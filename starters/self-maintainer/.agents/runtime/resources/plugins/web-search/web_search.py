#!/usr/bin/env python3
"""Agul Web Search Plugin using only the Python standard library."""

from __future__ import annotations

from collections.abc import Callable
from http.client import HTTPException
from html.parser import HTMLParser
import json
import os
import re
import sys
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


TAVILY_SEARCH_URL = "https://api.tavily.com/search"
RESULT_FORMAT = "agul/web-search-result/v1"
PLUGIN_VERSION = "0.3.0"
DEFAULT_MAX_RESULTS = 5
MAX_RESULTS = 10
MAX_QUERY_LENGTH = 399
MAX_URL_LENGTH = 2048
MAX_FIND_LENGTH = 200
MAX_PAGE_BYTES = 2_000_000
MAX_PAGE_TEXT_CHARS = 12_000
MAX_FIND_MATCHES = 8
FIND_EXCERPT_CHARS = 320
HTTP_TIMEOUT_SECONDS = 20
USER_AGENT = f"AgentKube-WebSearch/{PLUGIN_VERSION}"

Progress = Callable[[str, str], None]


class PluginError(Exception):
    """A readable tool failure that should not produce a traceback."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "invalid_request",
        retryable: bool = False,
        stage: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.stage = stage

    def value(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "code": self.code,
            "message": str(self),
            "retryable": self.retryable,
        }
        if self.stage is not None:
            value["stage"] = self.stage
        return value


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


class _PageExtractor(HTMLParser):
    _BLOCKS = {
        "article",
        "aside",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }
    _IGNORED = {"script", "style", "noscript", "svg", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self._ignored_depth = 0
        self._in_title = False

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        del attrs
        tag = tag.lower()
        if tag in self._IGNORED:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if tag == "title":
            self._in_title = True
            return
        if tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._ignored_depth:
            if tag in self._IGNORED:
                self._ignored_depth -= 1
            return
        if tag == "title":
            self._in_title = False
            return
        if tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
            return
        self.parts.append(data)


def _plain_text(value: Any, *, limit: int) -> str:
    parser = _TextExtractor()
    parser.feed(str(value or ""))
    text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _page_text(parts: list[str]) -> str:
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in parts]
    return "\n".join(line for line in lines if line)


def _read_json(response: Any) -> Mapping[str, Any]:
    try:
        payload = json.load(response)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PluginError(
            "search provider returned invalid JSON",
            code="provider_error",
            retryable=True,
            stage="search",
        ) from error
    if not isinstance(payload, dict):
        raise PluginError(
            "search provider returned an unexpected response",
            code="provider_error",
            retryable=True,
            stage="search",
        )
    return payload


def _retryable_http_status(status: int) -> bool:
    return status in {408, 425, 429} or status >= 500


def _open_json(request: Request) -> Mapping[str, Any]:
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return _read_json(response)
    except HTTPError as error:
        raise PluginError(
            f"search provider returned HTTP {error.code}",
            code="provider_error",
            retryable=_retryable_http_status(error.code),
            stage="search",
        ) from error
    except URLError as error:
        reason = getattr(error, "reason", error)
        raise PluginError(
            f"could not reach search provider: {reason}",
            code="provider_error",
            retryable=True,
            stage="search",
        ) from error
    except TimeoutError as error:
        raise PluginError(
            "search provider timed out",
            code="provider_error",
            retryable=True,
            stage="search",
        ) from error
    except (HTTPException, OSError) as error:
        raise PluginError(
            f"search provider connection failed: {error}",
            code="provider_error",
            retryable=True,
            stage="search",
        ) from error


def _searxng_endpoint(base_url: str) -> str:
    base_url = base_url.strip().rstrip("/")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PluginError(
            "SEARXNG_URL must be an http:// or https:// URL",
            code="configuration_error",
            stage="search",
        )
    if parsed.query or parsed.fragment:
        raise PluginError(
            "SEARXNG_URL must not include a query or fragment",
            code="configuration_error",
            stage="search",
        )
    path = parsed.path.rstrip("/")
    if not path.endswith("/search"):
        path += "/search"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _search_searxng(base_url: str, query: str, max_results: int) -> list[Any]:
    endpoint = _searxng_endpoint(base_url)
    url = endpoint + "?" + urlencode({"q": query, "format": "json"})
    request = Request(
        url,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    payload = _open_json(request)
    results = payload.get("results", [])
    if not isinstance(results, list):
        raise PluginError(
            "SearXNG returned an unexpected results field",
            code="provider_error",
            retryable=True,
            stage="search",
        )
    return results[:max_results]


def _search_tavily(
    api_key: str,
    query: str,
    max_results: int,
    *,
    endpoint: str | None = None,
) -> list[Any]:
    endpoint = endpoint or TAVILY_SEARCH_URL
    body = json.dumps(
        {
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
        }
    ).encode("utf-8")
    request = Request(
        endpoint,
        data=body,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    payload = _open_json(request)
    results = payload.get("results", [])
    if not isinstance(results, list):
        raise PluginError(
            "Tavily returned an unexpected results field",
            code="provider_error",
            retryable=True,
            stage="search",
        )
    return results[:max_results]


def _normalized_results(results: list[Any]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        title = _plain_text(result.get("title"), limit=160) or "Untitled result"
        url = _plain_text(result.get("url"), limit=MAX_URL_LENGTH)
        if not url:
            continue
        normalized.append(
            {
                "title": title,
                "url": url,
                "snippet": _plain_text(result.get("content"), limit=360),
            }
        )
    return normalized


def _validate_page_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PluginError("url must be an http:// or https:// URL")
    return url


def _open_page(url: str) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "text/html, text/plain;q=0.9, application/xhtml+xml;q=0.8",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            body = response.read(MAX_PAGE_BYTES + 1)
            content_type = response.headers.get_content_type().lower()
            charset = response.headers.get_content_charset() or "utf-8"
            final_url = response.geturl()
    except HTTPError as error:
        raise PluginError(
            f"page returned HTTP {error.code}",
            code="page_error",
            retryable=_retryable_http_status(error.code),
            stage="open_page",
        ) from error
    except URLError as error:
        reason = getattr(error, "reason", error)
        raise PluginError(
            f"could not open page: {reason}",
            code="page_error",
            retryable=True,
            stage="open_page",
        ) from error
    except TimeoutError as error:
        raise PluginError(
            "page request timed out",
            code="page_error",
            retryable=True,
            stage="open_page",
        ) from error
    except (HTTPException, OSError) as error:
        raise PluginError(
            f"page connection failed: {error}",
            code="page_error",
            retryable=True,
            stage="open_page",
        ) from error

    if len(body) > MAX_PAGE_BYTES:
        raise PluginError(
            "page is larger than the supported 2 MB response limit",
            code="page_too_large",
            stage="open_page",
        )
    allowed_application_types = {
        "application/json",
        "application/xhtml+xml",
        "application/xml",
    }
    if (
        not content_type.startswith("text/")
        and content_type not in allowed_application_types
    ):
        raise PluginError(
            f"page content type {content_type} is not readable text",
            code="unsupported_content",
            stage="open_page",
        )
    try:
        decoded = body.decode(charset, errors="replace")
    except LookupError:
        decoded = body.decode("utf-8", errors="replace")

    title = ""
    if content_type in {"text/html", "application/xhtml+xml"}:
        parser = _PageExtractor()
        parser.feed(decoded)
        text = _page_text(parser.parts)
        title = re.sub(r"\s+", " ", " ".join(parser.title_parts)).strip()
    else:
        text = decoded.replace("\r\n", "\n").replace("\r", "\n").strip()
    truncated = len(text) > MAX_PAGE_TEXT_CHARS
    if truncated:
        text = text[:MAX_PAGE_TEXT_CHARS].rstrip() + "…"
    return {
        "url": final_url,
        "title": title,
        "content_type": content_type,
        "text": text,
        "truncated": truncated,
    }


def _find_matches(text: str, query: str) -> tuple[int, list[dict[str, Any]]]:
    occurrences = list(re.finditer(re.escape(query), text, re.IGNORECASE))
    matches: list[dict[str, Any]] = []
    previous_end = -1
    for occurrence in occurrences:
        if len(matches) >= MAX_FIND_MATCHES:
            break
        offset = occurrence.start()
        excerpt_start = max(0, offset - FIND_EXCERPT_CHARS // 2)
        excerpt_end = min(len(text), offset + len(query) + FIND_EXCERPT_CHARS // 2)
        if excerpt_start < previous_end:
            continue
        excerpt = re.sub(r"\s+", " ", text[excerpt_start:excerpt_end]).strip()
        if excerpt_start:
            excerpt = "…" + excerpt
        if excerpt_end < len(text):
            excerpt += "…"
        matches.append({"offset": offset, "excerpt": excerpt})
        previous_end = excerpt_end
    return len(occurrences), matches


def _tool_arguments(request: Any, expected_tool: str) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise PluginError("request must be a JSON object")
    if request.get("tool") != expected_tool:
        raise PluginError(f"unknown tool; expected {expected_tool}")
    arguments = request.get("arguments")
    if not isinstance(arguments, dict):
        raise PluginError("arguments must be a JSON object")
    return arguments


def _search_arguments(request: Any) -> tuple[str, int]:
    arguments = _tool_arguments(request, "web_search")
    query = arguments.get("query")
    if not isinstance(query, str) or not query.strip():
        raise PluginError("query must be a non-empty string")
    query = query.strip()
    if len(query) > MAX_QUERY_LENGTH:
        raise PluginError(f"query must be at most {MAX_QUERY_LENGTH} characters")
    max_results = arguments.get("max_results", DEFAULT_MAX_RESULTS)
    if isinstance(max_results, bool) or not isinstance(max_results, int):
        raise PluginError("max_results must be an integer")
    if not 1 <= max_results <= MAX_RESULTS:
        raise PluginError(f"max_results must be between 1 and {MAX_RESULTS}")
    return query, max_results


def _open_arguments(request: Any) -> tuple[str, str | None]:
    arguments = _tool_arguments(request, "web_open")
    url = arguments.get("url")
    if not isinstance(url, str) or not url.strip():
        raise PluginError("url must be a non-empty string")
    url = url.strip()
    if len(url) > MAX_URL_LENGTH:
        raise PluginError(f"url must be at most {MAX_URL_LENGTH} characters")
    find = arguments.get("find")
    if find is not None:
        if not isinstance(find, str) or not find.strip():
            raise PluginError("find must be a non-empty string when provided")
        find = find.strip()
        if len(find) > MAX_FIND_LENGTH:
            raise PluginError(f"find must be at most {MAX_FIND_LENGTH} characters")
    return _validate_page_url(url), find


def _content(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def handle(
    request: Any,
    environ: Mapping[str, str] | None = None,
    progress: Progress | None = None,
) -> dict[str, str]:
    environ = os.environ if environ is None else environ
    progress = progress or (lambda stage, preview: None)
    tool = request.get("tool") if isinstance(request, dict) else None
    if tool == "web_search":
        query, max_results = _search_arguments(request)
        progress("search", "Searching the web")
        searxng_url = environ.get("SEARXNG_URL", "").strip()
        tavily_key = environ.get("TAVILY_API_KEY", "").strip()
        if searxng_url:
            results = _search_searxng(searxng_url, query, max_results)
            provider = "searxng"
        elif tavily_key:
            results = _search_tavily(tavily_key, query, max_results)
            provider = "tavily"
        else:
            raise PluginError(
                "web_search is not configured; set SEARXNG_URL or TAVILY_API_KEY",
                code="configuration_error",
                stage="search",
            )
        return {
            "content": _content(
                {
                    "format": RESULT_FORMAT,
                    "stage": "search",
                    "provider": provider,
                    "query": query,
                    "results": _normalized_results(results),
                }
            )
        }
    if tool == "web_open":
        url, find = _open_arguments(request)
        progress("open_page", "Opening page")
        page = _open_page(url)
        if find is None:
            return {
                "content": _content(
                    {
                        "format": RESULT_FORMAT,
                        "stage": "open_page",
                        "page": page,
                    }
                )
            }
        progress("find_in_page", "Finding text in page")
        total, matches = _find_matches(page.pop("text"), find)
        return {
            "content": _content(
                {
                    "format": RESULT_FORMAT,
                    "stage": "find_in_page",
                    "page": page,
                    "query": find,
                    "match_count": total,
                    "matches": matches,
                }
            )
        }
    raise PluginError("unknown tool; expected web_search or web_open")


def _call_id(request: Any) -> str:
    if not isinstance(request, dict):
        raise PluginError("request must be a JSON object")
    context = request.get("context")
    if not isinstance(context, dict):
        raise PluginError("context must be a JSON object")
    call_id = context.get("call_id")
    if not isinstance(call_id, str) or not call_id.strip():
        raise PluginError("context.call_id must be a non-empty string")
    return call_id.strip()


def _event(call_id: str, sequence: int, event_type: str, **fields: Any) -> None:
    value = {
        "type": event_type,
        "call_id": call_id,
        "seq": sequence,
        **fields,
    }
    sys.stdout.write(json.dumps(value, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    line = sys.stdin.readline()
    try:
        request = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _event(
            "unknown",
            1,
            "result",
            ok=False,
            error={
                "code": "invalid_request",
                "message": f"invalid request JSON: {error}",
                "retryable": False,
            },
        )
        return 0
    try:
        call_id = _call_id(request)
    except PluginError as error:
        _event("unknown", 1, "result", ok=False, error=error.value())
        return 0

    sequence = 0

    def report_progress(stage: str, preview: str) -> None:
        nonlocal sequence
        sequence += 1
        _event(
            call_id,
            sequence,
            "progress",
            stage=stage,
            preview=preview,
        )

    try:
        response = handle(request, progress=report_progress)
    except PluginError as error:
        sequence += 1
        _event(call_id, sequence, "result", ok=False, error=error.value())
        return 0
    sequence += 1
    _event(call_id, sequence, "result", ok=True, content=response["content"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
