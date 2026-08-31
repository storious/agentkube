# Focused verification

- Start with the most specific existing test or check for the supplied paths.
- Expand only when the focused result is insufficient to answer the task.
- Test runners may create ordinary build or cache artifacts. Do not edit tracked
  source or accept/update generated expectations.
- Report command, exit outcome, and the smallest useful failure excerpt.
- Distinguish a product failure from an environment or prerequisite failure.
