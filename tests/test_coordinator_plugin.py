from __future__ import annotations

import dataclasses
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "coordinator"
SCRIPT = PLUGIN / "coordinator.py"
MANIFEST = PLUGIN / "plugin.json"


FAKE_AGUL = r"""
from pathlib import Path
import json
import os
import sys
import time

root = Path.cwd()
session_id = f"session-{os.getpid()}"


def emit(value):
    print(json.dumps(value), flush=True)


def response(request, result=None, error=None):
    value = {"jsonrpc": "2.0", "id": request["id"]}
    if error is None:
        value["result"] = result
    else:
        value["error"] = error
    emit(value)


def usage(name):
    return {
        "purpose": "chat",
        "provider": "openai-compatible",
        "origin": "http://pool.test",
        "response_id": name,
        "observed_at_unix_seconds": 1,
        "observation_time_source": "host",
        "reported_model": "fake-model",
        "input_tokens": 100,
        "output_tokens": 10,
        "total_tokens": 110,
        "cache_hit_input_tokens": 60,
        "cache_miss_input_tokens": 40,
        "reasoning_tokens": 3,
        "cost": {"currency": "USD", "femto_units": "100000000000"},
        "price_ref": None,
        "stale": False,
        "assumptions": [],
        "unpriced_reason": None,
    }


def emit_tool_run(name, call_id, progress_count=1, duplicate_progress=False):
    emit({
        "jsonrpc": "2.0",
        "method": "ari.event",
        "params": {
            "session_id": session_id,
            "kind": "tool",
            "phase": "started",
            "name": "read",
            "detail": f"{name}.txt\nsection",
        },
    })
    for index in range(progress_count):
        preview = (
            f"{name}.txt\nstep {index + 1}"
            if progress_count > 1
            else f"{name}.txt\n50%"
        )
        for _ in range(2 if duplicate_progress else 1):
            emit({
                "jsonrpc": "2.0",
                "method": "ari.event",
                "params": {
                    "session_id": session_id,
                    "kind": "tool_progress",
                    "call_id": call_id,
                    "seq": 99,
                    "task_id": f"inner-{name}",
                    "stage": "reading",
                    "preview": preview,
                },
            })
    emit({
        "jsonrpc": "2.0",
        "method": "ari.event",
        "params": {
            "session_id": session_id,
            "kind": "tool",
            "phase": "finished",
            "name": "read",
            "detail": f"{name}.txt\nsection",
            "ok": name != "read-b",
            "elapsed_ms": 1250,
        },
    })


for line in sys.stdin:
    request = json.loads(line)
    method = request["method"]
    if method == "ari.initialize":
        response(request, {"ari": "0.2"})
    elif method == "ari.start_session":
        (root / f"params-{os.getpid()}.json").write_text(
            json.dumps(request["params"]), encoding="utf-8"
        )
        response(request, {"session_id": session_id, "model": "fake-model"})
    elif method == "ari.send":
        prompt = request["params"]["input"]
        task_line = prompt.splitlines()[0]
        name, effect, outcome = task_line.split("|")
        (root / f"started-{name}").touch()
        if effect == "single":
            pass
        elif effect == "read":
            deadline = time.monotonic() + 2
            while len(list(root.glob("started-read-*"))) < 2 and time.monotonic() < deadline:
                time.sleep(0.01)
            if len(list(root.glob("started-read-*"))) < 2:
                response(request, error={"code": -32099, "message": "reads were not concurrent"})
                continue
        else:
            if len(list(root.glob("finished-read-*"))) < 2:
                response(request, error={"code": -32098, "message": "write ran before reads"})
                continue
            if name == "write-2" and not (root / "finished-write-1").is_file():
                response(request, error={"code": -32097, "message": "writes were not serial"})
                continue
        emit({
            "jsonrpc": "2.0",
            "method": "ari.event",
            "params": {
                "session_id": session_id,
                "kind": "reasoning",
                "text": f"SECRET_REASONING_{name}",
            },
        })
        emit({
            "jsonrpc": "2.0",
            "method": "ari.event",
            "params": {
                "session_id": session_id,
                "kind": "text",
                "text": f"SECRET_TEXT_{name}",
            },
        })
        progress_count = 100 if name == "burst" else 1
        emit_tool_run(
            name,
            f"child-call-{name}",
            progress_count,
            duplicate_progress=name == "burst",
        )
        tool_calls = 1
        if name == "repeat-tools":
            emit_tool_run(name, f"child-call-{name}-2")
            tool_calls = 2
        emit({
            "jsonrpc": "2.0",
            "method": "ari.event",
            "params": {
                "session_id": session_id,
                "kind": "usage",
                "ledger_entry": usage(name),
            },
        })
        payload = {
            "format": "agul/handoff/v1",
            "status": outcome,
            "summary": f"summary:{name}",
            "evidence": [{"task": name}],
            "changes": [],
            "verification": [],
            "risks": [],
            "next_steps": [],
        }
        if outcome == "invalid":
            payload["verification"] = "required"
            text = (
                f"answer:{name}\n"
                '<agul-handoff format="agul/handoff/v1">'
                + json.dumps(payload)
                + "</agul-handoff>"
            )
            handoff = None
        else:
            text = (
                f"answer:{name}\n"
                '<agul-handoff format="agul/handoff/v1">'
                + json.dumps(payload)
                + "</agul-handoff>"
            )
            handoff = payload
        response(request, {
            "session_id": session_id,
            "text": text,
            "handoff": handoff,
            "model_rounds": 1,
            "tool_calls": tool_calls,
        })
        (root / f"finished-{name}").touch()
    elif method == "ari.close_session":
        (root / f"closed-{os.getpid()}").touch()
        response(request, {"closed": True})
"""


