# Coordinator Plugin

`coordinator` delegates one to five bounded tasks to specialists already
prepared by Agulater. Each task gets one fresh `agul ari serve` process and one
ARI session. The Plugin is only an execution bridge: it does not download
packages, invoke Agulater, maintain a daemon, commit, or push.

## Prepared inputs

Agul Plugin v2 supplies an absolute `context.workspace` and the current
`context.launch_path`. The coordinator locates `specialists.json` and
`pools.json` beside that launch file. Specialist launch/snapshot paths are
resolved relative to the registry, and each selected pool must satisfy the
specialist's minimum context window and capabilities.

The prepared registry must use strict `agulater/pools/v2`. Every pool declares
an `engine` and the coordinator rejects v1, unknown fields, or fields belonging
to the other engine. Agulater strips the source-only `override` marker; a
boolean marker has no effect if a hand-authored registry retains it. Native
pools describe an OpenAI-compatible endpoint:

```json
{
  "id": "local-default",
  "engine": "native",
  "provider": "openai-compatible",
  "endpoint": "http://127.0.0.1:51100/v1/chat/completions",
  "model": "local-model",
  "context_window": 32768,
  "capabilities": ["read", "write", "edit", "shell"],
  "max_concurrency": 5,
  "request_timeout_seconds": 600
}
```

Codex pools use the host's ChatGPT account and may select a model or executable:

```json
{
  "id": "codex-account",
  "engine": "codex",
  "capabilities": ["read", "write", "edit", "shell"],
  "max_concurrency": 1,
  "request_timeout_seconds": 900
}
```

A Codex `context_window` is an optional routing declaration. When absent, the
coordinator does not guess a limit; when present, it still checks the
specialist minimum. It is never sent to ARI. Native sessions receive endpoint
and harness loop limits, while Codex sessions receive only `engine`, timeout,
and any declared model, reasoning effort, or `codex_command`, plus common
attribution fields.

The source-tree `starters/self-maintainer` starter provides all four packages
and portable DeepSeek, GLM Coding Plan,
ChatGPT/Codex, and local-example Pools. Keep it in the AgentKube tree so its
relative resources remain available, choose a Pool, and run Agulater once
before starting Agul:

```console
cd starters/self-maintainer
agulater prepare --path .
agul
```

Runtime coordination has no Agulater dependency.

Run one prepared Specialist directly from the workbench:

```text
/agent repository-scout locate the package compiler entrypoint
```

The first word is the Specialist ID and the remaining text is its task. For
several tasks or explicit Pool selection, the model-facing `delegate_tasks`
tool remains the structured interface. `/agent` also accepts that same payload
as compact JSON: `/agent {"tasks":[...]}`.

## `delegate_tasks`

```json
{
  "tasks": [
    {
      "id": "trace",
      "specialist": "repository-scout",
      "task": "Trace the price sync call path and report exact evidence.",
      "paths": ["src/runtime/billing", "src/commands"]
    },
    {
      "id": "docs",
      "specialist": "docs-editor",
      "task": "Update the usage guide from the confirmed implementation.",
      "context": "Use the trace handoff supplied by the master.",
      "paths": ["docs/sessions-and-usage.md"]
    }
  ]
}
```

`id`, `pool`, `context`, and `paths` are optional; `specialist` and `task` are
required. Missing IDs become `task-1`, `task-2`, and so on. A missing or
accidentally blank pool uses the prepared `default_pool`, so normal calls do not
need to inspect `pools.json`.
`specialist` is a prepared role ID such as `repository-scout`; `pool` is an
execution-pool ID and should only be supplied to override the default.

For an explicit Pool override, add its prepared ID, such as
`"pool": "deepseek"`, to that task.

All `workspace_effect: read` tasks start first and may run concurrently, bounded
by each pool's `max_concurrency`. The coordinator waits for that phase, then
runs `workspace_effect: write` tasks serially. Results remain in input order.

## Plugin v2 stream

