# Web Search Plugin

`web-search` is AgentKube's optional search-and-read Plugin for Agul. It keeps
the discovery step small, then lets the model open a result or find a phrase in
that page instead of treating a search snippet as evidence.

It requires Python 3 to be available as `python` on `PATH` and exposes two
tools:

- `web_search` returns structured titles, URLs, and snippets.
- `web_open` downloads an HTTP or HTTPS page as readable text. Supplying
  `find` returns focused excerpts from that page.

From an AgentKube checkout, install it into a custom agent and prepare that
agent's launch with Agulater:

```console
agulater create search-agent --path ./search-agent
agulater add ./plugins/web-search --type plugin --path ./search-agent
agulater prepare --path ./search-agent
cd search-agent
agul
```

Agulater copies the Plugin into the custom package and records its Plugin
directory in `runtime/launch.json`. Agul discovers and runs it from that launch.
The checked-in `self-maintainer` starter already includes it.

## Search provider

Configure either:

- `SEARXNG_URL`: the base URL of a SearXNG instance. The Plugin sends
  `GET /search?q=...&format=json` and prefers this provider when both settings
  exist. The instance must enable JSON responses.
- `TAVILY_API_KEY`: a Tavily key. The Plugin sends a basic search to the
  official `POST https://api.tavily.com/search` endpoint.

For example:

```powershell
$env:SEARXNG_URL = "http://localhost:8080"
agul
```

or:

```powershell
$env:TAVILY_API_KEY = "tvly-..."
agul
```

Opening a page does not require either search setting. It reads HTML, plain
text, JSON, or XML directly over HTTP, extracts readable text without browser
rendering, and returns up to 12,000 characters. A response body larger than
2 MB is rejected with a compact tool error.

## Tool flow

A model can search, follow a result, and narrow a long page without another
extension:

```text
web_search {"query":"Agul ARI","max_results":3}
web_open   {"url":"https://example.com/agul"}
web_open   {"url":"https://example.com/agul","find":"ARI"}
```

Every successful tool result is a JSON string with
`"format":"agul/web-search-result/v1"`. Search results use `stage: "search"`:

```json
{
  "format": "agul/web-search-result/v1",
  "stage": "search",
  "provider": "searxng",
  "query": "Agul ARI",
  "results": [
    {
      "title": "Agul",
      "url": "https://example.com/agul",
      "snippet": "A small agent runtime."
    }
  ]
}
```

Opening returns `stage: "open_page"` with page metadata and readable text.
Passing `find` returns `stage: "find_in_page"`, the total occurrence count, and
up to eight excerpts. This makes the source URL and the operation that produced
the evidence explicit while keeping Plugin protocol v2 unchanged.

## Plugin protocol

Agul starts the declared command once per tool call with the Plugin directory
as its working directory and writes one request envelope to standard input:

```json
{"tool":"web_open","arguments":{"url":"https://example.com/agul","find":"ARI"},"context":{"call_id":"call-1","session_id":"session-1","workspace":"/work/project","launch_path":"/work/project/.agents/runtime/launch.json"}}
```

Standard output is NDJSON with consecutive sequence numbers and exactly one
final `result`. Progress stages are `search`, `open_page`, and `find_in_page`:

```json
{"type":"progress","call_id":"call-1","seq":1,"stage":"open_page","preview":"Opening page"}
{"type":"progress","call_id":"call-1","seq":2,"stage":"find_in_page","preview":"Finding text in page"}
{"type":"result","call_id":"call-1","seq":3,"ok":true,"content":"{...}"}
```

Invalid input, missing search settings, provider failures, and unreadable pages
return `ok: false` with a compact structured error. They do not mix protocol
data with standard error.

See the official [SearXNG Search API](https://docs.searxng.org/dev/search_api.html)
and [Tavily Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search)
for provider details.
