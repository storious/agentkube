# ARI example

This example combines all three projects without adding another runtime:

1. Agulater creates a workspace and installs AgentKube's `grilling` Skill.
2. Agulater prepares the workspace's thin launch file.
3. `grilling_over_ari.py` starts Agul and talks to it through ARI.

From the shared development workspace:

```powershell
bun .\agulater\tools\agulater.ts create grilling-demo --path .\grilling-demo
bun .\agulater\tools\agulater.ts add .\.agents\skills\grilling --path .\grilling-demo
bun .\agulater\tools\agulater.ts prepare --path .\grilling-demo
$env:AGUL = "agul"
python -m examples.grilling_over_ari .\grilling-demo "Grill my release plan"
```

Set `AGUL` to the Agul executable when it is not on `PATH`. Use `--model` and
`--base-url` to select an OpenAI-compatible model endpoint for the session.