Standard output is NDJSON. Every line repeats the call ID and uses consecutive
sequence numbers:

```json
{"type":"progress","call_id":"call-1","seq":1,"stage":"prepared","preview":"Prepared 1 delegated task(s)"}
{"type":"progress","call_id":"call-1","seq":2,"stage":"read_phase","preview":"Running 1 read task(s)"}
{"type":"progress","call_id":"call-1","seq":3,"task_id":"trace","stage":"starting","preview":"Starting repository-scout"}
{"type":"session","call_id":"call-1","seq":4,"relation":"delegated","session_id":"...","delegation_id":"...","task_id":"trace"}
{"type":"progress","call_id":"call-1","seq":5,"task_id":"trace","stage":"read","preview":"◆ src/runtime/plugin.rs"}
{"type":"progress","call_id":"call-1","seq":6,"task_id":"trace","stage":"read","preview":"✓ src/runtime/plugin.rs · 42ms"}
{"type":"progress","call_id":"call-1","seq":7,"task_id":"trace","stage":"completed","preview":"Found the loader"}
```

The next and final line is `result`. This abbreviated envelope uses strings in
angle brackets only to mark values omitted from the documentation; they are not
wire values:

```json
{"type":"result","call_id":"call-1","seq":8,"ok":true,"content":{"delegation_id":"...","status":"completed","results":"<ordered task results>","handoff":"<task handoffs>","usage":"<exact aggregate>"}}
```

While a child is running, its ARI `tool` and `tool_progress` events become
compact parent progress lines tagged with the outer task ID. The coordinator
folds whitespace, limits each preview to 160 characters, and assigns the
parent call ID and sequence. Child reasoning, streamed answer text, internal
call IDs, and internal task IDs stay in the child session instead of flooding
the parent conversation. Usage events continue into the exact aggregate
ledger. Adjacent duplicate child progress is collapsed; each child can emit at
most 32 fine-grained progress lines before one omission notice, while tool
start and finish lines always remain visible. Concurrent task events may
interleave and remain attributable through `task_id`.

There is exactly one final `result` event. Its content contains:

- `delegation_id` and aggregate `completed`, `partial`, or `failed` status;
- ordered per-task `results`, including session, rounds, tool calls, errors,
  and exact ledger entries;
- `handoff`, keyed by task ID, with the complete parsed handoff object;
- an exact aggregate `usage` summary derived from ledger entries.

Each specialist response must finish with no trailing text after this block:

```text
<agul-handoff format="agul/handoff/v1">{"format":"agul/handoff/v1","status":"completed","summary":"..."}</agul-handoff>
```

[Agul owns the handoff schema](https://github.com/storious/agul/blob/main/schemas/handoff-v1.schema.json)
and is the only component that parses it. The Coordinator consumes the
canonical `handoff` value returned by `ari.send`; it never reparses visible
model text. A missing or `null` value therefore fails the task even when the
text contains something that resembles a handoff.
Agulater places its required shape in the Specialist's stable compiled
instructions. The Coordinator sends only the changing task, optional context,
and scoped paths, keeping repeated delegation prefixes smaller and cacheable.

Missing, malformed, non-final, wrong-format, or schema-invalid handoffs fail
that task while preserving other results and usage already observed.
Agul may normalize one terminal Markdown fence for smaller models before it
returns the canonical value; that compatibility remains entirely inside Agul's
parser and does not create a second Coordinator parser.

`AGUL_SUBAGENT_BINARY` may select the local Agul executable for development or
tests. Engine, provider routing, model, limits, launch paths, and concurrency
come from the prepared specialist and pool registries rather than tool
arguments or ambient download logic. A pool's explicit `reasoning_effort`
takes precedence because it describes what that model supports; the specialist
default is used only when the pool leaves it unset. The parent Plugin budget is
6,300 seconds so five worst-case write tasks can remain serial; each child still
has its own harness worker deadline and pool request timeout.
