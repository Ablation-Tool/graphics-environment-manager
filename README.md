# Graphics Environment Manager (GEM)

A standalone native dashboard and agent environment for **your project + your AI agent**.

This is GEM's own application repository, not an Ablation submodule, add-on, or subdirectory. Derived from the Ablation GEM workbench, it pairs a reusable live project dashboard with the interactive agent CLI you already use. It does not require Ablation and does not include a model, API keys, or a simulated chatbot.

## What you get

- A native split workbench: project items on the left, a real agent terminal on the right.
- Milestones, tasks, and notes defined in a small `gem.json` file.
- Search, status filters, stars, item details, progress cards, and one-click handoff to the agent.
- Shared selection and persistent state, so the agent can work on the exact item the human selected.
- An append-only event history with atomic state writes, file locking, stable IDs, and stale-selection checks.
- Kimi, Claude, Codex, or any other interactive CLI through `--agent-command`.
- A dashboard that remains useful with no agent installed or configured.

## Quick start

Requirements: Python 3.10+ with Tkinter. Linux, macOS, and Windows are supported by the implementation; Linux uses a POSIX terminal and native Windows uses ConPTY through `pywinpty`.

```bash
git clone https://github.com/Ablation-Tool/graphics-environment-manager.git
cd graphics-environment-manager
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -e .
gem init my-project
cd my-project
gem open . --agent kimi
```

On Ubuntu/Debian, Tkinter is available from the `python3-tk` system package. Native Windows agent support needs the optional Windows dependency:

```powershell
python -m pip install -e ".[windows]"
```

Optional local file/folder drag-and-drop into the agent terminal:

```bash
python -m pip install -e ".[drop]"
```

Dropped paths are quoted and inserted without pressing Enter, so you review the command before running it.

## Use another agent

```bash
gem open . --agent claude
gem open . --agent codex
gem open . --agent /path/to/your-agent
gem open . --agent-command 'your-agent --interactive --flag'
gem open . --no-agent
```

With no explicit option, GEM looks for `kimi`, `claude`, then `codex`. It never silently substitutes a model or provider. Authentication, tool permissions, provider policy, and agent behavior stay under your chosen CLI's control.

## Make it yours

Edit `gem.json` before running `gem init`, or replace the generated file in a new project:

```json
{
  "schema_version": 1,
  "name": "Website redesign",
  "description": "Design and ship the new documentation site.",
  "items": [
    {
      "id": "milestone:launch",
      "type": "milestone",
      "label": "Launch",
      "details": "The first public release."
    },
    {
      "id": "task:navigation",
      "parent_id": "milestone:launch",
      "type": "task",
      "label": "Build navigation",
      "status": "in_progress",
      "details": "Responsive navigation with keyboard support.",
      "metadata": {
        "owner": "casey",
        "priority": "high",
        "issue": 42
      }
    },
    {
      "id": "note:decision",
      "type": "note",
      "label": "Use the existing design system",
      "details": "Avoid introducing another component library."
    }
  ]
}
```

Types are `project`, `milestone`, `task`, and `note`. Statuses are `not_started`, `in_progress`, `blocked`, and `done`. Item IDs must be unique and contain no whitespace. Declare a parent before referring to it. `metadata` accepts arbitrary JSON objects for your own fields.

**`gem.json` seeds a new session.** Once `.gem/events.jsonl` exists, the event history is authoritative; editing the seed file does not overwrite agent or human progress. Add items through `gem emit`, or remove `.gem/` only when you intentionally want a fresh dashboard.

The dashboard layout and reusable behavior live in `gem/app.py`. The terminal bridge is in `gem/terminal.py`, and the project/event model is in `gem/session.py`.

## Human + agent workflow

1. Select a task in the dashboard.
2. Click **Open in agent**, or ask the agent to work on the selected item.
3. The agent reads `gem state` and receives the selected ID and revision.
4. It calls `gem begin` with those exact values, performs real work in your project, and records progress with `gem emit`.
5. The dashboard notices the event/state changes and refreshes automatically.

