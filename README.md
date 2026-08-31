# AgentKube

AgentKube is the optional extension collection for
[Agul](https://github.com/storious/agul). It contains Skills, Plugins,
specialist agent packages, and starters. It is not a CLI and it does not
replace Agul.

## Do you need it?

- For a normal coding session: **no**. Install or build Agul and run `agul`.
- For Web Search, prepared specialists, or multi-agent delegation: install only
  the AgentKube pieces you need.
- To install and prepare those pieces: use
  [Agulater](https://github.com/storious/agulater). Its published
  installer is standalone; normal users do not need Bun, Node.js, or npm.

## What is included

| Path | Capability |
| --- | --- |
| `plugins/web-search/` | Search, open a known URL, and find text in a page |
| `plugins/coordinator/` | Delegate bounded tasks to prepared Agul workers |
| `agents/` | Repository scout, focused tester, docs editor, and short patcher |
| `.agents/skills/` | `grill-me` and `grilling` Skills |
| `starters/self-maintainer/` | Example master setup using the coordinator and specialists |
| `catalog/` | Versioned entries that Agulater can discover and install |

`web_open` reads a known page without configuring a search engine.
`web_search` requires SearXNG or Tavily because it performs an actual search.
The coordinator starts separate Agul ARI workers; local and DeepSeek pools can
be used together, while the master remains responsible for integration and the
final answer.

## Install the optional manager

Install Agulater only when you want AgentKube extensions or managed Agul
updates. The first experience release is a prerelease, so use its pinned URL:

Linux or macOS:

```console
curl -fsSL https://github.com/storious/agulater/releases/download/v0.2.1-rc.1/install.sh | sh
```

Windows PowerShell:

```powershell
irm https://github.com/storious/agulater/releases/download/v0.2.1-rc.1/install.ps1 | iex
```

The installer downloads a self-contained Agulater executable and creates a
general user `.agents` package only when one does not already exist. Bun is
needed only by contributors running Agulater from TypeScript source.

## Try the checked-in starter

Make sure `agul` and `agulater` are on `PATH`, then run:

```console
cd starters/self-maintainer
agulater prepare --path .
agul
```

The default master uses DeepSeek. `.agents/pools.json` also contains GLM Coding
Plan, ChatGPT/Codex, and a local OpenAI-compatible template. Local workers use
`medium` reasoning by default. Python 3 is required by the Coordinator and Web
Search Plugins.

## Install one capability

Agulater can install individual published Catalog entries instead of the whole
collection:

```console
agulater catalog add agentkube https://raw.githubusercontent.com/storious/agentkube/main/catalog/catalog.json
agulater add agentkube:web-search --path . --type plugin
agulater add agentkube:repository-scout --path . --type package
agulater prepare --path .
```

Use `--user` instead of `--path .` for a user-level install. Registering the
Catalog does not download every extension.

## Project boundaries

- **Agul** runs the model loop, TUI, four core tools, sessions, Usage Ledger,
  Skills, Plugins, and ARI.
- **Agulater** installs and updates runtimes and extensions, then prepares
  `.agents` packages.
- **AgentKube** supplies optional extension content.

Formats and examples are documented in the [package guide](docs/packages/README.md),
[coordinator contract](plugins/coordinator/README.md), and
[catalog guide](catalog/README.md). The
[reference-project notes](docs/reference-projects.md) record what the project
learns from Pi and other terminal agents, and where the three-part design
deliberately differs. Maintainers can use the
[hands-on acceptance checklist](docs/acceptance/README.md).

Apache-2.0. Third-party notices are in
[`.agents/THIRD_PARTY_NOTICES.md`](.agents/THIRD_PARTY_NOTICES.md).
