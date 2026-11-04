# Graphics Environment Manager

The standalone home of the canonical **Ablation native workbench**, reusable as a graphical environment for **your project + your AI agent**.

## Origin and naming

**Graphics Environment Manager did not originate with this repository.** The name honors the original **Graphics Environment Manager**, developed by **Digital Research** with **Lee Jay Lorenzen** and first released on **February 28, 1985**. [Gary Kildall](https://en.wikipedia.org/wiki/Gary_Kildall) oversaw its creation at Digital Research. [Dorothy McEwen Kildall](https://en.wikipedia.org/wiki/Dorothy_McEwen_Kildall) co-founded Digital Research and managed the company's marketing and daily operations.

This is a separate, modern application derived from the Ablation Graphics Environment Manager workbench. It is **not** the original Digital Research desktop, an emulator for it, or a continuation of its source code. No original Digital Research source code is included here, and no affiliation with or endorsement by Digital Research or the Kildall family is implied.

Historical references:

- [Graphics Environment Manager (desktop environment)](https://en.wikipedia.org/wiki/GEM_(desktop_environment)) — the original operating environment, its history, VDI, AES, and desktop.
- [Gary Kildall](https://en.wikipedia.org/wiki/Gary_Kildall) — Digital Research co-founder and the person who oversaw the original Graphics Environment Manager's creation.
- [Dorothy McEwen Kildall](https://en.wikipedia.org/wiki/Dorothy_McEwen_Kildall) — microcomputer industry pioneer and Digital Research co-founder.

<details>
<summary><strong>About this repository</strong></summary>

**This repository contains the actual Ablation native workbench—not a redesigned or simplified interface.** The canonical master and visual/functional template is the `gem-lab` distribution in [Ablation](https://github.com/Ablation-Tool/ablation). Its native interface, views, preferences, charts, terminal, session protocol, and graphical execution engine have been copied into this standalone repository.

On Linux, the default interface is the same native **GTK3/VTE workbench** used by Ablation. Native Windows and macOS use the master's Tk interface with ConPTY or POSIX PTY support. The in-app Ablation branding and design remain intact; the supplied red image is used only for the window and desktop-installer icons.

Use the repository as a build template for any project that needs a native dashboard beside its own AI agent. Select a directory, connect your existing agent CLI, and adapt the shared event model and domain tools to your workflow. The application does not supply a model, credentials, or a simulated chatbot, and launching the interface does not require installing Ablation's analysis engine.

Standalone changes are limited to packaging, version metadata, documentation, the supplied PNG/ICO/ICNS application icons, and the matching icon-test expectations. The canonical interface remains Ablation's master implementation.

</details>

<details>
<summary><strong>What the master workbench includes</strong></summary>

- Native GTK notebook, tree, disclosure, action, and VTE terminal model on Linux, with the master's Tk fallback on other platforms.
- Independent Lab tabs with separate sessions, selections, bookmarks, event histories, and agent terminals.
- Shared human/agent selection through `state.json` and revision-checked `gem begin` operations.
- Append-only `events.jsonl` history with file locking, stable identities, and atomic state writes.
- Search, status filters, bookmarks, breadcrumbs, node details, follow-up actions, and review states.
- Rings, Treemap, and native graphical scene views with shared selection.
- Spatial IR, Cairo/SVG previews, VDI metafiles, deterministic verification, and replayable runs.
- Persistent workspace layouts, terminal fonts, ANSI palettes, accessibility palettes, and graphical preferences.
- Kimi, Claude, Codex, or another interactive agent through `--agent` and `--agent-command`.
- Local file/folder drag-and-drop into the embedded terminal without automatically running the dropped paths.
- Native Linux, Windows, and macOS packaging sources.

See [WORKBENCH.md](WORKBENCH.md) for the master's workbench guide and [GEM.md](GEM.md) for graphical execution and replay details.

</details>

<details>
<summary><strong>Examples: Ablation and Cerotto</strong></summary>

These projects show the native graphical-environment-plus-agent approach in different domains:

- **[Ablation](https://github.com/Ablation-Tool/ablation)** — the canonical master used here: an agent-guided reverse-engineering workbench with shared investigation state, charts, evidence, and an embedded agent terminal.
- **[Cerotto](https://github.com/Ablation-Tool/cerotto)** — a native forensic workbench for investigating attacks involving autonomous AI agents and sandbox escapes, with timelines, defense events, encrypted-vault activity, accessible-volume charts, and an embedded agent.

They are examples of the broader approach, not dependencies of this standalone repository.

</details>

<details>
<summary><strong>Dependencies and installation</strong></summary>

Requirements: **Python 3.10+ with Tkinter**. The standard `python -m pip install -e .` installs `pyte`, `tkinterdnd2`, and `pywinpty` on native Windows. Linux's preferred GTK/VTE interface also uses system GTK and Cairo packages.

### Windows

1. Install Python from [python.org](https://www.python.org/downloads/windows/) with **tcl/tk and IDLE** enabled.
2. In PowerShell, run `py -m venv .venv` and `.venv\Scripts\Activate.ps1`.
3. Run `python -m pip install -e .`. `pywinpty` is installed automatically for the native ConPTY terminal.
4. Launch with `gem launch --toolkit tk --agent kimi`.

The native offline Windows packaging currently validates Python 3.11 x64; source installation supports Python 3.10 or newer.

### macOS

1. Install a Python 3.10+ build with Tkinter, such as the [python.org macOS installer](https://www.python.org/downloads/macos/). Homebrew users may need the `python-tk` formula matching their Python version.
2. Run `python3 -m venv .venv` and `source .venv/bin/activate`.
3. Run `python -m pip install -e .`. The embedded terminal uses POSIX PTY support; `pywinpty` is excluded by its Windows marker.
4. Launch with `gem launch --toolkit tk --agent kimi`.

The `packaging/` directory also contains the master's offline app-bundle installer. It uses the supplied ICNS icon.

### Linux

Install the native GTK/VTE and Tk dependencies on Ubuntu or Debian:

```bash
sudo apt install python3-venv python3-tk python3-gi python3-cairo python3-gi-cairo gir1.2-gtk-3.0 gir1.2-vte-2.91
```

Then install the standalone package with access to the system GTK bindings:

```bash
git clone https://github.com/Ablation-Tool/graphics-environment-manager.git
cd graphics-environment-manager
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install -e .
gem launch --agent kimi
```

Use `--toolkit tk` to select the master's Tk interface explicitly or `--toolkit gtk` to require GTK/VTE. Linux packages place the supplied PNG in the desktop icon theme; Windows packages use the ICO variant.

</details>

<details>
<summary><strong>Launch and agent examples</strong></summary>

Open the native target chooser:

```bash
gem launch --agent kimi
```

Open a specific project directory with a persistent session outside that directory:

```bash
gem lab /path/to/project --session /path/to/project-session --agent kimi
```

Use another agent or disable agent embedding:

```bash
gem lab /path/to/project --session /path/to/project-session --agent claude
gem lab /path/to/project --session /path/to/project-session --agent codex
gem lab /path/to/project --session /path/to/project-session --agent-command 'your-agent --flag'
gem lab /path/to/project --session /path/to/project-session --no-agent
```

The agent keeps its own authentication, tools, permissions, and provider policy. The workbench shares `GEM_SESSION`, `GEM_STATE`, `GEM_EVENTS`, `GEM_CLI`, `GEM_WORKSPACE`, `GEM_TARGET`, and `GEM_ROOT_ID` with the embedded terminal.

</details>

<details>
<summary><strong>Shared workbench protocol</strong></summary>

```bash
gem state --session /path/to/project-session
gem tree --session /path/to/project-session
gem begin --session /path/to/project-session \
  --expected-id SELECTED_ID \
  --expected-revision REVISION

gem emit --session /path/to/project-session \
  --id observation:example \
  --parent PARENT_ID \
  --type observation \
  --label 'Inspected result' \
  --status in_progress \
  --evidence analysis/result.txt \
  --note 'Record the inspected output and remaining uncertainty'
```

The human selects a node; the agent reads the exact selection and revision, begins work with `gem begin`, performs real work, and records supported results with `gem emit` or `gem emit-many`. Stale selections and revisions are rejected rather than silently overwritten.

</details>

<details>
<summary><strong>Graphical execution and replay</strong></summary>

The master's graphical execution commands are included:

```bash
gem demo --output runs/house
gem replay runs/house
gem verify runs/house/scene.json --vdi
gem render runs/house/scene.json --output house.svg
```

Generate and repair a scene through an external agent:

```bash
gem solve 'Draw a house with a touching roof, a contained door, and symmetric windows.' \
  --agent-command 'kimi -p {prompt}' \
  --attempts 3 --timeout 120 --output runs/agent-house
```

SVG and VDI use the Python standard library. PNG and native graphical views require the optional Cairo/GTK bindings supplied by the Linux system packages above.

</details>

<details>
<summary><strong>Canonical sources and validation</strong></summary>

- `gem/gtk_app.py` — the actual native Linux workbench.
- `gem/app.py` and `metrix/desktop.py` — the master's Tk and embedded-terminal implementation.
- `gem/events.py` — authoritative sessions, selections, and append-only events.
- `gem/model.py`, `gem/geometry.py`, `gem/runner.py`, and `gem/vdi.py` — graphical execution, verification, and replay.
- `stress/` — the master's core, native, desktop-input, installer, and platform validation suites.
- `packaging/` — native Linux, Windows, and macOS packaging sources.

Run the core validation from the repository root:

```bash
python stress/run_stress.py
python stress/native_stress.py
python stress/gem_stress.py
```

For repeated GUI testing, use `stress/nested_x11.sh` instead of opening test windows on the live desktop. Windows and macOS still require their native validation environments.

</details>

<details>
<summary><strong>License and attribution</strong></summary>

The modern workbench is GPL-3.0-or-later, matching the Ablation master from which it is copied. Additional upstream notices for GNOME Baobab, Vanilla Framework icons, Solarized, and related components are preserved in [UPSTREAM-NOTICE](UPSTREAM-NOTICE) and `licenses/`.

See [LICENSE](LICENSE), [NOTICE](NOTICE), and [UPSTREAM-NOTICE](UPSTREAM-NOTICE).

</details>
