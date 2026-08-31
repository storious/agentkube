# Packages

| Collection | Use it for |
| --- | --- |
| `agents/` | A complete assistant setup for a particular kind of work |
| `skills/` | Focused instructions an agent can load when needed |
| `plugins/` | Reusable tools or integrations |
| `starters/` | Small templates users can copy and customize |
| `catalog/` | Names and locations Agulater can browse |

Each extension should have a short README, an example, and a way to check that
it works. Prefer one understandable package over several layers of metadata.

AgentKube packages use `agulater/package/v2`. A specialist package adds a
`profile` naming accepted work, `read` or `write` workspace effect, eager
contexts, and an `agulater/harness/v1`. Agulater resolves local composition at
prepare time and writes `launch.json`, `snapshot.json`, `specialists.json`, and
`pools.json` under `.agents/runtime/`.

Agul Plugins use `agul/plugin/v2`. Agul sends a request envelope containing
`tool`, `arguments`, and call `context`; the process writes NDJSON `progress`,
`session`, and final `result` events with one call ID and consecutive sequence
numbers. A final error is a `result` event rather than an ad-hoc stdout shape.
See [`plugins/web-search`](../../plugins/web-search/README.md) for a compact
tool and [`plugins/coordinator`](../../plugins/coordinator/README.md) for a
streaming delegated-session example.

Agulater owns package, catalog, harness, pool, and prepared-runtime formats.
[Agul owns ARI and the `agul/handoff/v1` schema](https://github.com/storious/agul/blob/main/schemas/handoff-v1.schema.json).
AgentKube publishes extensions using those contracts and owns only the Web
Search result format produced by its Plugin.
