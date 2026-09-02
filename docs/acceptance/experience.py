#!/usr/bin/env python3
"""Local owner experience menu; preparation is an explicit maintainer action."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HOME = ROOT / ".tmp" / "acceptance-experience"
CANDIDATE = ROOT / ".tmp" / "acceptance-candidate" / "candidate.json"
SCENES = {
    "1": ("DeepSeek minimal", "deepseek", ["--provider", "deepseek"], "开始验收"),
    "2": ("GLM Coding Plan", "glm", ["--provider", "glm"], "开始验收"),
    "3": ("ChatGPT + Web", "codex", ["--engine", "codex"], "开始验收"),
    "4": ("AgentKube 网页", "master", ["--provider", "glm"], "网页验收"),
    "5": ("本地 + DeepSeek 子 Agent", "master", ["--provider", "glm"], "委派验收"),
}


def load_json(path: Path, default=None):
    return (
        json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else default
    )


def save_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def child_env(ready: dict, home: Path) -> dict[str, str]:
    env = os.environ.copy()
    # Keep the real HOME and CODEX_HOME: account mode must reuse official login.
    # Explicit acceptance routes must not inherit a different native endpoint.
    for name in ("AGUL_PROVIDER", "AGUL_BASE_URL", "AGUL_MODEL", "AGUL_CONTEXT_WINDOW"):
        env.pop(name, None)
    env["AGUL_SUBAGENT_BINARY"] = ready["agul"]
    env["AGUL_STATE_DIR"] = str(home / "state")
    env["PATH"] = str(Path(ready["agulater"]).parent) + os.pathsep + env.get("PATH", "")
    return env


def local_config(home: Path) -> dict:
    saved = load_json(home / "local.json", {})
    if not saved:
        # Reuse only this workflow's previous fixture, never scan user projects.
        old = load_json(CANDIDATE.parent / "master" / ".agents" / "pools.json", {})
        pool = next((p for p in old.get("pools", []) if p["id"] == "local-default"), {})
        saved = {key: pool[key] for key in ("endpoint", "model") if key in pool}
    for key, name in (
        ("endpoint", "AGUL_ACCEPTANCE_LOCAL_ENDPOINT"),
        ("model", "AGUL_ACCEPTANCE_LOCAL_MODEL"),
    ):
        if os.environ.get(name, "").strip():
            saved[key] = os.environ[name].strip()
    return saved


def configure_local(ready: dict, home: Path) -> bool:
    from urllib.parse import urlparse

    if __package__:
        from .prepare_experience import prepare_pools
    else:
        from prepare_experience import prepare_pools

    config = local_config(home)
    for key, label in (("endpoint", "本地 HTTP(S) 地址"), ("model", "模型名称")):
        suffix = "（Enter 保留已有值）" if config.get(key) else "（留空取消）"
        value = input(f"{label}{suffix}: ").strip()
        if value:
            config[key] = value
        if not config.get(key):
            return False
    parsed = urlparse(config["endpoint"])
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        print("需要 HTTP(S) 地址；本地 HTTP 可以直接使用。")
        return False
    prepare_pools(ready, home, config)
    save_json(home / "local.json", config)
    print("已保存本机配置，之后无需重复填写。")
    return True


def chat_command(
    ready: dict, home: Path, scene: str, resume: str | None = None
) -> list[str]:
    _, workspace, connection, _ = SCENES[scene]
    root = home / "workspaces" / workspace
    command = [
        ready["agul"],
        "chat",
        "--workspace",
        str(root),
        "--launch",
        str(root / ".agents" / "runtime" / "launch.json"),
        "--state-dir",
        str(home / "state"),
        "--timeout-seconds",
        "600",
    ]
    # Resume restores the stored engine and model; never silently change them.
    return command + (
        [resume] if resume else connection + ["--reasoning-effort", "high"]
    )


def run_chat(ready: dict, home: Path, scene: str, resume: str | None = None) -> int:
    hint = "可直接继续对话" if resume else f"输入「{SCENES[scene][3]}」即可"
    print(
        f"进入 {SCENES[scene][0]}。{hint}；/exit 回到菜单。",
        flush=True,
    )
    # Inherit the real terminal. Pipes here would disable Agul's full-screen TUI.
    process = subprocess.Popen(
        chat_command(ready, home, scene, resume),
        cwd=home / "workspaces" / SCENES[scene][1],
        env=child_env(ready, home),
    )
    while True:
        try:
            return process.wait()
        except KeyboardInterrupt:
            # The foreground Agul process receives Ctrl+C too and owns stopping
            # the turn. Do not abandon it or start a second menu over its TUI.
            continue


def record_result(home: Path, ready: dict, scene: str, exit_code: int) -> None:
    if exit_code:
        print(f"Agul 退出码为 {exit_code}；这次可能没有正常完成。")
    choice = input("本次体验 [p 满意 / f 有问题 / Enter 暂不判断]: ").strip().lower()
    if choice not in {"p", "f"}:
        return
    note = input("一句备注（可留空）: ").strip()
    result = {
        "at": datetime.now(timezone.utc).isoformat(),
        "scene": SCENES[scene][0],
        "result": "pass" if choice == "p" else "fail",
        "note": note,
        "exit_code": exit_code,
        "candidate": ready["candidate"],
    }
    with (home / "results.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(result, ensure_ascii=False) + "\n")


def menu(ready: dict, home: Path) -> None:
    previous = load_json(home / "last-scene.json", "1")
    if previous not in SCENES:
        previous = "1"
    while True:
        print("\nAgul 体验 · 复用已有环境，不重新安装\n")
        print(
            " · ".join(
                f"{name} {version}"
                for name, version in ready["candidate"]["versions"].items()
            )
        )
        for key, (label, _, _, prompt) in SCENES.items():
            print(f"  {key}  {label} — 输入「{prompt}」")
        print(f"  6  继续上次场景（{SCENES[previous][0]}）\n  7  选择上次场景的历史")
        print("  8  ChatGPT 官方登录\n  L  本地模型设置（只需一次）\n  0  退出")
        choice = input("> ").strip().lower()
        if choice == "0":
            return
        try:
            if choice == "l":
                configure_local(ready, home)
            elif choice == "8":
                subprocess.run(
                    [ready["agul"], "account", "login"],
                    env=child_env(ready, home),
                    check=True,
                )
            elif choice in SCENES or choice in {"6", "7"}:
                scene = choice if choice in SCENES else previous
                required = ["DEEPSEEK_API_KEY"] if scene == "1" else []
                if scene in {"2", "4", "5"}:
                    required.append("GLM_API_KEY")
                if scene == "5":
                    required.append("DEEPSEEK_API_KEY")
                missing = [
                    name for name in required if not os.environ.get(name, "").strip()
                ]
                if missing:
                    print("此场景缺少 " + ", ".join(missing) + "；其他场景仍可体验。")
                    continue
                if scene == "5" and not load_json(home / "local.json", {}).get("model"):
                    if not configure_local(ready, home):
                        continue
                resume = {"6": "--continue", "7": "--resume"}.get(choice)
                save_json(home / "last-scene.json", scene)
                previous = scene
                record_result(home, ready, scene, run_chat(ready, home, scene, resume))
            else:
                print("请选择菜单中的数字或 L。")
        except (
            OSError,
            ValueError,
            RuntimeError,
            subprocess.CalledProcessError,
        ) as error:
            print(f"本次操作未完成：{error}。环境保留，可以重试或换一个场景。")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Open the prepared Agul experience menu."
    )
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME)
    parser.add_argument(
        "--prepare",
        action="store_true",
        help="Maintainer only: prepare existing local artifacts.",
    )
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    args = parser.parse_args()
    home = args.home.resolve()
    try:
        if args.prepare:
            if __package__:
                from .prepare_experience import prepare
            else:
                from prepare_experience import prepare
            prepare(args.candidate.resolve(), home)
            return 0
        ready = load_json(home / "ready.json")
        if not ready or not all(
            Path(ready[name]).is_file() for name in ("agul", "agulater")
        ):
            print(
                "维护者尚未准备好本机体验环境。无需自己构建或安装，请让维护者完成准备。"
            )
            return 1
        menu(ready, home)
        return 0
    except (EOFError, KeyboardInterrupt):
        print("\n已退出；环境和会话保留。")
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"未能打开体验：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
