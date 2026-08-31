from __future__ import annotations

from io import StringIO
import json
import unittest

from examples.ari import AriConnection, AriError
from examples.grilling_over_ari import EventPrinter, grilling_prompt


def line(value: object) -> str:
    return json.dumps(value) + "\n"


class AriExampleTests(unittest.TestCase):
    def test_event_printer_keeps_text_deltas_inline_and_usage_compact(self) -> None:
        output = StringIO()
        printer = EventPrinter(output)

        printer({"kind": "reasoning", "text": "先想"})
        printer({"kind": "reasoning", "text": "一下❓"})
        printer({"kind": "tool", "name": "read"})
        printer({"kind": "text", "text": "答案"})
        printer(
            {
                "kind": "usage",
                "usage": {"input_tokens": 20, "output_tokens": 8, "ledger": [1, 2]},
            }
        )

        self.assertEqual(
            output.getvalue(),
            "reasoning: 先想一下❓\ntool: read\ntext: 答案\nusage: ↑20 ↓8\n",
        )
        self.assertNotIn("ledger", output.getvalue())

    def test_agentkube_extension_drives_a_complete_agul_session(self) -> None:
        responses = StringIO(
            "".join(
                [
                    line({"jsonrpc": "2.0", "id": "1", "result": {"ari": "0.2"}}),
                    line(
                        {
                            "jsonrpc": "2.0",
                            "id": "2",
                            "result": {"methods": ["ari.start_session", "ari.send"]},
                        }
                    ),
                    line(
                        {
                            "jsonrpc": "2.0",
                            "id": "3",
                            "result": {"session_id": "session-1"},
                        }
                    ),
                    line(
                        {
                            "jsonrpc": "2.0",
                            "method": "ari.event",
                            "params": {
                                "session_id": "session-1",
                                "kind": "reasoning",
                                "text": "Inspect the plan",
                            },
                        }
                    ),
                    line(
                        {
                            "jsonrpc": "2.0",
                            "method": "ari.event",
                            "params": {
                                "session_id": "session-1",
                                "kind": "text",
                                "text": "Q1: Who is the first user?",
                            },
                        }
                    ),
                    line(
                        {
                            "jsonrpc": "2.0",
                            "method": "ari.event",
                            "params": {
                                "session_id": "session-1",
                                "kind": "tool",
                                "name": "read",
                            },
                        }
                    ),
                    line(
                        {
                            "jsonrpc": "2.0",
                            "method": "ari.event",
                            "params": {
                                "session_id": "session-1",
                                "kind": "usage",
                                "usage": {"input_tokens": 20, "output_tokens": 8},
                            },
                        }
                    ),
                    line(
                        {
                            "jsonrpc": "2.0",
                            "id": "4",
                            "result": {
                                "session_id": "session-1",
                                "text": "Q1: Who is the first user?",
                            },
                        }
                    ),
                    line(
                        {
                            "jsonrpc": "2.0",
                            "id": "5",
                            "result": {"session_id": "session-1", "closed": True},
                        }
                    ),
                ]
            )
        )
        requests = StringIO()
        events: list[dict[str, object]] = []
        agul = AriConnection(responses, requests, events.append)

        self.assertEqual(agul.initialize()["ari"], "0.2")
        self.assertIn("ari.send", agul.capabilities()["methods"])
        started = agul.start_session(
            workspace="grilling-demo",
            launch_path="grilling-demo/.agents/runtime/launch.json",
            context_window=32_768,
            timeout_seconds=600,
            max_tokens=4_096,
            max_rounds=4,
            max_tool_calls=8,
        )
        result = agul.send(started["session_id"], grilling_prompt("Grill my release plan"))
        agul.close_session(started["session_id"])

        sent = [json.loads(value) for value in requests.getvalue().splitlines()]
        self.assertEqual(
            [request["method"] for request in sent],
            [
                "ari.initialize",
                "ari.capabilities",
                "ari.start_session",
                "ari.send",
                "ari.close_session",
            ],
        )
        self.assertEqual(sent[2]["params"]["launch_path"], "grilling-demo/.agents/runtime/launch.json")
        self.assertEqual(
            {
                key: sent[2]["params"][key]
                for key in (
                    "context_window",
                    "timeout_seconds",
                    "max_tokens",
                    "max_rounds",
                    "max_tool_calls",
                )
            },
            {
                "context_window": 32_768,
                "timeout_seconds": 600,
                "max_tokens": 4_096,
                "max_rounds": 4,
                "max_tool_calls": 8,
            },
        )
        self.assertEqual(sent[3]["params"]["input"], "@skill:grilling Grill my release plan")
        self.assertEqual(result["text"], "Q1: Who is the first user?")
        self.assertEqual(
            [event["kind"] for event in events],
            ["reasoning", "text", "tool", "usage"],
        )

    def test_structured_error_is_available_to_the_caller(self) -> None:
        reader = StringIO(
            line(
                {
                    "jsonrpc": "2.0",
                    "id": "1",
                    "error": {"code": -32000, "message": "model unavailable"},
                }
            )
        )
        connection = AriConnection(reader, StringIO())

        with self.assertRaises(AriError) as raised:
            connection.capabilities()

        self.assertEqual(raised.exception.error["code"], -32000)


if __name__ == "__main__":
    unittest.main()
