from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import json
import os
from pathlib import Path
from queue import Empty, Queue
import re
import subprocess
import sys
from threading import Lock, Semaphore, Thread
from time import monotonic
from typing import Any, Callable, Mapping, TextIO
from uuid import uuid4


MAX_TASKS = 5
MAX_CHILD_PROGRESS_EVENTS = 32
STDERR_TAIL_CHARS = 2_000
COORDINATOR_VERSION = "0.3.2-rc.1"
HANDOFF_FORMAT = "agul/handoff/v1"
SPECIALISTS_FORMAT = "agulater/specialists/v1"
POOLS_FORMAT = "agulater/pools/v2"
PACKAGE_ID_PATTERN = re.compile(
    r"^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?(?:/[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?)*$"
)
ENVIRONMENT_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
POOL_COMMON_FIELDS = {
    "id",
    "engine",
    "description",
    "labels",
    "reasoning_effort",
    "capabilities",
    "max_concurrency",
    "request_timeout_seconds",
    "override",
}
POOL_ENGINE_FIELDS = {
    "native": {"provider", "endpoint", "model", "api_key_env", "context_window"},
    "codex": {"model", "codex_command", "context_window"},
}


class PluginError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str = "invalid_request",
        stage: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.retryable = retryable

    def value(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "code": self.code,
            "message": str(self),
            "retryable": self.retryable,
        }
        if self.stage is not None:
            value["stage"] = self.stage
        return value


