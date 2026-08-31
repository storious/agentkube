# Self Maintainer Starter

This starter assembles the coordinator and Web Search Plugin with four prepared
specialists: repository scouting, focused testing, documentation editing, and
short source patches. It can search, open the source page, and find relevant
text before delegating implementation work.

From an AgentKube checkout or source archive, keep this directory in its
original location so its package-relative resources remain available. Choose a
Pool in `.agents/pools.json`, then run `agulater prepare --path .` here before
starting Agul. The shipped default is DeepSeek; GLM Coding Plan and
ChatGPT/Codex are ready-to-select alternatives. `local-example` must be edited
for the user's own endpoint and model before it is selected; it defaults to
`medium` reasoning so a bounded worker can reliably finish its handoff.

Configure `SEARXNG_URL` or `TAVILY_API_KEY` only for `web_search`. Opening a
known page with `web_open` needs neither service. The optional
`codex-account` Pool uses the host's ChatGPT login for harder work and live
Web Search. Run `agul account login` once before selecting it. Credentials and
subscription details never belong in `pools.json`.

The starter contains no downloader and does not run Agulater at runtime. It is
not installed as a nested Catalog Package: use the checked-in starter as a
project root, or assemble the same root from the individual Catalog entries.
