# Validation

The executable release gate is the
[three-repository acceptance checklist](../acceptance/README.md). Historical
model runs never substitute for a fresh candidate run.

## Public evidence policy

Raw dogfood evidence stays in the ignored `.tmp/` directory of the maintainer
checkout. It may contain account state, private model routes, terminal paths,
session metadata, and detailed usage, so it is not committed.

A public validation note should contain only:

- candidate versions and public commit hashes;
- a small capability matrix with `PASS`, `FAIL`, or `BLOCKED`;
- public CI and Release URLs;
- concise, reproducible defects or limitations.

Do not publish credentials, private network addresses, absolute host paths,
account plan details, upstream thread or session identifiers, raw transcripts,
or per-account token and cost totals.

The first formal experience release requires a fresh owner run of the complete
checklist, followed by a clean install from the published artifacts. Record the
public result here only after that flow finishes.
