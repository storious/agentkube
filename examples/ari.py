from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Callable, TextIO


EventHandler = Callable[[dict[str, Any]], None]


class AriError(RuntimeError):
    def __init__(self, error: dict[str, Any]) -> None:
        self.error = error
        super().__init__(error.get("message", "Agul returned an ARI error"))


class AriConnection:
    """Synchronous JSON-RPC connection to one Agul process."""

    def __init__(
        self,
        reader: TextIO,
        writer: TextIO,
        on_event: EventHandler | None = None,
    ) -> None:
        self.reader = reader
        self.writer = writer
        self.on_event = on_event or (lambda event: None)
        self.next_id = 1

    def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        request_id = str(self.next_id)
        self.next_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }
        self.writer.write(json.dumps(request, ensure_ascii=False) + "\n")
        self.writer.flush()

        while line := self.reader.readline():
            message = json.loads(line)
            if message.get("method") == "ari.event":
                self.on_event(message.get("params", {}))
                continue
            if message.get("id") != request_id:
                raise RuntimeError(f"unexpected ARI response id: {message.get('id')!r}")
            if "error" in message:
                raise AriError(message["error"])
            return message.get("result")
        raise RuntimeError("Agul closed ARI before replying")

    def initialize(self) -> Any:
        return self.call(
            "ari.initialize",
            {"client": {"name": "agentkube", "version": "0.1.0"}},
        )

    def capabilities(self) -> Any:
        return self.call("ari.capabilities")

    def start_session(
        self,
        *,
        workspace: str | None = None,
        launch_path: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        api_key_env: str | None = None,
        reasoning_effort: str | None = None,
        price_card: str | None = None,
        context_window: int | None = None,
        timeout_seconds: int | None = None,
        max_tokens: int | None = None,
        max_rounds: int | None = None,
        max_tool_calls: int | None = None,
    ) -> Any:
        values = {
            "workspace": workspace,
            "launch_path": launch_path,
            "model": model,
            "base_url": base_url,
            "api_key_env": api_key_env,
            "reasoning_effort": reasoning_effort,
            "price_card": price_card,
            "context_window": context_window,
            "timeout_seconds": timeout_seconds,
            "max_tokens": max_tokens,
            "max_rounds": max_rounds,
            "max_tool_calls": max_tool_calls,
        }
        return self.call(
            "ari.start_session",
            {key: value for key, value in values.items() if value is not None},
        )

    def send(self, session_id: str, text: str) -> Any:
        return self.call("ari.send", {"session_id": session_id, "input": text})

    def compact(self, session_id: str) -> Any:
        return self.call("ari.compact", {"session_id": session_id})

    def close_session(self, session_id: str) -> Any:
        return self.call("ari.close_session", {"session_id": session_id})


class AriClient:
    """Start Agul and expose its ARI connection."""

    def __init__(self, on_event: EventHandler | None = None) -> None:
        executable = os.environ.get("AGUL", "agul")
        self.process = subprocess.Popen(
            [executable, "ari", "serve"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        if self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("could not open Agul ARI streams")
        self.connection = AriConnection(
            self.process.stdout,
            self.process.stdin,
            on_event,
        )

    def close(self) -> None:
        if self.process.stdin:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=5)

    def __enter__(self) -> AriConnection:
        return self.connection

    def __exit__(self, *_: object) -> None:
        self.close()
