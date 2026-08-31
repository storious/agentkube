# Focused Tester

`focused-tester` runs a bounded, read-only verification pass, diagnoses the
first useful failure, and reports reproducible evidence without editing source.
Its harness reserves eight model rounds so a small multi-check pass can still
finish with the required compact handoff.

The installable Agulater package is in [`.agents`](.agents/).
