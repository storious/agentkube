from __future__ import annotations

from contextlib import AbstractContextManager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import subprocess
from threading import Thread
from typing import Any
from urllib.parse import parse_qs, urlsplit
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "web-search"
SCRIPT = PLUGIN / "web_search.py"
MANIFEST = PLUGIN / "plugin.json"
RESULT_FORMAT = "agul/web-search-result/v1"


def _load_plugin() -> Any:
    spec = importlib.util.spec_from_file_location("agentkube_web_search", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load web-search Plugin")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _WebHandler(BaseHTTPRequestHandler):
    def _record(self, body: bytes = b"") -> None:
        self.server.requests.append(  # type: ignore[attr-defined]
            {
                "method": self.command,
                "path": self.path,
                "headers": dict(self.headers.items()),
                "body": body,
            }
        )

    def _send(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _search_response(self) -> None:
        host, port = self.server.server_address
        page_url = f"http://{host}:{port}/page"
        payload = {
            "results": [
                {
                    "title": "Agul <b>runtime</b>",
                    "url": page_url,
                    "content": "A small &amp; direct agent runtime.",
                },
                {
                    "title": "ARI 协作",
                    "url": f"http://{host}:{port}/plain",
                    "content": "运行时协作 🧭",
                },
                {
                    "title": "Ignored",
                    "url": f"http://{host}:{port}/ignored",
                    "content": "Past the requested limit.",
                },
            ]
        }
        self._send(json.dumps(payload).encode("utf-8"), "application/json")

    def do_GET(self) -> None:  # noqa: N802
        self._record()
        parsed = urlsplit(self.path)
        if parsed.path == "/search":
            if parse_qs(parsed.query).get("q") == ["disconnect"]:
                self.connection.close()
                return
            self._search_response()
            return
        if parsed.path == "/page":
            body = """<!doctype html>
<html><head><title>Agul &amp; ARI</title>
<style>.hidden { display:none }</style><script>secret-script-text</script></head>
<body><main><h1>Agul runtime</h1><p>ARI lets the runtime coordinate agents.</p>
<p>Use the runtime for direct work.</p><p>中文协作也可以。</p></main></body></html>"""
            self._send(body.encode("utf-8"), "text/html; charset=utf-8")
            return
        if parsed.path == "/plain":
            self._send("plain runtime page".encode(), "text/plain; charset=utf-8")
            return
        if parsed.path == "/rate-limited":
            self.send_error(429)
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self._record(self.rfile.read(length))
        self._search_response()

    def log_message(self, format: str, *args: object) -> None:
        return


class _LocalWeb(AbstractContextManager["_LocalWeb"]):
    def __init__(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _WebHandler)
        self.server.requests = []  # type: ignore[attr-defined]
        self.thread = Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    @property
    def requests(self) -> list[dict[str, Any]]:
        return self.server.requests  # type: ignore[attr-defined,no-any-return]

    def __enter__(self) -> "_LocalWeb":
        self.thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def _invoke_plugin(
    request: dict[str, Any], **settings: str
) -> subprocess.CompletedProcess[str]:
    environ = os.environ.copy()
    environ.pop("SEARXNG_URL", None)
    environ.pop("TAVILY_API_KEY", None)
    environ.pop("PYTHONIOENCODING", None)
    environ.pop("PYTHONUTF8", None)
    environ.update(settings)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    request = {
        **request,
        "context": request.get(
            "context",
            {
                "call_id": "web-call-1",
                "session_id": "session-1",
                "workspace": str(ROOT),
                "launch_path": None,
            },
        ),
    }
    return subprocess.run(
        manifest["command"],
        cwd=PLUGIN,
        input=json.dumps(request) + "\n",
        capture_output=True,
        check=False,
        encoding="utf-8",
        env=environ,
        timeout=5,
    )


def _events(request: dict[str, Any], **settings: str) -> list[dict[str, Any]]:
    result = _invoke_plugin(request, **settings)
    result.check_returncode()
    assert result.stderr == ""
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    assert events[-1]["type"] == "result"
    return events


def _payload(events: list[dict[str, Any]]) -> dict[str, Any]:
    result = events[-1]
    assert result["ok"]
    payload = json.loads(result["content"])
    assert payload["format"] == RESULT_FORMAT
    return payload


class WebSearchPluginTests(unittest.TestCase):
    def test_manifest_declares_protocol_and_both_tool_schemas(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

        self.assertEqual(
            set(manifest), {"format", "name", "version", "command", "tools"}
        )
        self.assertEqual(manifest["format"], "agul/plugin/v2")
        self.assertEqual(manifest["name"], "web-search")
        self.assertEqual(manifest["version"], "0.3.0")
        self.assertEqual(manifest["command"], ["python", "web_search.py"])
        self.assertEqual(
            [tool["name"] for tool in manifest["tools"]],
            ["web_search", "web_open"],
        )
        search_parameters = manifest["tools"][0]["parameters"]
        self.assertEqual(search_parameters["required"], ["query"])
        self.assertEqual(search_parameters["properties"]["query"]["maxLength"], 399)
        self.assertEqual(
            search_parameters["properties"]["max_results"]["maximum"], 10
        )
        open_parameters = manifest["tools"][1]["parameters"]
        self.assertEqual(open_parameters["required"], ["url"])
        self.assertEqual(open_parameters["properties"]["url"]["maxLength"], 2048)
        self.assertEqual(open_parameters["properties"]["find"]["maxLength"], 200)

    def test_searxng_search_is_structured_and_provider_takes_precedence(self) -> None:
        with _LocalWeb() as web:
            events = _events(
                {
                    "tool": "web_search",
                    "arguments": {"query": "Agul 中文 🔎", "max_results": 2},
                },
                SEARXNG_URL=web.url,
                TAVILY_API_KEY="must-not-be-used",
            )

        self.assertEqual([event.get("stage") for event in events[:-1]], ["search"])
        payload = _payload(events)
        self.assertEqual(payload["stage"], "search")
        self.assertEqual(payload["provider"], "searxng")
        self.assertEqual(payload["query"], "Agul 中文 🔎")
        self.assertEqual(len(payload["results"]), 2)
        self.assertEqual(payload["results"][0]["title"], "Agul runtime")
        self.assertEqual(
            payload["results"][0]["snippet"], "A small & direct agent runtime."
        )
        self.assertEqual(payload["results"][1]["title"], "ARI 协作")
        self.assertEqual(len(web.requests), 1)
        request = web.requests[0]
        self.assertEqual(request["method"], "GET")
        parsed = urlsplit(request["path"])
        self.assertEqual(parsed.path, "/search")
        self.assertEqual(
            parse_qs(parsed.query), {"q": ["Agul 中文 🔎"], "format": ["json"]}
        )

    def test_local_search_open_and_find_complete_the_source_chain(self) -> None:
        with _LocalWeb() as web:
            search = _payload(
                _events(
                    {
                        "tool": "web_search",
                        "arguments": {"query": "Agul", "max_results": 1},
                    },
                    SEARXNG_URL=web.url,
                )
            )
            page_url = search["results"][0]["url"]
            open_events = _events(
                {"tool": "web_open", "arguments": {"url": page_url}}
            )
            find_events = _events(
                {
                    "tool": "web_open",
                    "arguments": {"url": page_url, "find": "runtime"},
                }
            )

        self.assertEqual(
            [event.get("stage") for event in open_events[:-1]], ["open_page"]
        )
        opened = _payload(open_events)
        self.assertEqual(opened["stage"], "open_page")
        self.assertEqual(opened["page"]["title"], "Agul & ARI")
        self.assertEqual(opened["page"]["content_type"], "text/html")
        self.assertIn("ARI lets the runtime coordinate agents.", opened["page"]["text"])
        self.assertIn("中文协作也可以。", opened["page"]["text"])
        self.assertNotIn("secret-script-text", opened["page"]["text"])

        self.assertEqual(
            [event.get("stage") for event in find_events[:-1]],
            ["open_page", "find_in_page"],
        )
        found = _payload(find_events)
        self.assertEqual(found["stage"], "find_in_page")
        self.assertEqual(found["query"], "runtime")
        self.assertEqual(found["match_count"], 3)
        self.assertTrue(found["matches"])
        self.assertNotIn("text", found["page"])
        self.assertTrue(
            all("runtime" in match["excerpt"].lower() for match in found["matches"])
        )

    def test_tavily_uses_official_request_shape(self) -> None:
        plugin = _load_plugin()
        with (
            _LocalWeb() as web,
            patch.object(plugin, "TAVILY_SEARCH_URL", web.url + "/search"),
        ):
            response = plugin.handle(
                {"tool": "web_search", "arguments": {"query": "ARI"}},
                {"TAVILY_API_KEY": "tvly-test"},
            )

        payload = json.loads(response["content"])
        self.assertEqual(payload["format"], RESULT_FORMAT)
        self.assertEqual(payload["provider"], "tavily")
        self.assertEqual(len(web.requests), 1)
        request = web.requests[0]
        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["headers"]["Authorization"], "Bearer tvly-test")
        body = json.loads(request["body"])
        self.assertEqual(
            body,
            {"query": "ARI", "max_results": 5, "search_depth": "basic"},
        )

    def test_missing_search_configuration_is_a_recoverable_tool_failure(self) -> None:
        events = _events(
            {"tool": "web_search", "arguments": {"query": "Agul"}}
        )

        self.assertEqual(events[0]["stage"], "search")
        result = events[-1]
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "configuration_error")
        self.assertEqual(result["error"]["stage"], "search")
        self.assertIn("set SEARXNG_URL or TAVILY_API_KEY", result["error"]["message"])

    def test_query_length_is_checked_before_search(self) -> None:
        events = _events(
            {"tool": "web_search", "arguments": {"query": "x" * 400}}
        )

        self.assertEqual(len(events), 1)
        self.assertFalse(events[-1]["ok"])
        self.assertEqual(
            events[-1]["error"]["message"],
            "query must be at most 399 characters",
        )
        self.assertEqual(events[-1]["error"]["code"], "invalid_request")

    def test_provider_disconnect_is_a_short_tool_failure(self) -> None:
        with _LocalWeb() as web:
            events = _events(
                {"tool": "web_search", "arguments": {"query": "disconnect"}},
                SEARXNG_URL=web.url,
            )

        result = events[-1]
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "provider_error")
        self.assertTrue(result["error"]["retryable"])
        self.assertIn("search provider connection failed", result["error"]["message"])

    def test_web_open_rejects_non_http_urls_before_progress(self) -> None:
        events = _events(
            {"tool": "web_open", "arguments": {"url": "file:///tmp/private"}}
        )

        self.assertEqual(len(events), 1)
        self.assertFalse(events[0]["ok"])
        self.assertEqual(
            events[0]["error"]["message"], "url must be an http:// or https:// URL"
        )

    def test_rate_limited_page_is_retryable(self) -> None:
        with _LocalWeb() as web:
            events = _events(
                {
                    "tool": "web_open",
                    "arguments": {"url": web.url + "/rate-limited"},
                }
            )

        self.assertEqual(events[0]["stage"], "open_page")
        result = events[-1]
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "page_error")
        self.assertEqual(result["error"]["stage"], "open_page")
        self.assertTrue(result["error"]["retryable"])


if __name__ == "__main__":
    unittest.main()
