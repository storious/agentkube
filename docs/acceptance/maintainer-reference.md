# Maintainer acceptance supplement

Use this supplement after completing the shorter
[release-owner checklist](README.md). It adds repeatable diagnostics without
turning local account, model, or session data into repository documentation.

## Keep evidence local

Create an ignored run directory from the current checkout rather than writing
machine-specific paths into scripts or reports:

```powershell
$Repo = (Resolve-Path .).Path
$Stamp = (Get-Date -Format "yyyyMMdd-HHmmss") + "-" +
  [guid]::NewGuid().ToString("N").Substring(0, 8)
$RunRoot = Join-Path $Repo (".tmp/acceptance-" + $Stamp)
New-Item -ItemType Directory -Path $RunRoot | Out-Null
```

Raw screenshots, model responses, traces, session files, account status, and
usage ledgers stay below `$RunRoot`. They are release-owner evidence, not
source artifacts. A public validation note may retain only:

- candidate versions and public commit hashes;
- a capability-level `PASS`, `FAIL`, or `BLOCKED` result;
- public CI or Release URLs;
- a concise product defect that another user can reproduce.

Do not commit credentials, private network routes, absolute machine paths,
account plan details, upstream thread identifiers, session identifiers, or
per-account token and cost totals.

## Local model configuration

The repository contains no maintainer-specific model route. The owner supplies
the route for the current terminal, and the main checklist generates a
temporary Pool file from it:

```powershell
$Required = @(
  "AGUL_ACCEPTANCE_LOCAL_ENDPOINT",
  "AGUL_ACCEPTANCE_LOCAL_MODEL"
)
foreach ($Name in $Required) {
  $Value = [Environment]::GetEnvironmentVariable($Name)
  if ([string]::IsNullOrWhiteSpace($Value)) {
    throw "$Name is required for the local-worker acceptance section"
  }
}

$LocalUri = [uri]$env:AGUL_ACCEPTANCE_LOCAL_ENDPOINT
if (-not $LocalUri.IsAbsoluteUri -or
    $LocalUri.Scheme -notin @("http", "https")) {
  throw "AGUL_ACCEPTANCE_LOCAL_ENDPOINT must be an absolute HTTP(S) URL"
}
```

Optional tuning variables are
`AGUL_ACCEPTANCE_LOCAL_CONTEXT_WINDOW`,
`AGUL_ACCEPTANCE_LOCAL_MAX_CONCURRENCY`, and
`AGUL_ACCEPTANCE_LOCAL_TIMEOUT_SECONDS`. The checklist uses portable defaults
when they are absent. Never echo the full environment while collecting
evidence.

## Focused automated checks

Run the collection and Plugin checks before real model traffic:

```powershell
python -m unittest -v `
  tests.test_collection `
  tests.test_coordinator_plugin `
  tests.test_web_search_plugin
```

Then run the three projects' own test suites from their repositories. A failed
automated check blocks the candidate; a passing check does not replace the TUI,
account login, Web, or delegated-worker observations in the owner checklist.

## Usage Ledger invariants

For each machine-readable provider result retained under `$RunRoot`, verify
these properties without copying the raw ledger into Git:

- every response has one unique response identifier;
- input, output, reasoning, and cache-hit counts are non-negative;
- DeepSeek currency entries cite a versioned price card;
- GLM Coding Plan and ChatGPT account entries are quota-backed and have no
  invented currency price;
- an unpriced local endpoint remains explicitly unpriced;
- a compaction response is recorded separately from the user-visible turn.

The terminal may round displayed cost, but persisted arithmetic must remain
exact. Record only the invariant result publicly.

## Failure-path checks

Before approval, exercise these paths in disposable directories below
`$RunRoot`:

1. An explicitly configured Plugin directory containing no `plugin.json`
   fails visibly before a model request.
2. A failed Agulater `prepare` leaves the previous prepared snapshot usable.
3. `/stop`, Ctrl+C, and steer settle the active parent and child operations
   without losing already recorded usage.
4. `--continue` and the `--resume` picker work without requiring the user to
   copy a session identifier.
5. `web_open` works without a search provider; `web_search` reports a clear
   configuration error when neither supported provider is configured.

Store the disposable inputs and raw output locally. Add a repository regression
test for any defect found; do not publish the private run transcript.

## Final public record

Use the blank result table in the owner checklist. Keep the outcome short and
reproducible. A release must still be based on clean candidate manifests, and
the first post-release download smoke must use public artifacts rather than the
local build directory.
