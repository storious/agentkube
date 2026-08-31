# 0.6 release batch

This batch is deliberately split across three independently versioned projects:

| Project | Candidate | Role |
| --- | --- | --- |
| Agul | 0.6.0-rc.1 | Runtime, TUI, four core tools, sessions, Usage Ledger, ARI |
| Agulater | 0.2.1-rc.2 | Optional runtime/extension lifecycle and Package preparation |
| AgentKube | 0.2.3-rc.1 | Optional Skills, Plugins, specialist Packages, and source starters |

Coordinator and Self Maintainer source manifests are `0.3.2-rc.1`. The Catalog
publishes this Coordinator preview from its matching immutable tag; the root
Self Maintainer remains a source starter rather than a nested Catalog package.

## Supported user paths

The install route depends on whether the artifacts have been published. Do not
use the stable commands below to test an unpublished release candidate.

| State | Direct Agul route | Optional Agulater route |
| --- | --- | --- |
| Current unpublished candidate | Extract the local Agul archive produced by the owner checklist | Run the local standalone Agulater candidate, then install the local Agul runtime index |
| Published prerelease | Download the tagged platform archive or tagged installer | Download the tagged standalone Agulater asset or attached installer, then `runtime install --channel next` |
| Published stable | Run the release `install.sh`/`install.ps1` or download a platform archive | Run Agulater's `install.sh`/`install.ps1`, then `runtime install --channel stable` |

Windows x64, Linux x64, and macOS x64/ARM64 have standalone Agul release
artifacts. Agulater publishes the same platform set as self-contained
executables. Normal users need no Bun, Node.js, or npm for either application;
Bun remains only in Agulater's source build and optional npm compatibility
path. A new terminal may be needed after either installer changes `PATH`.
AgentKube Plugins require Python 3 on `PATH`; add individual Plugin and Package
entries to a root `.agents` package rather than installing the source starter
as a nested Package.

GLM means Coding Plan throughout the public CLI, ARI, docs, and acceptance.
ChatGPT-account mode uses the official Codex account flow and quota. Opening a
known page with AgentKube `web_open` needs no search provider; only
`web_search` needs SearXNG or Tavily.

The acceptance pool keeps local workers at `medium` reasoning by default. The
owner must personally complete a fresh official ChatGPT/Codex login during
acceptance; an already-present account status is not enough to pass the gate.

## Publication gate

The owner checklist is [acceptance/README.md](acceptance/README.md). It builds a
local Agul archive and standalone Agulater executable, runs both without a
runtime dependency, then exercises the real TUI, GLM Coding Plan, ChatGPT Web
Search, session recovery, and local plus DeepSeek workers. It also packs the
optional npm artifact for maintainers. No public artifact is needed to pass
that pre-publication gate.

Only after explicit owner approval:

1. promote the accepted `dev` commits to each `main`;
2. create immutable AgentKube asset tags and update the Catalog to those exact
   stable manifests;
3. publish Agul platform assets;
4. publish Agulater platform archives and one-line installers; optionally
   publish the same source version to npm as a compatibility route;
5. repeat a clean install from the public GitHub assets and runtime channel.

## GitHub About and visibility

These values were applied to the three GitHub About panels on 2026-08-31. This
metadata update did not merge `dev`, publish a release, or change repository
visibility or default branches.

| Repository | Description | Topics |
| --- | --- | --- |
| `storious/agul` | Terminal coding agent with a full-screen TUI, four core tools, persistent sessions, usage tracking, and optional extensions. | `ai-agent`, `coding-agent`, `terminal`, `tui`, `rust`, `llm`, `chatgpt`, `deepseek`, `glm` |
| `storious/agulater` | Optional package and lifecycle manager for Agul runtimes, Skills, Plugins, and `.agents` packages. | `agul`, `cli`, `package-manager`, `agent-skills`, `plugins`, `standalone`, `typescript` |
| `storious/agentkube` | Optional Skills, Plugins, specialist agents, Web Search, and multi-agent coordination for Agul. | `agul`, `ai-agents`, `agent-skills`, `plugins`, `multi-agent`, `web-search`, `agent-extensions` |

Homepage remains blank until there is a maintained public documentation site.
Descriptions, topics, license detection, visibility, and the default branch
must eventually describe the same accepted source state.

Before changing visibility, verify that `storious/agulater` resolves to the
accepted Apache-2.0 source, uses `main` as its default branch, and publishes
standalone installers from that same release commit. Old repository redirects
may remain for existing links, but documentation, package metadata, and
installers use the canonical `storious/agulater` address.
