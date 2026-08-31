# Agents

Each directory contains an independently preparable `agulater/package/v2`
specialist under `.agents/`:

- `repository-scout` performs read-only search and implementation tracing.
- `focused-tester` runs focused checks without changing tracked source.
- `docs-editor` makes bounded documentation-only changes.
- `short-patcher` makes small source patches, normally five files or fewer.

Every package includes eager context, a frozen harness, and an
`agul/handoff/v1` result contract. Agulater prepares these into the runtime
specialist registry consumed by the coordinator.

Specialists spend intermediate rounds on tool work rather than progress prose.
Their final handoff keeps the summary within 240 characters and includes at
most four evidence items.
