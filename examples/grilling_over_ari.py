from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import TextIO

from examples.ari import AriClient


def grilling_prompt(prompt: str) -> str:
    return f"@skill:grilling {prompt}"


class EventPrinter:
    """Keep streamed text readable without turning every delta into a new line."""

    def __init__(self, output: TextIO) -> None:
        self.output = output
        self.streaming_kind: str | None = None

    def finish_stream(self) -> None:
        if self.streaming_kind is not None:
            self.output.write("\n")
            self.output.flush()
            self.streaming_kind = None

    def __call__(self, event: dict[str, object]) -> None:
        kind = str(event.get("kind", "event"))
        text = event.get("text")
        if kind in {"reasoning", "text"} and isinstance(text, str):
            if self.streaming_kind != kind:
                self.finish_stream()
                self.output.write(f"{kind}: ")
                self.streaming_kind = kind
            self.output.write(text)
            self.output.flush()
            return

        self.finish_stream()
        if kind == "tool":
            name = event.get("name", "tool")
            self.output.write(f"tool: {name}\n")
        elif kind == "usage" and isinstance(event.get("usage"), dict):
            usage = event["usage"]
            self.output.write(
                f"usage: ↑{usage.get('input_tokens', 0)} ↓{usage.get('output_tokens', 0)}\n"
            )
        else:
            value = text or event.get("name")
            if value is not None:
                self.output.write(f"{kind}: {value}\n")
        self.output.flush()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Send a prompt to an Agul agent prepared with AgentKube's grilling Skill."
    )
    parser.add_argument("workspace", type=Path)
    parser.add_argument("prompt")
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    launch = workspace / ".agents" / "runtime" / "launch.json"

    show = EventPrinter(sys.stdout)

    with AriClient(show) as agul:
        agul.initialize()
        started = agul.start_session(
            workspace=str(workspace),
            launch_path=str(launch),
            model=args.model,
            base_url=args.base_url,
        )
        session_id = started["session_id"]
        result = agul.send(session_id, grilling_prompt(args.prompt))
        agul.close_session(session_id)

    show.finish_stream()
    report = {key: value for key, value in result.items() if key != "text"}
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
