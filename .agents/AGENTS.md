# AgentKube

AgentKube is a collection of optional Agents, Skills, Plugins, starters, and
catalog entries for Agul.

- Put runtime and terminal work in `agul/`.
- Put installation and preparation work in `agulater/`.
- Put reusable extensions and examples in this repository.
- Do not add another AgentKube CLI or runtime.
- Keep each extension understandable on its own and document how to use it.
- Load a Skill from `skills/` only when the task calls for it.
- Follow `CONTRIBUTING.md` for the branch and release flow before starting
  repository work.
- Before adding or materially expanding generic infrastructure, inspect mature
  engineering libraries first. If a parser, terminal component, protocol
  framer, schema validator, version resolver, archive handler, HTTP/SSE layer,
  or process state machine is likely to exceed roughly 100 lines, record the
  candidates and why they fit or do not fit before implementing it. Keep
  AgentKube-specific coordination policy in-house; do not reimplement solved
  infrastructure around it.

Run the smallest relevant check for the files you change.
