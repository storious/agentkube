# Architecture

```text
AgentKube packages
       |
       v
Agulater installs and prepares them
       |
       v
Agul runs the resulting agent
```

Agul is the small runtime and terminal application. Agulater installs and
updates that runtime, resolves extension sources, and prepares readable
packages. AgentKube is where optional extensions are collected and shared.
Its checked-in instance of `agulater/catalog/v1` gives Agulater versioned Git
sources for discovery. Minimal Agul needs none of these packages; a custom
agent gains focused abilities by loading only the AgentKube extensions its
prepared launch names.

When Agulater is installed, Agul exposes it as the compact
`system/agulater` capability. A registered AgentKube catalog adds
`system/agentkube`. Both still use Agul's existing shell tool: Agul does not
gain a downloader, and AgentKube does not gain a CLI. An installed Skill can
be read and applied in the same task, then appears through normal Skill
discovery on the next session.

The multi-agent design does not add another application. The optional
[Coordinator Plugin](../../plugins/coordinator/README.md) lets one Agul instance
act as the master and start independent prepared specialist Agul sessions.
Read tasks run concurrently and write tasks serially; specialists return a
structured handoff while the master owns decomposition, verification,
integration, and the final response. The optional
[Web Search Plugin](../../plugins/web-search/README.md) follows the same small
Plugin boundary. AgentKube remains package content, not the process hosting
that content.

ARI is how an external integration drives Agul without becoming another
runtime. It is also the collaboration seam used by the coordinator to drive
specialist Agul sessions and collect their per-response usage. The
[small Python example](../../examples/README.md) starts an Agul session from an
Agulater launch, forwards streamed reasoning, text, tool, and usage events, and
returns the final result.

The [validation policy](../validation/README.md) keeps raw dogfood state local
and the public result small, so this page remains an evergreen description of
the boundaries.