The agent receives these environment variables:

| Variable | Purpose |
| --- | --- |
| `GEM_WORKSPACE` | Actual working directory for the agent |
| `GEM_SESSION` | Dashboard session directory |
| `GEM_CLI` | Session-local GEM executable wrapper |
| `GEM_STATE` | Current selection JSON |
| `GEM_EVENTS` | Append-only dashboard history |
| `GEM_PROJECT` | Project name |
| `GEM_ROOT_ID` | Parent ID for top-level items |
| `GEM_CONFIG` | Seed configuration path |

A generated `.gem/AGENTS.md` explains the same protocol to the embedded agent.

## CLI

```bash
gem state --session .gem
gem tree --session .gem
gem tree --session .gem --json

gem begin --session .gem \
  --expected-id task:navigation \
  --expected-revision 3

gem emit --session .gem \
  --id task:mobile-nav \
  --parent milestone:launch \
  --type task \
  --label 'Implement mobile navigation' \
  --status in_progress \
  --details 'Keyboard behavior is implemented; narrow-screen review remains.' \
  --metadata '{"owner":"agent","issue":43}'

gem done task:mobile-nav --session .gem \
  --source agent \
  --details 'Verified keyboard and narrow-screen behavior.'
```

Inside the embedded terminal, `--session "$GEM_SESSION"` and the session-local `"$GEM_CLI"` wrapper are available. On Windows, use `%GEM_SESSION%` and `%GEM_CLI%`.

`gem begin` is a compare-and-commit operation: if the human changes the selection or its revision first, the command fails and the agent must read the latest state. It does not lock project files or prevent the human from continuing to use the dashboard.

## Session files

```text
my-project/
├── gem.json             # Project branding and seed items
└── .gem/
    ├── AGENTS.md        # Generated agent protocol
    ├── bin/gem          # Agent-facing CLI wrapper
    ├── session.json     # Workspace identity
    ├── events.jsonl     # Authoritative append-only item history
    └── state.json       # Current selection, stars, and revision
```

Keep `.gem/` out of version control if it is personal working state, or commit it deliberately if your team wants shared dashboard history. The supplied `.gitignore` excludes it.

## Scope

GEM supplies the environment and integration, not intelligence or domain-specific tools. Your agent does the work; your configuration defines the dashboard. This first template deliberately leaves out Ablation's reverse-engineering engine, Spatial IR, VDI renderer, and investigation-specific statuses.

## Origin and naming

**GEM did not originate with this repository.** The name honors the original **Graphics Environment Manager**, developed by **Digital Research** with **Lee Jay Lorenzen** and first released on **February 28, 1985**. [Gary Kildall](https://en.wikipedia.org/wiki/Gary_Kildall) oversaw its creation at Digital Research. [Dorothy McEwen Kildall](https://en.wikipedia.org/wiki/Dorothy_McEwen_Kildall) co-founded Digital Research and managed the company's marketing and daily operations.

This is a separate, modern application derived from the Ablation GEM workbench. It is **not** the original Digital Research GEM desktop, an emulator for it, or a continuation of its source code. No original Digital Research GEM source code is included here, and no affiliation with or endorsement by Digital Research or the Kildall family is implied.

Historical references:

- [GEM (desktop environment)](https://en.wikipedia.org/wiki/GEM_(desktop_environment)) — the original operating environment, its history, VDI, AES, and desktop.
- [Gary Kildall](https://en.wikipedia.org/wiki/Gary_Kildall) — Digital Research co-founder and the person who oversaw GEM's creation.
- [Dorothy McEwen Kildall](https://en.wikipedia.org/wiki/Dorothy_McEwen_Kildall) — microcomputer industry pioneer and Digital Research co-founder.

## License and attribution

The modern code in this repository is GPL-3.0-or-later, matching the Ablation GEM workbench from which it is derived. Historical acknowledgment of the original GEM does not change that license or imply that this repository contains the original desktop's source. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