def _load_plugin():
    spec = importlib.util.spec_from_file_location("agentkube_coordinator", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load coordinator Plugin")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_runtime(
    workspace: Path, pool: dict[str, object] | None = None
) -> Path:
    runtime = workspace / ".agents" / "runtime"
    runtime.mkdir(parents=True)
    launch = runtime / "launch.json"
    launch.write_text('{"format":"agul/launch/v2"}\n', encoding="utf-8")
    specialists = []
    for specialist_id, effect, defaults in [
        (
            "repository-scout",
            "read",
            {
                "reasoning_effort": "medium",
                "max_rounds": 4,
                "max_tool_calls": 8,
                "max_tokens": 1536,
                "timeout_seconds": 10,
            },
        ),
        (
            "docs-editor",
            "write",
            {
                "reasoning_effort": "medium",
                "max_rounds": 6,
                "max_tool_calls": 12,
                "max_tokens": 2048,
                "timeout_seconds": 10,
            },
        ),
    ]:
        specialist_root = runtime / "specialists" / specialist_id
        specialist_root.mkdir(parents=True)
        specialist_launch = specialist_root / "launch.json"
        specialist_snapshot = specialist_root / "snapshot.json"
        specialist_launch.write_text('{"format":"agul/launch/v2"}\n', encoding="utf-8")
        specialist_snapshot.write_text("{}\n", encoding="utf-8")
        specialists.append(
            {
                "id": specialist_id,
                "version": "0.1.0",
                "description": specialist_id,
                "accepts": ["test"],
                "workspace_effect": effect,
                "launch_path": specialist_launch.relative_to(runtime).as_posix(),
                "snapshot_path": specialist_snapshot.relative_to(runtime).as_posix(),
                "requirements": {
                    "min_context_window": 16384,
                    "capabilities": ["read", "shell"]
                    if effect == "read"
                    else ["read", "write", "edit", "shell"],
                },
                "defaults": defaults,
                "handoff_format": "agul/handoff/v1",
            }
        )
    (runtime / "specialists.json").write_text(
        json.dumps({"format": "agulater/specialists/v1", "specialists": specialists}),
        encoding="utf-8",
    )
    if pool is None:
        pool = {
            "id": "local",
            "engine": "native",
            "provider": "openai-compatible",
            "endpoint": "http://pool.test/v1/chat/completions",
            "model": "fake-model",
            "reasoning_effort": "low",
            "context_window": 32768,
            "capabilities": ["read", "write", "edit", "shell"],
            "max_concurrency": 2,
            "request_timeout_seconds": 17,
        }
    (runtime / "pools.json").write_text(
        json.dumps(
            {
                "format": "agulater/pools/v2",
                "default_pool": pool["id"],
                "pools": [pool],
            }
        ),
        encoding="utf-8",
    )
    return launch


