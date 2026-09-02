"""Maintainer-side wiring of existing candidate binaries and Agulater commands."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

if __package__:
    from .experience import ROOT, load_json, local_config, save_json
else:
    from experience import ROOT, load_json, local_config, save_json


def invoke(binary: str, home: Path, *arguments: str) -> str:
    result = subprocess.run(
        [binary, *map(str, arguments)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
    )
    with (home / "prepare.log").open("a", encoding="utf-8") as log:
        log.write(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f"{arguments[0]} 未完成，详见 {home / 'prepare.log'}")
    return result.stdout


def write_fixture(workspace: Path, name: str, contents: str) -> None:
    path = workspace / name
    if not path.exists():
        path.write_text(contents, encoding="utf-8")


def make_pools(local: dict) -> dict:
    starter = load_json(ROOT / "starters/self-maintainer/.agents/pools.json")
    pools = [
        pool for pool in starter["pools"] if pool["id"] in {"deepseek", "codex-account"}
    ]
    for pool in pools:
        if pool["id"] == "deepseek":
            pool["id"] = "deepseek-subagent"
    default = "deepseek-subagent"
    if local.get("endpoint") and local.get("model"):
        local_pool = {
            "id": "local-default",
            "engine": "native",
            "provider": "openai-compatible",
            "endpoint": local["endpoint"],
            "model": local["model"],
            "reasoning_effort": "medium",
            "capabilities": ["read", "write", "edit", "shell"],
        }
        for key, suffix, fallback in (
            ("context_window", "CONTEXT_WINDOW", 32768),
            ("max_concurrency", "MAX_CONCURRENCY", 1),
            ("request_timeout_seconds", "TIMEOUT_SECONDS", 600),
        ):
            value = int(
                os.environ.get(
                    f"AGUL_ACCEPTANCE_LOCAL_{suffix}", local.get(key, fallback)
                )
            )
            if value <= 0:
                raise ValueError(f"local {key} must be positive")
            local_pool[key] = value
        pools.insert(0, local_pool)
        default = "local-default"
    return {"format": "agulater/pools/v2", "default_pool": default, "pools": pools}


def prepare_pools(ready: dict, home: Path, local: dict) -> None:
    master = home / "workspaces/master"
    save_json(master / ".agents/pools.json", make_pools(local))
    invoke(
        ready["agulater"],
        home,
        "prepare",
        "--path",
        str(master),
        "--home",
        str(home / "user"),
    )


def prepare(candidate_path: Path, home: Path) -> None:
    candidate = load_json(candidate_path)
    if not candidate:
        raise RuntimeError("维护者需要先构建本机 candidate；体验菜单不会自动构建。")
    home.mkdir(parents=True, exist_ok=True)
    # Candidate commits may share a version. A fresh install prefix prevents
    # Agulater's same-version reuse from serving yesterday's binary.
    build = Path(tempfile.mkdtemp(prefix="build-", dir=home))
    bin_dir = build / "bin"
    bin_dir.mkdir()
    agulater = bin_dir / ("agulater.exe" if os.name == "nt" else "agulater")
    shutil.copy2(candidate["artifacts"]["agulater"]["path"], agulater)
    binary = str(agulater)
    print("准备候选程序（本地安装，无公网下载）…", flush=True)
    invoke(binary, home, "setup", "user", "--if-missing", "--home", str(home / "user"))
    install = json.loads(
        invoke(
            binary,
            home,
            "runtime",
            "install",
            "--channel",
            "next",
            "--url",
            candidate["artifacts"]["runtime_index"],
            "--prefix",
            str(build / "runtime"),
            "--json",
        )
    )
    ready = {
        "agul": install["executable"],
        "agulater": binary,
        "candidate": {key: candidate[key] for key in ("versions", "repositories")},
    }
    invoke(ready["agul"], home, "--version")

    skill = home / "sample-skill"
    skill.mkdir(exist_ok=True)
    (skill / "SKILL.md").write_text(
        "---\nname: acceptance-note\ndescription: A tiny installed Skill for the experience menu.\n---\n"
        "When activated, say that the local acceptance Skill was loaded, then continue the user's task.\n",
        encoding="utf-8",
    )
    for name in ("deepseek", "glm", "codex", "master"):
        print(f"准备 {name} 场景（保留已有练习和会话）…", flush=True)
        workspace = home / "workspaces" / name
        workspace.mkdir(parents=True, exist_ok=True)
        if not (workspace / ".agents/package.json").exists():
            invoke(
                binary, home, "create", f"experience-{name}", "--path", str(workspace)
            )
        instructions = (
            "这是可自由体验的临时工作区。只操作本工作区内的练习，不修改产品源码。"
            "当用户说‘开始验收’，读取 README.md，运行 python -m unittest -v，"
            "用 Markdown 标题、短列表、行内代码和代码块总结。不要自行扩展任务。\n"
        )
        if name == "codex":
            instructions += (
                "本场景的‘开始验收’还要求：通过真实 Web Search 查询 Python 当前稳定版本，"
                "打开官方来源核实，给出两个来源链接；不能假装完成联网。\n"
            )
        if name == "master":
            instructions = (
                ROOT / "starters/self-maintainer/.agents/AGENTS.md"
            ).read_text(encoding="utf-8")
            instructions += (
                "\n这是临时练习区。用户说‘网页验收’时：用 web_open 打开 https://example.com/，"
                "无需配置搜索引擎。只有用户要求搜索时才使用 web_search。\n"
                "用户说‘委派验收’时：只调用一次 delegate_tasks，按顺序提交两个任务："
                "local-default 池的 repository-scout 读取 calculator.py 和 test_calculator.py，"
                "报告加法测试问题；deepseek-subagent 池的 short-patcher 仅修复 calculator.py "
                "并运行测试。两个任务 paths 均限定为这两个文件。"
                "master 随后亲自读取修改后的文件，对照 calculator.before.txt 并运行测试。"
                "使用真实子 Agent，不自行冒充子 Agent。不要重置用户已修复的文件。\n"
            )
        (workspace / ".agents/AGENTS.md").write_text(instructions, encoding="utf-8")
        write_fixture(
            workspace,
            "README.md",
            "# Agul 体验练习\n\n此目录用于读写、运行测试和会话恢复体验。\n",
        )
        operator = "-" if name == "master" else "+"
        calculator = f"def add(left, right):\n    return left {operator} right\n"
        write_fixture(workspace, "calculator.py", calculator)
        write_fixture(workspace, "calculator.before.txt", calculator)
        write_fixture(
            workspace,
            "test_calculator.py",
            "import unittest\nfrom calculator import add\n\nclass CalculatorTests(unittest.TestCase):\n"
            "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n",
        )
        extensions = [("skill", "acceptance-note", skill)]
        if name == "master":
            extensions.extend(
                ("plugin", plugin, ROOT / "plugins" / plugin)
                for plugin in ("coordinator", "web-search")
            )
            extensions.extend(
                ("package", role, ROOT / "agents" / role / ".agents")
                for role in (
                    "repository-scout",
                    "focused-tester",
                    "docs-editor",
                    "short-patcher",
                )
            )
        for kind, resource_id, source in extensions:
            # add also prepares the package, including the updated instructions.
            invoke(
                binary,
                home,
                "add",
                str(source),
                "--type",
                kind,
                "--name",
                resource_id,
                "--path",
                str(workspace),
                "--home",
                str(home / "user"),
            )
    local = local_config(home)
    prepare_pools(ready, home, local)
    if local.get("endpoint") and local.get("model"):
        save_json(home / "local.json", local)
    save_json(home / "ready.json", ready)
    print("准备完成。体验者只需打开 docs/acceptance/start.cmd；不会重新构建或安装。")
