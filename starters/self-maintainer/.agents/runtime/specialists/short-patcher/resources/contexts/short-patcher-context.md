# Focused patching

- Treat supplied `paths` as the write boundary and keep a normal patch to five
  files or fewer.
- Inspect adjacent tests before changing behavior.
- Avoid generated files and unrelated cleanup.
- Preserve user changes already present in the workspace.
- Run the narrowest check that exercises the edited behavior.
