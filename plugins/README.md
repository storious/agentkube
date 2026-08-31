# Plugins

Reusable tools and integrations for Agul live here.

- [`web-search`](web-search/README.md) adds an optional `web_search` tool backed
  by a configured SearXNG instance or Tavily.
- [`coordinator`](coordinator/README.md) lets one master Agul delegate up to
  five bounded tasks to locally prepared specialists through ARI.

Both manifests use `agul/plugin/v2` NDJSON events. Plugins are custom
capabilities loaded by Agul. AgentKube supplies the package; it does not add
another CLI or runtime.
