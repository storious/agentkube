# Reference projects

Reviewed on 2026-08-31 against first-party documentation. These projects are
design references, not dependencies or compatibility targets. We record the
specific lesson we are taking from each one so that "inspired by" does not
turn into copying an entire product surface.

## Pi

Pi describes itself as a minimal terminal coding harness whose core stays
small while extensions, Skills, prompt templates, themes, and packages provide
optional behavior. Its interactive terminal, steering while a turn is running,
tree-structured sessions, compaction, progressive Skill loading, and compact
package story are specific references for Agul's everyday terminal
experience. Pi also offers direct shell and PowerShell installers in addition
to package-manager installation; a user is not required to choose Bun.
([Pi documentation](https://pi.dev/docs/latest),
[Pi product overview](https://pi.dev/))

We do not copy Pi's choice to leave sub-agents and other orchestration entirely
to user-built extensions. We also do not make Pi's TypeScript extension API or
npm/git package format an Agul compatibility target.

The Agul split is more explicit: Agul owns the small model loop, terminal,
sessions, usage, and ARI; Agulater owns installation, updates, package
resolution, and preparation; AgentKube supplies optional Skills, Plugins, and
specialist packages. ARI gives delegated sessions one versioned runtime
boundary, while the package and Plugin formats define the other integration
seams. Minimal Agul still works without Agulater or AgentKube.

## Claude Code

Claude Code is a coding agent available across terminal and other surfaces.
The relevant references are its direct native installers and first-run login,
plus the clear separation between persistent instructions, on-demand Skills,
isolated subagents, external-tool connections, lifecycle hooks, and Plugins.
Its documentation also treats Plugins as a distribution layer that can bundle
several extension types rather than as another model runtime.
([Claude Code overview](https://code.claude.com/docs/en/overview),
[Claude Code extension overview](https://code.claude.com/docs/en/features-overview))

We do not copy the full Claude Code product surface, put hooks and every
integration into Agul's core, or assume a Claude account and Anthropic-only
execution model. Agul also does not need one CLI to own the runtime, package
manager, extension catalog, and multi-agent implementation at once.

For the Agul projects, the practical lesson is that installation should be a
product path rather than a language-runtime exercise. Published Agul and
Agulater releases should offer direct platform installers; Rust and Bun remain
development implementation details. Extension concerns stay outside the
minimal Agul loop unless they are required to load and run a prepared package.

## OpenAI Codex CLI

Codex CLI provides a focused repository loop in the terminal: inspect and edit
files, run installed tools, steer an active turn, resume saved work, and use
interactive or scripted operation. Its current quickstart leads with a
standalone installer on macOS and Linux and signs users in on first run. The
same official overview exposes model and reasoning choices, context remaining,
Skills, Plugins, subagents, live Web Search, and non-interactive automation as
parts of one coherent terminal workflow.
([OpenAI Codex CLI documentation](https://learn.chatgpt.com/docs/codex/cli))

We do not copy Codex's cloud, desktop, or managed-platform architecture, and
we do not make OpenAI the only execution path. Agul's native loop also supports
DeepSeek, GLM Coding Plan, and local OpenAI-compatible endpoints; the optional
Codex engine is a separate ChatGPT-account path with an explicit tool-owner and
billing boundary.

The main reference is interaction continuity: a terminal agent should make
model choice, reasoning, context, in-flight activity, resumability, and account
mode understandable without turning the transcript into a diagnostics dump.
Agul keeps those runtime facts in its TUI, sessions, Usage Ledger, and ARI so
Agulater and AgentKube do not need to reproduce the conversation loop.

## Gemini CLI

Gemini CLI documents several installation routes and a concrete extension
lifecycle. Its extensions have a manifest and can bundle prompts, MCP servers,
custom commands, themes, hooks, subagents, and Agent Skills. The CLI exposes
install, update, enable, disable, link, and validate operations rather than
treating copied extension directories as invisible state.
([Gemini CLI installation](https://github.com/google-gemini/gemini-cli/blob/main/docs/get-started/installation.mdx),
[Gemini CLI extensions](https://github.com/google-gemini/gemini-cli/blob/main/docs/extensions/index.md),
[Gemini CLI extension reference](https://github.com/google-gemini/gemini-cli/blob/main/docs/extensions/reference.md))

We do not copy Gemini CLI's Node.js runtime requirement for ordinary users or
place extension installation inside Agul. We also do not adopt its manifest as
our package contract: Agulater packages describe prepared agent inputs, while
Agul Plugins describe runtime tool processes.

The relevant lesson belongs in Agulater: sources, versions, validation,
installation, updates, and prepared output should remain explicit and
inspectable. AgentKube can then remain a collection of optional content rather
than becoming another command-line application.

## Resulting project rules

These references lead to a small set of concrete rules for this repository:

1. A new user must be able to install and run Agul without Agulater, AgentKube,
   Bun, or Node.js.
2. A published Agulater release must have a direct platform install path;
   installing Bun is for source development, not an ordinary-user prerequisite.
3. Agul's default interaction should stay compact and responsive while making
   reasoning, tools, steering, context, usage, and session recovery visible.
4. Agulater prepares and manages non-runtime inputs. It never starts a model
   session or becomes a second agent harness.
5. AgentKube publishes optional, independently understandable extension
   content. It never becomes another CLI.
6. Runtime tools use Agul's Plugin contract, and delegated sessions use ARI,
   so the three repositories can evolve separately without relying on private
   coupling.

The current responsibility split is documented in
[Architecture](architecture/README.md), and the package boundaries are in
[Packages](packages/README.md).