class WorkerError(Exception):
    def __init__(self, stage: str, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.stage = stage
        self.code = code

    def value(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "stage": self.stage,
            "message": str(self),
        }
        if self.code is not None:
            value["code"] = self.code
        return value


class EventEmitter:
    """Serialize Plugin v2 events from concurrent workers."""

    def __init__(self, call_id: str, stream: TextIO | None = None) -> None:
        self.call_id = call_id
        self.stream = stream
        self.events: list[dict[str, Any]] = []
        self.sequence = 0
        self.lock = Lock()

    def emit(self, event_type: str, **fields: Any) -> dict[str, Any]:
        with self.lock:
            self.sequence += 1
            event = {
                "type": event_type,
                "call_id": self.call_id,
                "seq": self.sequence,
                **fields,
            }
            self.events.append(event)
            if self.stream is not None:
                self.stream.write(json.dumps(event, ensure_ascii=False) + "\n")
                self.stream.flush()
            return event

    def progress(self, stage: str, preview: str, task_id: str | None = None) -> None:
        fields: dict[str, Any] = {
            "stage": stage,
            "preview": _one_line(preview)[:160],
        }
        if task_id is not None:
            fields["task_id"] = task_id
        self.emit("progress", **fields)


@dataclass(frozen=True)
class Specialist:
    id: str
    version: str
    description: str
    accepts: tuple[str, ...]
    workspace_effect: str
    launch_path: Path
    snapshot_path: Path
    min_context_window: int
    capabilities: frozenset[str]
    defaults: Mapping[str, Any]
    handoff_format: str


@dataclass(frozen=True)
class Pool:
    id: str
    reasoning_effort: str | None
    capabilities: frozenset[str]
    max_concurrency: int
    request_timeout_seconds: int


@dataclass(frozen=True)
class NativePool(Pool):
    provider: str
    endpoint: str
    model: str
    api_key_env: str | None
    context_window: int


@dataclass(frozen=True)
class CodexPool(Pool):
    model: str | None
    codex_command: str | None
    context_window: int | None


@dataclass(frozen=True)
class TaskSpec:
    index: int
    id: str
    specialist: Specialist
    pool: Pool
    task: str
    context: str | None
    paths: tuple[str, ...]


@dataclass
class TaskOutcome:
    result: dict[str, Any]
    handoff: dict[str, Any] | None


@dataclass(frozen=True)
class WorkerConfig:
    binary: str
    reasoning_effort: str | None
    request_timeout_seconds: int
    worker_timeout_seconds: int

    def common_session_params(
        self, workspace: Path, launch_path: Path, engine: str
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "workspace": str(workspace),
            "launch_path": str(launch_path),
            "engine": engine,
            "timeout_seconds": self.request_timeout_seconds,
        }
        if self.reasoning_effort is not None:
            params["reasoning_effort"] = self.reasoning_effort
        return params

    def session_params(self, workspace: Path, launch_path: Path) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(frozen=True)
class NativeWorkerConfig(WorkerConfig):
    endpoint: str
    model: str
    api_key_env: str | None
    context_window: int
    max_rounds: int
    max_tool_calls: int
    max_tokens: int

    def session_params(self, workspace: Path, launch_path: Path) -> dict[str, Any]:
        params = self.common_session_params(workspace, launch_path, "native")
        params.update(
            {
                "base_url": self.endpoint,
                "model": self.model,
                "context_window": self.context_window,
                "max_rounds": self.max_rounds,
                "max_tool_calls": self.max_tool_calls,
                "max_tokens": self.max_tokens,
            }
        )
        if self.api_key_env is not None:
            params["api_key_env"] = self.api_key_env
        return params


@dataclass(frozen=True)
class CodexWorkerConfig(WorkerConfig):
    model: str | None
    codex_command: str | None

    def session_params(self, workspace: Path, launch_path: Path) -> dict[str, Any]:
        params = self.common_session_params(workspace, launch_path, "codex")
        if self.model is not None:
            params["model"] = self.model
        if self.codex_command is not None:
            params["codex_command"] = self.codex_command
        return params


class AriWorker:
    """One deadline-bounded JSON-RPC conversation with one Agul process."""

    def __init__(
        self,
        config: WorkerConfig,
        workspace: Path,
        on_progress: Callable[[str, str], None] | None = None,
    ) -> None:
        self.config = config
        self.on_progress = on_progress
        self.deadline = monotonic() + config.worker_timeout_seconds
        self.messages: Queue[tuple[str, str]] = Queue()
        self.ledger_entries: list[dict[str, Any]] = []
        self.rounds = 0
        self.tool_calls = 0
        self.forwarded_child_progress = 0
        self.last_child_progress: tuple[str | None, str, str] | None = None
        self.child_progress_limited = False
        self.next_id = 1
        self.stderr_tail = ""
        try:
            self.process = subprocess.Popen(
                [config.binary, "ari", "serve"],
                cwd=workspace,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as error:
            raise WorkerError(
                "start_process", f"could not start Agul: {error}"
            ) from error
        if (
            self.process.stdin is None
            or self.process.stdout is None
            or self.process.stderr is None
        ):
            self.stop()
            raise WorkerError("start_process", "could not open Agul ARI streams")
        self.reader = Thread(target=self._read_stdout, daemon=True)
        self.stderr_reader = Thread(target=self._read_stderr, daemon=True)
        self.reader.start()
        self.stderr_reader.start()

    def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        try:
            for line in self.process.stdout:
                self.messages.put(("line", line))
        except OSError as error:
            self.messages.put(("error", str(error)))
        finally:
            self.messages.put(("eof", ""))

    def _read_stderr(self) -> None:
        assert self.process.stderr is not None
        try:
            while chunk := self.process.stderr.read(4096):
                self.stderr_tail = (self.stderr_tail + chunk)[-STDERR_TAIL_CHARS:]
        except OSError:
            return

    def _remaining(self, stage: str) -> float:
        remaining = self.deadline - monotonic()
        if remaining <= 0:
            raise WorkerError(
                stage,
                f"worker timed out after {self.config.worker_timeout_seconds} seconds",
            )
        return remaining

    def call(self, method: str, params: dict[str, Any], stage: str) -> Any:
        request_id = str(self.next_id)
        self.next_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        try:
            assert self.process.stdin is not None
            self.process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise WorkerError(stage, f"could not write to Agul ARI: {error}") from error

        while True:
            try:
                kind, payload = self.messages.get(timeout=self._remaining(stage))
            except Empty as error:
                raise WorkerError(
                    stage,
                    f"worker timed out after {self.config.worker_timeout_seconds} seconds",
                ) from error
            if kind == "error":
                raise WorkerError(stage, f"could not read Agul ARI: {payload}")
            if kind == "eof":
                detail = self.stderr_tail.strip()
                suffix = f": {detail}" if detail else ""
                raise WorkerError(stage, f"Agul closed ARI before replying{suffix}")
            try:
                message = json.loads(payload)
            except json.JSONDecodeError as error:
                raise WorkerError(
                    stage, f"Agul returned invalid ARI JSON: {error}"
                ) from error
            if message.get("method") == "ari.event":
                self._event(message.get("params"))
                continue
            if message.get("id") != request_id:
                raise WorkerError(
                    stage, f"unexpected ARI response id: {message.get('id')!r}"
                )
            error = message.get("error")
            if isinstance(error, dict):
                code = error.get("code")
                raise WorkerError(
                    stage,
                    str(error.get("message") or "Agul returned an ARI error"),
                    code
                    if isinstance(code, int) and not isinstance(code, bool)
                    else None,
                )
            return message.get("result")

    def _event(self, params: Any) -> None:
        if not isinstance(params, dict):
            return
        if params.get("kind") == "usage" and isinstance(
            params.get("ledger_entry"), dict
        ):
            entry = params["ledger_entry"]
            self.ledger_entries.append(entry)
            if entry.get("purpose") == "chat":
                self.rounds += 1
        if params.get("kind") == "tool" and params.get("phase") == "started":
            self.tool_calls += 1
        progress = _worker_progress(params)
        if progress is not None:
            child_call_id = params.get("call_id")
            self._forward_progress(
                params.get("kind"),
                progress,
                child_call_id if isinstance(child_call_id, str) else None,
            )

    def _forward_progress(
        self,
        kind: Any,
        progress: tuple[str, str],
        child_call_id: str | None,
    ) -> None:
        if self.on_progress is None:
            return
        if kind != "tool_progress":
            self.last_child_progress = None
            self.on_progress(*progress)
            return
        dedupe_key = (child_call_id, *progress)
        if dedupe_key == self.last_child_progress:
            return
        self.last_child_progress = dedupe_key
        if self.forwarded_child_progress < MAX_CHILD_PROGRESS_EVENTS:
            self.forwarded_child_progress += 1
            self.on_progress(*progress)
        elif not self.child_progress_limited:
            self.child_progress_limited = True
            self.on_progress("progress", "… additional child progress omitted")

    def stop(self) -> None:
        process = getattr(self, "process", None)
        if process is None:
            return
        if process.stdin is not None and not process.stdin.closed:
            try:
                process.stdin.close()
            except OSError:
                pass
        try:
            process.wait(timeout=2)
            return
        except subprocess.TimeoutExpired:
            process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _event_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = _one_line(value)
    return text or None


def _worker_progress(params: Mapping[str, Any]) -> tuple[str, str] | None:
    kind = params.get("kind")
    if kind == "tool":
        name = _event_text(params.get("name"))
        phase = params.get("phase")
        if name is None or phase not in {"started", "finished"}:
            return None
        detail = _event_text(params.get("detail"))
        if phase == "started":
            marker = "◆"
        else:
            ok = params.get("ok")
            if not isinstance(ok, bool):
                return None
            marker = "✓" if ok else "!"
        preview = marker if detail is None else f"{marker} {detail}"
        elapsed = params.get("elapsed_ms")
        if (
            phase == "finished"
            and isinstance(elapsed, int)
            and not isinstance(elapsed, bool)
            and elapsed >= 0
        ):
            preview += f" · {elapsed}ms"
        return name[:64], preview
    if kind == "tool_progress":
        stage = _event_text(params.get("stage"))
        preview = _event_text(params.get("preview"))
        if stage is not None and preview is not None:
            return stage[:64], preview
    return None


def _non_empty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PluginError(f"{name} must be a non-empty string")
    return value.strip()


def _optional_string(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _non_empty_string(value, name)


def _optional_member_string(
    value: Mapping[str, Any], key: str, name: str
) -> str | None:
    if key not in value:
        return None
    return _non_empty_string(value[key], name)


def _package_id(value: Any, name: str) -> str:
    identifier = _non_empty_string(value, name)
    if PACKAGE_ID_PATTERN.fullmatch(identifier) is None:
        raise PluginError(f"{name} is invalid")
    return identifier


def _optional_member_package_id(
    value: Mapping[str, Any], key: str, name: str
) -> str | None:
    if key not in value:
        return None
    return _package_id(value[key], name)


def _optional_member_environment_name(
    value: Mapping[str, Any], key: str, name: str
) -> str | None:
    variable = _optional_member_string(value, key, name)
    if (
        variable is not None
        and ENVIRONMENT_NAME_PATTERN.fullmatch(variable) is None
    ):
        raise PluginError(f"{name} is invalid")
    return variable


def _positive_integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise PluginError(f"{name} must be a positive integer")
    return value


def _optional_member_positive_integer(
    value: Mapping[str, Any], key: str, name: str
) -> int | None:
    if key not in value:
        return None
    return _positive_integer(value[key], name)


def _string_list(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise PluginError(f"{name} must be an array")
    result = tuple(
        _non_empty_string(item, f"{name}[{index}]") for index, item in enumerate(value)
    )
    if len(set(result)) != len(result):
        raise PluginError(f"{name} must not contain duplicates")
    return result


def _reject_unknown_fields(
    value: Mapping[str, Any],
    allowed: set[str],
    name: str,
    engine: str | None = None,
) -> None:
    unknown = sorted(set(value) - allowed)
    if not unknown:
        return
    suffix = f" for {engine} engine" if engine is not None else ""
    raise PluginError(f"{name}.{unknown[0]} is not allowed{suffix}")


def _read_object(path: Path, name: str) -> dict[str, Any]:
    if not path.is_file():
        raise PluginError(
            f"prepared {name} registry not found: {path}",
            code="registry_error",
            stage="prepare",
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PluginError(
            f"could not read prepared {name} registry {path}: {error}",
            code="registry_error",
            stage="prepare",
        ) from error
    if not isinstance(value, dict):
        raise PluginError(
            f"prepared {name} registry must contain a JSON object: {path}",
            code="registry_error",
            stage="prepare",
        )
    return value


def _resolved_file(runtime_root: Path, value: Any, name: str) -> Path:
    raw = _non_empty_string(value, name)
    path = Path(raw)
    if not path.is_absolute():
        path = runtime_root / path
    path = path.resolve()
    if not path.is_file():
        raise PluginError(
            f"{name} not found: {path}", code="registry_error", stage="prepare"
        )
    return path


def _specialists(runtime_root: Path) -> dict[str, Specialist]:
    path = runtime_root / "specialists.json"
    document = _read_object(path, "specialists")
    if document.get("format") != SPECIALISTS_FORMAT:
        raise PluginError(
            f"{path} format must be {SPECIALISTS_FORMAT}",
            code="registry_error",
            stage="prepare",
        )
    entries = document.get("specialists")
    if not isinstance(entries, list):
        raise PluginError(
            f"{path} specialists must be an array",
            code="registry_error",
            stage="prepare",
        )
    result: dict[str, Specialist] = {}
    for index, value in enumerate(entries):
        name = f"specialists[{index}]"
        if not isinstance(value, dict):
            raise PluginError(f"{name} must be a JSON object")
        specialist_id = _non_empty_string(value.get("id"), f"{name}.id")
        if specialist_id in result:
            raise PluginError(f"duplicate specialist id: {specialist_id}")
        effect = _non_empty_string(
            value.get("workspace_effect"), f"{name}.workspace_effect"
        )
        if effect not in {"read", "write"}:
            raise PluginError(f"{name}.workspace_effect must be read or write")
        requirements = value.get("requirements")
        defaults = value.get("defaults")
        if not isinstance(requirements, dict):
            raise PluginError(f"{name}.requirements must be a JSON object")
        if not isinstance(defaults, dict):
            raise PluginError(f"{name}.defaults must be a JSON object")
        handoff_format = _non_empty_string(
            value.get("handoff_format"), f"{name}.handoff_format"
        )
        if handoff_format != HANDOFF_FORMAT:
            raise PluginError(f"{name}.handoff_format must be {HANDOFF_FORMAT}")
        result[specialist_id] = Specialist(
            id=specialist_id,
            version=_non_empty_string(value.get("version"), f"{name}.version"),
            description=_non_empty_string(
                value.get("description"), f"{name}.description"
            ),
            accepts=_string_list(value.get("accepts"), f"{name}.accepts"),
            workspace_effect=effect,
            launch_path=_resolved_file(
                runtime_root, value.get("launch_path"), f"{name}.launch_path"
            ),
            snapshot_path=_resolved_file(
                runtime_root, value.get("snapshot_path"), f"{name}.snapshot_path"
            ),
            min_context_window=_positive_integer(
                requirements.get("min_context_window"),
                f"{name}.requirements.min_context_window",
            ),
            capabilities=frozenset(
                _string_list(
                    requirements.get("capabilities"),
                    f"{name}.requirements.capabilities",
                )
            ),
            defaults=defaults,
            handoff_format=handoff_format,
        )
    return result


def _pools(runtime_root: Path) -> tuple[str | None, dict[str, Pool]]:
    path = runtime_root / "pools.json"
    document = _read_object(path, "pools")
    _reject_unknown_fields(document, {"format", "default_pool", "pools"}, "pools")
    if document.get("format") != POOLS_FORMAT:
        raise PluginError(
            f"{path} format must be {POOLS_FORMAT}",
            code="registry_error",
            stage="prepare",
        )
    entries = document.get("pools")
    if not isinstance(entries, list):
        raise PluginError(
            f"{path} pools must be an array",
            code="registry_error",
            stage="prepare",
        )
    result: dict[str, Pool] = {}
    for index, value in enumerate(entries):
        name = f"pools[{index}]"
        if not isinstance(value, dict):
            raise PluginError(f"{name} must be a JSON object")
        engine = _non_empty_string(value.get("engine"), f"{name}.engine")
        engine_fields = POOL_ENGINE_FIELDS.get(engine)
        if engine_fields is None:
            raise PluginError(f"{name}.engine must be native or codex")
        _reject_unknown_fields(
            value, POOL_COMMON_FIELDS | engine_fields, name, engine
        )
        pool_id = _package_id(value.get("id"), f"{name}.id")
        if pool_id in result:
            raise PluginError(f"duplicate pool id: {pool_id}")
        _optional_member_string(value, "description", f"{name}.description")
        if "labels" in value:
            _string_list(value["labels"], f"{name}.labels")
        if "override" in value and not isinstance(value["override"], bool):
            raise PluginError(f"{name}.override must be a boolean")
        common: dict[str, Any] = dict(
            id=pool_id,
            reasoning_effort=_optional_member_string(
                value, "reasoning_effort", f"{name}.reasoning_effort"
            ),
            capabilities=frozenset(
                _string_list(value.get("capabilities"), f"{name}.capabilities")
            ),
            max_concurrency=_positive_integer(
                value.get("max_concurrency"), f"{name}.max_concurrency"
            ),
            request_timeout_seconds=_positive_integer(
                value.get("request_timeout_seconds"),
                f"{name}.request_timeout_seconds",
            ),
        )
        if engine == "native":
            result[pool_id] = NativePool(
                **common,
                provider=_non_empty_string(
                    value.get("provider"), f"{name}.provider"
                ),
                endpoint=_non_empty_string(
                    value.get("endpoint"), f"{name}.endpoint"
                ),
                model=_non_empty_string(value.get("model"), f"{name}.model"),
                api_key_env=_optional_member_environment_name(
                    value, "api_key_env", f"{name}.api_key_env"
                ),
                context_window=_positive_integer(
                    value.get("context_window"), f"{name}.context_window"
                ),
            )
        else:
            result[pool_id] = CodexPool(
                **common,
                model=_optional_member_string(value, "model", f"{name}.model"),
                codex_command=_optional_member_string(
                    value, "codex_command", f"{name}.codex_command"
                ),
                context_window=_optional_member_positive_integer(
                    value, "context_window", f"{name}.context_window"
                ),
            )
    default_pool = _optional_member_package_id(
        document, "default_pool", "default_pool"
    )
    if result and default_pool is None:
        raise PluginError("default_pool is required when pools are configured")
    if default_pool is not None and default_pool not in result:
        raise PluginError(f"default_pool does not exist: {default_pool}")
    return default_pool, result


def _worker_config(
    specialist: Specialist, pool: Pool, environ: Mapping[str, str]
) -> WorkerConfig:
    defaults = specialist.defaults
    allowed = {
        "reasoning_effort",
        "max_rounds",
        "max_tool_calls",
        "max_tokens",
        "timeout_seconds",
    }
    unknown = sorted(set(defaults) - allowed)
    if unknown:
        raise PluginError(
            f"specialist {specialist.id} has unknown default: {unknown[0]}",
            code="registry_error",
            stage="prepare",
        )
    reasoning_effort = _optional_string(
        defaults.get("reasoning_effort"),
        f"specialist {specialist.id} defaults.reasoning_effort",
    )
    max_rounds = _positive_integer(
        defaults.get("max_rounds"),
        f"specialist {specialist.id} defaults.max_rounds",
    )
    max_tool_calls = _positive_integer(
        defaults.get("max_tool_calls"),
        f"specialist {specialist.id} defaults.max_tool_calls",
    )
    max_tokens = _positive_integer(
        defaults.get("max_tokens"),
        f"specialist {specialist.id} defaults.max_tokens",
    )
    common: dict[str, Any] = dict(
        binary=_non_empty_string(
            environ.get("AGUL_SUBAGENT_BINARY", "agul"),
            "AGUL_SUBAGENT_BINARY",
        ),
        reasoning_effort=pool.reasoning_effort or reasoning_effort,
        request_timeout_seconds=pool.request_timeout_seconds,
        worker_timeout_seconds=_positive_integer(
            defaults.get("timeout_seconds"),
            f"specialist {specialist.id} defaults.timeout_seconds",
        ),
    )
    if isinstance(pool, NativePool):
        return NativeWorkerConfig(
            **common,
            endpoint=pool.endpoint,
            model=pool.model,
            api_key_env=pool.api_key_env,
            context_window=pool.context_window,
            max_rounds=max_rounds,
            max_tool_calls=max_tool_calls,
            max_tokens=max_tokens,
        )
    if isinstance(pool, CodexPool):
        return CodexWorkerConfig(
            **common,
            model=pool.model,
            codex_command=pool.codex_command,
        )
    raise PluginError(
        f"pool {pool.id} has an unsupported engine",
        code="registry_error",
        stage="prepare",
    )


def _tasks(
    value: Any,
    specialists: Mapping[str, Specialist],
    default_pool: str | None,
    pools: Mapping[str, Pool],
) -> list[TaskSpec]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_TASKS:
        raise PluginError(f"tasks must contain between 1 and {MAX_TASKS} items")
    result: list[TaskSpec] = []
    used_ids: set[str] = set()
    allowed = {"id", "specialist", "pool", "task", "context", "paths"}
    for index, item in enumerate(value):
        name = f"tasks[{index}]"
        if not isinstance(item, dict):
            raise PluginError(f"{name} must be a JSON object")
        unknown = sorted(set(item) - allowed)
        if unknown:
            raise PluginError(f"unknown {name} field: {unknown[0]}")
        task_id = _optional_string(item.get("id"), f"{name}.id") or f"task-{index + 1}"
        if task_id in used_ids:
            raise PluginError(f"duplicate task id: {task_id}")
        used_ids.add(task_id)
        specialist_id = _non_empty_string(item.get("specialist"), f"{name}.specialist")
        specialist = specialists.get(specialist_id)
        if specialist is None:
            raise PluginError(
                f"unknown specialist: {specialist_id}",
                code="specialist_not_found",
                stage="prepare",
            )
        pool_value = item.get("pool")
        if isinstance(pool_value, str) and not pool_value.strip():
            pool_value = None
        pool_id = _optional_string(pool_value, f"{name}.pool") or default_pool
        if pool_id is None:
            raise PluginError(
                f"no pool configured for {task_id}",
                code="pool_not_found",
                stage="prepare",
            )
        pool = pools.get(pool_id)
        if pool is None:
            raise PluginError(
                f"unknown pool: {pool_id}; pool selects an execution pool, not a "
                f"specialist; omit pool to use default_pool {default_pool}",
                code="pool_not_found",
                stage="prepare",
            )
        missing = sorted(specialist.capabilities - pool.capabilities)
        if missing:
            raise PluginError(
                f"pool {pool.id} lacks capability required by {specialist.id}: {missing[0]}",
                code="pool_incompatible",
                stage="prepare",
            )
        if (
            pool.context_window is not None
            and pool.context_window < specialist.min_context_window
        ):
            raise PluginError(
                f"pool {pool.id} context_window is below "
                f"{specialist.id} minimum {specialist.min_context_window}",
                code="pool_incompatible",
                stage="prepare",
            )
        paths = _string_list(item.get("paths", []), f"{name}.paths")
        result.append(
            TaskSpec(
                index=index,
                id=task_id,
                specialist=specialist,
                pool=pool,
                task=_non_empty_string(item.get("task"), f"{name}.task"),
                context=_optional_string(item.get("context"), f"{name}.context"),
                paths=paths,
            )
        )
    return result


def _request(
    request: Any,
) -> tuple[str, str, Path, Path, Any]:
    if not isinstance(request, dict):
        raise PluginError("request must be a JSON object")
    tool = request.get("tool")
    command = request.get("command")
    if tool != "delegate_tasks" and command != "agent":
        raise PluginError("unknown invocation; expected delegate_tasks or /agent")
    context = request.get("context")
    if not isinstance(context, dict):
        raise PluginError("context must be a JSON object")
    call_id = _non_empty_string(context.get("call_id"), "context.call_id")
    session_id = _non_empty_string(context.get("session_id"), "context.session_id")
    workspace = Path(_non_empty_string(context.get("workspace"), "context.workspace"))
    if not workspace.is_absolute():
        raise PluginError("context.workspace must be an absolute path")
    workspace = workspace.resolve()
    if not workspace.is_dir():
        raise PluginError(f"context.workspace does not exist: {workspace}")
    launch_value = context.get("launch_path")
    if launch_value is None:
        raise PluginError(
            "context.launch_path is required for prepared specialists",
            code="registry_error",
            stage="prepare",
        )
    launch_path = Path(_non_empty_string(launch_value, "context.launch_path"))
    if not launch_path.is_absolute():
        raise PluginError("context.launch_path must be an absolute path")
    launch_path = launch_path.resolve()
    if not launch_path.is_file():
        raise PluginError(
            f"context.launch_path not found: {launch_path}",
            code="registry_error",
            stage="prepare",
        )
    arguments = request.get("arguments")
    if command == "agent":
        return call_id, session_id, workspace, launch_path, _agent_tasks(arguments)
    if not isinstance(arguments, dict):
        raise PluginError("arguments must be a JSON object")
    unknown = sorted(set(arguments) - {"tasks"})
    if unknown:
        raise PluginError(f"unknown argument: {unknown[0]}")
    return call_id, session_id, workspace, launch_path, arguments.get("tasks")


def _agent_tasks(arguments: Any) -> Any:
    text = _non_empty_string(arguments, "/agent arguments")
    if text.lstrip().startswith("{"):
        try:
            value = json.loads(text)
        except json.JSONDecodeError as error:
            raise PluginError(f"invalid /agent JSON: {error}") from error
        if not isinstance(value, dict):
            raise PluginError("/agent JSON must be an object containing tasks")
        unknown = sorted(set(value) - {"tasks"})
        if unknown:
            raise PluginError(f"unknown /agent JSON field: {unknown[0]}")
        return value.get("tasks")
    specialist, separator, task = text.partition(" ")
    if not separator or not task.strip():
        raise PluginError("usage: /agent <specialist> <task>")
    return [{"specialist": specialist, "task": task.strip()}]


def _task_prompt(task: TaskSpec) -> str:
    sections = [task.task]
    if task.context is not None:
        sections.extend(["", "Additional context:", task.context])
    if task.paths:
        sections.extend(["", "Scoped paths:", *[f"- {path}" for path in task.paths]])
    return "\n".join(sections)


def _authoritative_handoff(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WorkerError(
            "handoff", "Agul returned no schema-valid agul/handoff/v1 handoff"
        )
    payload_format = value.get("format")
    if payload_format != HANDOFF_FORMAT:
        raise WorkerError("handoff", f"handoff format must be {HANDOFF_FORMAT}")
    status = value.get("status")
    if status not in {"completed", "blocked", "failed"}:
        raise WorkerError(
            "handoff", "handoff status must be completed, blocked, or failed"
        )
    if not isinstance(value.get("summary"), str):
        raise WorkerError("handoff", "handoff summary must be a string")
    return value


def _integer(value: Any, fallback: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return fallback


def _failed_result(
    task: TaskSpec, error: dict[str, Any], worker: AriWorker | None
) -> TaskOutcome:
    return TaskOutcome(
        result={
            "id": task.id,
            "specialist": task.specialist.id,
            "pool": task.pool.id,
            "workspace_effect": task.specialist.workspace_effect,
            "status": "failed",
            "error": error,
            "rounds": worker.rounds if worker is not None else 0,
            "tool_calls": worker.tool_calls if worker is not None else 0,
            "ledger_entries": worker.ledger_entries if worker is not None else [],
        },
        handoff=None,
    )


def _run_task(
    task: TaskSpec,
    workspace: Path,
    parent_session_id: str,
    delegation_id: str,
    config: WorkerConfig,
    emitter: EventEmitter,
) -> TaskOutcome:
    worker: AriWorker | None = None
    session_id: str | None = None
    emitter.progress("starting", f"Starting {task.specialist.id}", task.id)
    try:
        worker = AriWorker(
            config,
            workspace,
            lambda stage, preview: emitter.progress(stage, preview, task.id),
        )
        worker.call(
            "ari.initialize",
            {
                "client": {
                    "name": "agentkube-coordinator",
                    "version": COORDINATOR_VERSION,
                }
            },
            "initialize",
        )
        session_params = config.session_params(workspace, task.specialist.launch_path)
        session_params.update(
            {
                "parent_session_id": parent_session_id,
                "delegation_id": delegation_id,
                "task_id": task.id,
                "specialist_id": task.specialist.id,
                "pool_id": task.pool.id,
            }
        )
        started = worker.call("ari.start_session", session_params, "start_session")
        if not isinstance(started, dict) or not isinstance(
            started.get("session_id"), str
        ):
            raise WorkerError("start_session", "Agul returned no session_id")
        session_id = started["session_id"]
        emitter.emit(
            "session",
            relation="delegated",
            session_id=session_id,
            delegation_id=delegation_id,
            task_id=task.id,
        )
        sent = worker.call(
            "ari.send",
            {"session_id": session_id, "input": _task_prompt(task)},
            "send",
        )
        if not isinstance(sent, dict) or not isinstance(sent.get("text"), str):
            raise WorkerError("send", "Agul returned no final text")
        handoff = _authoritative_handoff(sent.get("handoff"))
        status = handoff["status"]
        result: dict[str, Any] = {
            "id": task.id,
            "specialist": task.specialist.id,
            "pool": task.pool.id,
            "workspace_effect": task.specialist.workspace_effect,
            "status": status,
            "session_id": session_id,
            "summary": handoff["summary"],
            "rounds": _integer(sent.get("model_rounds"), worker.rounds),
            "tool_calls": _integer(sent.get("tool_calls"), worker.tool_calls),
            "ledger_entries": worker.ledger_entries,
        }
        emitter.progress(status, handoff["summary"], task.id)
        return TaskOutcome(result=result, handoff=handoff)
    except WorkerError as error:
        emitter.progress("failed", str(error), task.id)
        return _failed_result(task, error.value(), worker)
    except Exception as error:  # Preserve sibling results when one worker surprises us.
        emitter.progress("failed", str(error), task.id)
        return _failed_result(task, {"stage": "worker", "message": str(error)}, worker)
    finally:
        if worker is not None:
            if session_id is not None:
                try:
                    worker.call(
                        "ari.close_session",
                        {"session_id": session_id},
                        "close_session",
                    )
                except WorkerError:
                    pass
            worker.stop()


def _run_guarded(
    semaphore: Semaphore,
    task: TaskSpec,
    workspace: Path,
    parent_session_id: str,
    delegation_id: str,
    config: WorkerConfig,
    emitter: EventEmitter,
) -> TaskOutcome:
    with semaphore:
        return _run_task(
            task,
            workspace,
            parent_session_id,
            delegation_id,
            config,
            emitter,
        )


def _non_negative_integer(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _cache_split(entry: Mapping[str, Any]) -> tuple[int, int] | None:
    input_tokens = _non_negative_integer(entry.get("input_tokens"))
    if input_tokens is None:
        return None
    hit = entry.get("cache_hit_input_tokens")
    miss = entry.get("cache_miss_input_tokens")
    if hit is None and miss is None:
        if "all_input_cache_miss" in (entry.get("assumptions") or []):
            return 0, input_tokens
        return None
    if hit is not None and (
        not isinstance(hit, int) or isinstance(hit, bool) or hit < 0
    ):
        return None
    if miss is not None and (
        not isinstance(miss, int) or isinstance(miss, bool) or miss < 0
    ):
        return None
    if hit is None:
        assert isinstance(miss, int)
        hit = input_tokens - miss
    if miss is None:
        assert isinstance(hit, int)
        miss = input_tokens - hit
    if hit < 0 or miss < 0 or hit + miss != input_tokens:
        return None
    return hit, miss


def _usage_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "responses": 0,
        "chat_responses": 0,
        "compaction_responses": 0,
        "responses_with_usage": 0,
        "priced_responses": 0,
        "unpriced_responses": 0,
        "stale_price_responses": 0,
        "assumed_price_responses": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_hit_input_tokens": 0,
        "cache_miss_input_tokens": 0,
        "reasoning_tokens": 0,
        "total_cost": None,
        "total_cost_unavailable": False,
    }
    total_currency: str | None = None
    total_femto_units = 0

    for entry in entries:
        summary["responses"] += 1
        purpose = entry.get("purpose")
        if purpose == "chat":
            summary["chat_responses"] += 1
        elif purpose == "compaction":
            summary["compaction_responses"] += 1

        input_tokens = _non_negative_integer(entry.get("input_tokens"))
        output_tokens = _non_negative_integer(entry.get("output_tokens"))
        if input_tokens is not None and output_tokens is not None:
            summary["responses_with_usage"] += 1
        if input_tokens is not None:
            summary["input_tokens"] += input_tokens
        if output_tokens is not None:
            summary["output_tokens"] += output_tokens
        reasoning_tokens = _non_negative_integer(entry.get("reasoning_tokens"))
        if reasoning_tokens is not None:
            summary["reasoning_tokens"] += reasoning_tokens
        cache = _cache_split(entry)
        if cache is not None:
            summary["cache_hit_input_tokens"] += cache[0]
            summary["cache_miss_input_tokens"] += cache[1]
        if entry.get("stale") is True:
            summary["stale_price_responses"] += 1
        if entry.get("assumptions"):
            summary["assumed_price_responses"] += 1

        cost = entry.get("cost")
        if cost is None:
            summary["unpriced_responses"] += 1
            continue
        summary["priced_responses"] += 1
        if not isinstance(cost, dict):
            summary["total_cost_unavailable"] = True
            continue
        currency = cost.get("currency")
        femto_units = cost.get("femto_units")
        try:
            femto_units = int(femto_units)
        except (TypeError, ValueError):
            summary["total_cost_unavailable"] = True
            continue
        if not isinstance(currency, str) or not currency or femto_units < 0:
            summary["total_cost_unavailable"] = True
            continue
        if total_currency is None:
            total_currency = currency
        elif total_currency != currency:
            summary["total_cost_unavailable"] = True
            continue
        total_femto_units += femto_units

    if total_currency is not None and not summary["total_cost_unavailable"]:
        summary["total_cost"] = {
            "currency": total_currency,
            "femto_units": str(total_femto_units),
        }
    return summary


def handle(
    request: Any,
    environ: Mapping[str, str] | None = None,
    emitter: EventEmitter | None = None,
) -> dict[str, Any]:
    environ = os.environ if environ is None else environ
    call_id, parent_session_id, workspace, launch_path, task_values = _request(request)
    emitter = emitter or EventEmitter(call_id)
    runtime_root = launch_path.parent
    specialists = _specialists(runtime_root)
    default_pool, pools = _pools(runtime_root)
    tasks = _tasks(task_values, specialists, default_pool, pools)
    delegation_id = f"delegation-{uuid4()}"
    emitter.progress("prepared", f"Prepared {len(tasks)} delegated task(s)")

    configs = {
        task.id: _worker_config(task.specialist, task.pool, environ) for task in tasks
    }
    semaphores = {pool.id: Semaphore(pool.max_concurrency) for pool in pools.values()}
    outcomes: list[TaskOutcome | None] = [None] * len(tasks)
    read_tasks = [task for task in tasks if task.specialist.workspace_effect == "read"]
    write_tasks = [
        task for task in tasks if task.specialist.workspace_effect == "write"
    ]

    if read_tasks:
        emitter.progress("read_phase", f"Running {len(read_tasks)} read task(s)")
        with ThreadPoolExecutor(max_workers=len(read_tasks)) as executor:
            futures = {
                executor.submit(
                    _run_guarded,
                    semaphores[task.pool.id],
                    task,
                    workspace,
                    parent_session_id,
                    delegation_id,
                    configs[task.id],
                    emitter,
                ): task
                for task in read_tasks
            }
            for future in as_completed(futures):
                task = futures[future]
                try:
                    outcomes[task.index] = future.result()
                except Exception as error:
                    outcomes[task.index] = _failed_result(
                        task, {"stage": "worker", "message": str(error)}, None
                    )

    if write_tasks:
        emitter.progress(
            "write_phase", f"Running {len(write_tasks)} write task(s) serially"
        )
        for task in write_tasks:
            outcomes[task.index] = _run_guarded(
                semaphores[task.pool.id],
                task,
                workspace,
                parent_session_id,
                delegation_id,
                configs[task.id],
                emitter,
            )

    ordered = [outcome for outcome in outcomes if outcome is not None]
    results = [outcome.result for outcome in ordered]
    handoff = {
        result["id"]: outcome.handoff
        for result, outcome in zip(results, ordered, strict=True)
        if outcome.handoff is not None
    }
    entries = [
        entry
        for result in results
        for entry in result["ledger_entries"]
        if isinstance(entry, dict)
    ]
    completed = sum(result["status"] == "completed" for result in results)
    if completed == len(results):
        status = "completed"
    elif completed == 0 and all(result["status"] == "failed" for result in results):
        status = "failed"
    else:
        status = "partial"
    return {
        "delegation_id": delegation_id,
        "status": status,
        "results": results,
        "handoff": handoff,
        "usage": _usage_summary(entries),
    }


def _call_id_from(value: Any) -> str:
    if isinstance(value, dict):
        context = value.get("context")
        if isinstance(context, dict):
            call_id = context.get("call_id")
            if isinstance(call_id, str) and call_id.strip():
                return call_id.strip()
    return "unknown"


def main() -> int:
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    line = sys.stdin.readline()
    try:
        request = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        emitter = EventEmitter("unknown", sys.stdout)
        emitter.emit(
            "result",
            ok=False,
            error=PluginError(f"invalid request JSON: {error}").value(),
        )
        return 0

    emitter = EventEmitter(_call_id_from(request), sys.stdout)
    try:
        content = handle(request, emitter=emitter)
    except PluginError as error:
        emitter.emit("result", ok=False, error=error.value())
        return 0
    except Exception as error:
        emitter.emit(
            "result",
            ok=False,
            error=PluginError(
                str(error), code="internal_error", stage="coordinator"
            ).value(),
        )
        return 0
    emitter.emit("result", ok=True, content=content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