def _invoke(
    workspace: Path,
    launch: Path,
    tasks: list[dict[str, object]] | None = None,
    *,
    command: str | None = None,
):
    (workspace / "ari").write_text(textwrap.dedent(FAKE_AGUL), encoding="utf-8")
    environment = os.environ.copy()
    environment["AGUL_SUBAGENT_BINARY"] = sys.executable
    request = {
        **(
            {"command": "agent", "arguments": command}
            if command is not None
            else {"tool": "delegate_tasks", "arguments": {"tasks": tasks}}
        ),
        "context": {
            "call_id": "call-1",
            "session_id": "master-1",
            "workspace": str(workspace),
            "launch_path": str(launch),
        },
    }
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=PLUGIN,
        input=json.dumps(request) + "\n",
        capture_output=True,
        check=False,
        encoding="utf-8",
        env=environment,
        timeout=15,
    )


class CoordinatorPluginTests(unittest.TestCase):
    def test_task_prompt_contains_only_task_context_and_paths(self) -> None:
        plugin = _load_plugin()
        task = plugin.TaskSpec(
            index=0,
            id="internal-id",
            specialist=None,
            pool=None,
            task="Inspect the selected files.",
            context="Focus on prompt assembly.",
            paths=("plugins/coordinator", "tests"),
        )

        self.assertEqual(
            plugin._task_prompt(task),
            "Inspect the selected files.\n\n"
            "Additional context:\n"
            "Focus on prompt assembly.\n\n"
            "Scoped paths:\n"
            "- plugins/coordinator\n"
            "- tests",
        )
        self.assertEqual(
            plugin._task_prompt(dataclasses.replace(task, context=None, paths=())),
            "Inspect the selected files.",
        )

    def test_manifest_exposes_prepared_specialist_contract(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

        self.assertEqual(manifest["format"], "agul/plugin/v2")
        self.assertEqual(manifest["name"], "coordinator")
        self.assertEqual(manifest["version"], "0.3.2-rc.1")
        self.assertEqual(manifest["timeout_seconds"], 6300)
        self.assertEqual(
            manifest["commands"],
            [
                {
                    "name": "agent",
                    "description": "Run one prepared specialist: /agent <specialist> <task>",
                }
            ],
        )
        self.assertEqual(
            [tool["name"] for tool in manifest["tools"]], ["delegate_tasks"]
        )
        parameters = manifest["tools"][0]["parameters"]
        self.assertEqual(parameters["required"], ["tasks"])
        self.assertEqual(parameters["properties"]["tasks"]["maxItems"], 5)
        item = parameters["properties"]["tasks"]["items"]
        self.assertEqual(item["required"], ["specialist", "task"])
        self.assertEqual(
            set(item["properties"]),
            {"id", "specialist", "pool", "task", "context", "paths"},
        )
        self.assertNotIn("minLength", item["properties"]["pool"])

    def test_agent_command_runs_a_prepared_specialist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            launch = _write_runtime(workspace)
            completed = _invoke(
                workspace,
                launch,
                command="repository-scout solo|single|completed",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            events = [json.loads(line) for line in completed.stdout.splitlines()]
            self.assertEqual(events[-1]["type"], "result")
            self.assertTrue(events[-1]["ok"])
            self.assertEqual(events[-1]["content"]["status"], "completed")
            self.assertEqual(
                events[-1]["content"]["results"][0]["specialist"],
                "repository-scout",
            )
            params = json.loads(
                next(workspace.glob("params-*.json")).read_text(encoding="utf-8")
            )
            self.assertEqual(
                {
                    key: params[key]
                    for key in (
                        "parent_session_id",
                        "delegation_id",
                        "task_id",
                        "specialist_id",
                        "pool_id",
                    )
                },
                {
                    "parent_session_id": "master-1",
                    "delegation_id": events[-1]["content"]["delegation_id"],
                    "task_id": "task-1",
                    "specialist_id": "repository-scout",
                    "pool_id": "local",
                },
            )

    def test_forwards_only_compact_child_tool_progress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            launch = _write_runtime(workspace)
            completed = _invoke(
                workspace,
                launch,
                [
                    {
                        "id": "read-a",
                        "specialist": "repository-scout",
                        "task": "read-a|read|completed",
                    },
                    {
                        "id": "read-b",
                        "specialist": "repository-scout",
                        "task": "read-b|read|completed",
                    },
                ],
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            events = [json.loads(line) for line in completed.stdout.splitlines()]
            self.assertEqual(
                [event["seq"] for event in events], list(range(1, len(events) + 1))
            )
            self.assertTrue(all(event["call_id"] == "call-1" for event in events))
            forwarded = [
                event
                for event in events
                if event["type"] == "progress"
                and event["stage"] in {"read", "reading"}
            ]
            for task_id in ("read-a", "read-b"):
                task_events = [
                    event for event in forwarded if event.get("task_id") == task_id
                ]
                finished_marker = "✓" if task_id == "read-a" else "!"
                self.assertEqual(
                    [event["stage"] for event in task_events],
                    ["read", "reading", "read"],
                )
                self.assertEqual(
                    [event["preview"] for event in task_events],
                    [
                        f"◆ {task_id}.txt section",
                        f"{task_id}.txt 50%",
                        f"{finished_marker} {task_id}.txt section · 1250ms",
                    ],
                )
                self.assertTrue(
                    all(
                        set(event)
                        == {"type", "call_id", "seq", "task_id", "stage", "preview"}
                        for event in task_events
                    )
                )
            self.assertNotIn("SECRET_REASONING", completed.stdout)
            self.assertNotIn("SECRET_TEXT", completed.stdout)
            self.assertNotIn("child-call", completed.stdout)
            self.assertNotIn("inner-read", completed.stdout)
            self.assertEqual(
                [result["tool_calls"] for result in events[-1]["content"]["results"]],
                [1, 1],
            )

    def test_bounds_repeated_child_progress_without_losing_the_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            launch = _write_runtime(workspace)
            completed = _invoke(
                workspace,
                launch,
                [
                    {
                        "id": "burst",
                        "specialist": "repository-scout",
                        "task": "burst|single|completed",
                    }
                ],
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            events = [json.loads(line) for line in completed.stdout.splitlines()]
            reading = [
                event
                for event in events
                if event["type"] == "progress" and event["stage"] == "reading"
            ]
            self.assertEqual(len(reading), 32)
            self.assertEqual(reading[0]["preview"], "burst.txt step 1")
            self.assertEqual(reading[-1]["preview"], "burst.txt step 32")
            limited = [
                event
                for event in events
                if event["type"] == "progress"
                and event["preview"] == "… additional child progress omitted"
            ]
            self.assertEqual(len(limited), 1)
            self.assertEqual(sum(event["type"] == "result" for event in events), 1)
            self.assertTrue(events[-1]["ok"])
            self.assertEqual(events[-1]["content"]["usage"]["responses"], 1)
            self.assertEqual(
                events[-1]["content"]["results"][0]["tool_calls"],
                1,
            )

    def test_keeps_identical_progress_from_distinct_child_tool_calls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            launch = _write_runtime(workspace)
            completed = _invoke(
                workspace,
                launch,
                [
                    {
                        "id": "repeat-tools",
                        "specialist": "repository-scout",
                        "task": "repeat-tools|single|completed",
                    }
                ],
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            events = [json.loads(line) for line in completed.stdout.splitlines()]
            reading = [
                event
                for event in events
                if event["type"] == "progress" and event["stage"] == "reading"
            ]
            self.assertEqual(
                [event["preview"] for event in reading],
                ["repeat-tools.txt 50%", "repeat-tools.txt 50%"],
            )
            self.assertEqual(
                events[-1]["content"]["results"][0]["tool_calls"],
                2,
            )

    def test_pool_reasoning_effort_overrides_specialist_with_fallback(self) -> None:
        plugin = _load_plugin()
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            runtime = _write_runtime(workspace).parent
            specialist = plugin._specialists(runtime)["repository-scout"]
            pool = plugin._pools(runtime)[1]["local"]

            configured = plugin._worker_config(specialist, pool, {})
            self.assertEqual(configured.reasoning_effort, "low")

            fallback_pool = dataclasses.replace(pool, reasoning_effort=None)
            fallback = plugin._worker_config(specialist, fallback_pool, {})
            self.assertEqual(fallback.reasoning_effort, "medium")

    def test_pools_v2_strictly_rejects_invalid_and_cross_engine_fields(self) -> None:
        plugin = _load_plugin()
        native = {
            "id": "local",
            "engine": "native",
            "provider": "openai-compatible",
            "endpoint": "http://pool.test/v1/chat/completions",
            "model": "fake-model",
            "api_key_env": "POOL_API_KEY",
            "context_window": 32768,
            "capabilities": ["read", "shell"],
            "max_concurrency": 2,
            "request_timeout_seconds": 17,
        }
        codex = {
            "id": "chatgpt",
            "engine": "codex",
            "capabilities": ["read", "shell"],
            "max_concurrency": 2,
            "request_timeout_seconds": 17,
        }
        cases = [
            (
                "v1",
                {"format": "agulater/pools/v1", "pools": []},
                "format must be agulater/pools/v2",
            ),
            (
                "unknown top-level field",
                {"format": "agulater/pools/v2", "pools": [], "extra": True},
                "pools.extra is not allowed",
            ),
            (
                "missing engine",
                {
                    "format": "agulater/pools/v2",
                    "default_pool": "local",
                    "pools": [{key: value for key, value in native.items() if key != "engine"}],
                },
                "pools[0].engine must be a non-empty string",
            ),
            (
                "unknown engine",
                {
                    "format": "agulater/pools/v2",
                    "default_pool": "local",
                    "pools": [{**native, "engine": "remote"}],
                },
                "pools[0].engine must be native or codex",
            ),
            (
                "native missing required endpoint",
                {
                    "format": "agulater/pools/v2",
                    "default_pool": "local",
                    "pools": [{key: value for key, value in native.items() if key != "endpoint"}],
                },
                "pools[0].endpoint must be a non-empty string",
            ),
            (
                "native rejects codex command",
                {
                    "format": "agulater/pools/v2",
                    "default_pool": "local",
                    "pools": [{**native, "codex_command": "codex"}],
                },
                "pools[0].codex_command is not allowed for native engine",
            ),
            (
                "codex rejects provider",
                {
                    "format": "agulater/pools/v2",
                    "default_pool": "chatgpt",
                    "pools": [{**codex, "provider": "openai"}],
                },
                "pools[0].provider is not allowed for codex engine",
            ),
            (
                "override must be boolean",
                {
                    "format": "agulater/pools/v2",
                    "default_pool": "chatgpt",
                    "pools": [{**codex, "override": "yes"}],
                },
                "pools[0].override must be a boolean",
            ),
            (
                "invalid id",
                {
                    "format": "agulater/pools/v2",
                    "default_pool": "Bad ID",
                    "pools": [{**codex, "id": "Bad ID"}],
                },
                "pools[0].id is invalid",
            ),
            (
                "invalid environment name",
                {
                    "format": "agulater/pools/v2",
                    "default_pool": "local",
                    "pools": [{**native, "api_key_env": "BAD-NAME"}],
                },
                "pools[0].api_key_env is invalid",
            ),
            (
                "explicit null",
                {
                    "format": "agulater/pools/v2",
                    "default_pool": "chatgpt",
                    "pools": [{**codex, "model": None}],
                },
                "pools[0].model must be a non-empty string",
            ),
            (
                "boolean integer",
                {
                    "format": "agulater/pools/v2",
                    "default_pool": "chatgpt",
                    "pools": [{**codex, "max_concurrency": True}],
                },
                "pools[0].max_concurrency must be a positive integer",
            ),
            (
                "duplicate capability",
                {
                    "format": "agulater/pools/v2",
                    "default_pool": "chatgpt",
                    "pools": [{**codex, "capabilities": ["read", "read"]}],
                },
                "pools[0].capabilities must not contain duplicates",
            ),
            (
                "missing default",
                {"format": "agulater/pools/v2", "pools": [codex]},
                "default_pool is required when pools are configured",
            ),
            (
                "unknown default",
                {
                    "format": "agulater/pools/v2",
                    "default_pool": "missing",
                    "pools": [codex],
                },
                "default_pool does not exist: missing",
            ),
        ]

        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            path = runtime / "pools.json"
            for label, document, expected in cases:
                with self.subTest(case=label):
                    path.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaises(plugin.PluginError) as raised:
                        plugin._pools(runtime)
                    self.assertIn(expected, str(raised.exception))

            path.write_text(
                json.dumps(
                    {
                        "format": "agulater/pools/v2",
                        "default_pool": "chatgpt",
                        "pools": [{**codex, "override": True}],
                    }
                ),
                encoding="utf-8",
            )
            default_pool, parsed = plugin._pools(runtime)
            self.assertEqual(default_pool, "chatgpt")
            self.assertEqual(set(parsed), {"chatgpt"})

    def test_codex_context_is_only_a_routing_declaration(self) -> None:
        plugin = _load_plugin()
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            runtime = _write_runtime(
                workspace,
                {
                    "id": "chatgpt",
                    "engine": "codex",
                    "capabilities": ["read", "write", "edit", "shell"],
                    "max_concurrency": 2,
                    "request_timeout_seconds": 23,
                },
            ).parent
            specialists = plugin._specialists(runtime)
            default_pool, pools = plugin._pools(runtime)
            selected = plugin._tasks(
                [{"specialist": "repository-scout", "task": "inspect"}],
                specialists,
                default_pool,
                pools,
            )
            self.assertEqual(selected[0].pool.id, "chatgpt")
            config = plugin._worker_config(
                specialists["repository-scout"], pools["chatgpt"], {}
            )
            self.assertEqual(
                config.session_params(workspace, specialists["repository-scout"].launch_path),
                {
                    "workspace": str(workspace),
                    "launch_path": str(specialists["repository-scout"].launch_path),
                    "engine": "codex",
                    "timeout_seconds": 23,
                    "reasoning_effort": "medium",
                },
            )

            document = json.loads((runtime / "pools.json").read_text(encoding="utf-8"))
            document["pools"][0]["context_window"] = 8192
            (runtime / "pools.json").write_text(json.dumps(document), encoding="utf-8")
            default_pool, pools = plugin._pools(runtime)
            with self.assertRaises(plugin.PluginError) as raised:
                plugin._tasks(
                    [{"specialist": "repository-scout", "task": "inspect"}],
                    specialists,
                    default_pool,
                    pools,
                )
            self.assertEqual(raised.exception.code, "pool_incompatible")
            self.assertIn("context_window is below", str(raised.exception))

    def test_codex_pool_sends_only_codex_ari_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            launch = _write_runtime(
                workspace,
                {
                    "id": "chatgpt",
                    "engine": "codex",
                    "model": "gpt-codex",
                    "codex_command": "codex-custom",
                    "reasoning_effort": "high",
                    "context_window": 32768,
                    "capabilities": ["read", "write", "edit", "shell"],
                    "max_concurrency": 2,
                    "request_timeout_seconds": 23,
                },
            )
            completed = _invoke(
                workspace,
                launch,
                [
                    {
                        "id": "codex",
                        "specialist": "repository-scout",
                        "task": "codex|single|completed",
                    }
                ],
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            events = [json.loads(line) for line in completed.stdout.splitlines()]
            self.assertTrue(events[-1]["ok"])
            params = json.loads(
                next(workspace.glob("params-*.json")).read_text(encoding="utf-8")
            )
            self.assertEqual(
                params,
                {
                    "workspace": str(workspace),
                    "launch_path": str(
                        launch.parent / "specialists" / "repository-scout" / "launch.json"
                    ),
                    "engine": "codex",
                    "timeout_seconds": 23,
                    "reasoning_effort": "high",
                    "model": "gpt-codex",
                    "codex_command": "codex-custom",
                    "parent_session_id": "master-1",
                    "delegation_id": events[-1]["content"]["delegation_id"],
                    "task_id": "codex",
                    "specialist_id": "repository-scout",
                    "pool_id": "chatgpt",
                },
            )

    def test_unknown_pool_explains_the_default_and_specialist_distinction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            launch = _write_runtime(workspace)
            completed = _invoke(
                workspace,
                launch,
                [
                    {
                        "specialist": "repository-scout",
                        "pool": "repository-scout",
                        "task": "inspect the repository",
                    }
                ],
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            events = [json.loads(line) for line in completed.stdout.splitlines()]
            self.assertEqual(len(events), 1)
            self.assertFalse(events[0]["ok"])
            self.assertEqual(events[0]["error"]["code"], "pool_not_found")
            self.assertEqual(events[0]["error"]["stage"], "prepare")
            self.assertIn(
                "pool selects an execution pool", events[0]["error"]["message"]
            )
            self.assertIn(
                "omit pool to use default_pool local", events[0]["error"]["message"]
            )

    def test_blank_pool_uses_default_pool(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            launch = _write_runtime(workspace)
            completed = _invoke(
                workspace,
                launch,
                [
                    {
                        "specialist": "repository-scout",
                        "pool": "",
                        "task": "inspect the repository",
                    }
                ],
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            events = [json.loads(line) for line in completed.stdout.splitlines()]
            self.assertTrue(events[-1]["ok"])
            params = json.loads(
                next(workspace.glob("params-*.json")).read_text(encoding="utf-8")
            )
            self.assertEqual(params["pool_id"], "local")

    def test_read_tasks_are_concurrent_writes_are_serial_and_handoffs_are_authoritative(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            launch = _write_runtime(workspace)
            completed = _invoke(
                workspace,
                launch,
                [
                    {
                        "id": "read-a",
                        "specialist": "repository-scout",
                        "task": "read-a|read|completed",
                        "paths": ["src"],
                    },
                    {
                        "id": "write-1",
                        "specialist": "docs-editor",
                        "task": "write-1|write|completed",
                    },
                    {
                        "id": "read-b",
                        "specialist": "repository-scout",
                        "task": "read-b|read|completed",
                        "context": "Check the implementation.",
                    },
                    {
                        "id": "write-2",
                        "specialist": "docs-editor",
                        "task": "write-2|write|completed",
                    },
                ],
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stderr, "")
            events = [json.loads(line) for line in completed.stdout.splitlines()]
            self.assertEqual(
                [event["seq"] for event in events], list(range(1, len(events) + 1))
            )
            self.assertTrue(all(event["call_id"] == "call-1" for event in events))
            self.assertEqual(events[-1]["type"], "result")
            self.assertTrue(events[-1]["ok"])
            self.assertEqual(sum(event["type"] == "result" for event in events), 1)
            self.assertEqual(sum(event["type"] == "session" for event in events), 4)

            content = events[-1]["content"]
            self.assertRegex(content["delegation_id"], r"^delegation-")
            self.assertEqual(content["status"], "completed")
            self.assertEqual(
                [result["id"] for result in content["results"]],
                ["read-a", "write-1", "read-b", "write-2"],
            )
            self.assertEqual(
                list(content["handoff"]),
                ["read-a", "write-1", "read-b", "write-2"],
            )
            self.assertEqual(content["handoff"]["read-a"]["format"], "agul/handoff/v1")
            self.assertEqual(
                content["handoff"]["write-2"]["summary"], "summary:write-2"
            )
            self.assertEqual(content["usage"]["responses"], 4)
            self.assertEqual(
                content["usage"]["total_cost"],
                {"currency": "USD", "femto_units": "400000000000"},
            )
            self.assertEqual(len(list(workspace.glob("closed-*"))), 4)

            params = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in workspace.glob("params-*.json")
            ]
            self.assertEqual(len(params), 4)
            self.assertTrue(
                all(
                    set(value)
                    == {
                        "workspace",
                        "launch_path",
                        "engine",
                        "timeout_seconds",
                        "reasoning_effort",
                        "base_url",
                        "model",
                        "context_window",
                        "max_rounds",
                        "max_tool_calls",
                        "max_tokens",
                        "parent_session_id",
                        "delegation_id",
                        "task_id",
                        "specialist_id",
                        "pool_id",
                    }
                    for value in params
                )
            )
            self.assertTrue(
                all(value["workspace"] == str(workspace) for value in params)
            )
            self.assertTrue(all(value["engine"] == "native" for value in params))
            self.assertTrue(
                all(
                    value["base_url"] == "http://pool.test/v1/chat/completions"
                    for value in params
                )
            )
            self.assertTrue(all(value["model"] == "fake-model" for value in params))
            self.assertTrue(all(value["context_window"] == 32768 for value in params))
            self.assertTrue(all(value["timeout_seconds"] == 17 for value in params))
            self.assertTrue(
                all(value["parent_session_id"] == "master-1" for value in params)
            )
            self.assertTrue(
                all(
                    value["delegation_id"] == content["delegation_id"]
                    for value in params
                )
            )
            self.assertEqual(
                {
                    (
                        value["task_id"],
                        value["specialist_id"],
                        value["pool_id"],
                    )
                    for value in params
                },
                {
                    ("read-a", "repository-scout", "local"),
                    ("write-1", "docs-editor", "local"),
                    ("read-b", "repository-scout", "local"),
                    ("write-2", "docs-editor", "local"),
                },
            )
            self.assertEqual(
                {Path(value["launch_path"]).parent.name for value in params},
                {"repository-scout", "docs-editor"},
            )

    def test_missing_authoritative_handoff_is_a_task_failure(self) -> None:
        plugin = _load_plugin()
        with self.assertRaises(plugin.WorkerError):
            plugin._authoritative_handoff(None)

    def test_authoritative_handoff_is_used_without_reparsing_visible_text(self) -> None:
        plugin = _load_plugin()
        handoff = plugin._authoritative_handoff(
            {
                "format": "agul/handoff/v1",
                "status": "completed",
                "summary": "done",
                "evidence": [],
                "changes": [],
                "verification": [],
                "risks": [],
                "next_steps": [],
            }
        )

        self.assertEqual(handoff["format"], "agul/handoff/v1")
        self.assertEqual(handoff["status"], "completed")

    def test_one_invalid_handoff_keeps_sibling_handoff_and_usage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            launch = _write_runtime(workspace)
            completed = _invoke(
                workspace,
                launch,
                [
                    {
                        "id": "read-a",
                        "specialist": "repository-scout",
                        "task": "read-a|read|completed",
                    },
                    {
                        "id": "read-b",
                        "specialist": "repository-scout",
                        "task": "read-b|read|invalid",
                    },
                ],
            )

            events = [json.loads(line) for line in completed.stdout.splitlines()]
            content = events[-1]["content"]
            self.assertEqual(content["status"], "partial")
            self.assertEqual(
                [result["status"] for result in content["results"]],
                ["completed", "failed"],
            )
            self.assertEqual(content["results"][1]["error"]["stage"], "handoff")
            self.assertEqual(list(content["handoff"]), ["read-a"])
            self.assertEqual(content["usage"]["responses"], 2)

    def test_missing_prepared_registry_returns_one_terminal_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            runtime = workspace / ".agents" / "runtime"
            runtime.mkdir(parents=True)
            launch = runtime / "launch.json"
            launch.write_text("{}", encoding="utf-8")
            completed = _invoke(
                workspace,
                launch,
                [
                    {
                        "specialist": "repository-scout",
                        "task": "read-a|read|completed",
                    }
                ],
            )

            self.assertEqual(completed.returncode, 0)
            events = [json.loads(line) for line in completed.stdout.splitlines()]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["type"], "result")
            self.assertFalse(events[0]["ok"])
            self.assertEqual(events[0]["error"]["code"], "registry_error")


if __name__ == "__main__":
    unittest.main()
