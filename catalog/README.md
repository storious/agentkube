# Catalog

`catalog.json` is an AgentKube instance of Agulater's
`agulater/catalog/v1` discovery contract.
Each entry has an ID, a `package`, `skill`, or `plugin` kind, a description,
and one or more versions whose source is a Git URL plus an optional
subdirectory. Released versions use matching Git tags; moving branches are
reserved for an explicit development channel.

Catalog discovery, installation, and updates are Agulater concerns. AgentKube
only publishes the contents. It has no downloader or CLI of its own.

A scoped Skill source includes its own required third-party notice. This keeps
license attribution intact when Agulater installs only the Catalog `subdir`
rather than cloning the repository root.

Catalog Packages are intended to become prepared specialists inside an
existing root. Root starter templates are therefore not advertised as nested
Package entries: use `starters/self-maintainer` from an AgentKube source archive
or assemble a root from the individual Plugin and specialist entries.
