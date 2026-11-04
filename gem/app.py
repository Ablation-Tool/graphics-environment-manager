from collections import Counter, defaultdict
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from .agent_bridge import prepare_agent_command
from .environment import configure_environment
from .session import STATUSES
from .terminal import TerminalPanel


STATUS_LABELS = {
    "not_started": "Not started",
    "in_progress": "In progress",
    "blocked": "Blocked",
    "done": "Done",
}


class DashboardApp:
    def __init__(self, root, session, command=None, workspace=None):
        self.root = root
        self.session = session
        self.workspace = Path(workspace).expanduser().resolve() if workspace else session.workspace
        if not self.workspace.is_dir():
            raise ValueError(f"agent workspace is not a directory: {self.workspace}")
        self.environment = configure_environment(session, self.workspace)
        self.command, self.agent_startup_prompt = prepare_agent_command(command, session)
        self.events = {}
        self.children = {}
        self.selected_id = session.root_id
        self.restoring_selection = False
        self.closed = False
        self.refresh_after_id = None
        self.signature = None
        self.search_variable = tk.StringVar()
        self.status_variable = tk.StringVar(value="All statuses")
        self.starred_variable = tk.BooleanVar(value=False)
        self.agent_variable = tk.StringVar(value="Agent: not configured")
        self.summary_variable = tk.StringVar()
        self.count_variables = {status: tk.StringVar(value="0") for status in STATUSES}
        self.detail_variable = tk.StringVar()
        self.root.title(f"GEM · {session.project}")
        self.root.geometry("1500x900")
        self.root.minsize(900, 560)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.configure_theme()
        self.build_header()
        self.build_workspace()
        self.build_footer()
        self.root.bind("<Control-f>", lambda event: self.search.focus_set())
        self.root.bind("<F5>", lambda event: self.reload())
        self.reload()
        self.after_refresh()

    def configure_theme(self):
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Header.TFrame", background="#17212b")
        style.configure("Header.TLabel", background="#17212b", foreground="#dce6ef")
        style.configure("Brand.TLabel", background="#17212b", foreground="#79c0ff", font=("TkDefaultFont", 20, "bold"))
        style.configure("Project.TLabel", background="#17212b", foreground="#ffffff", font=("TkDefaultFont", 14, "bold"))
        style.configure("Card.TFrame", background="#eef2f6", relief="solid", borderwidth=1)
        style.configure("Card.TLabel", background="#eef2f6", foreground="#52606d")
        style.configure("CardValue.TLabel", background="#eef2f6", foreground="#17212b", font=("TkDefaultFont", 17, "bold"))
        style.configure("Treeview", rowheight=28)
        style.configure("Treeview.Heading", font=("TkDefaultFont", 10, "bold"))

    def build_header(self):
        header = ttk.Frame(self.root, style="Header.TFrame", padding=(16, 12))
        header.pack(fill="x")
        ttk.Label(header, text="GEM", style="Brand.TLabel").pack(side="left")
        title = ttk.Frame(header, style="Header.TFrame", padding=(18, 0))
        title.pack(side="left", fill="x", expand=True)
        ttk.Label(title, text=self.session.project, style="Project.TLabel").pack(anchor="w")
        ttk.Label(title, text="Graphics Environment Manager · reusable agent dashboard", style="Header.TLabel").pack(anchor="w")
        ttk.Label(header, textvariable=self.agent_variable, style="Header.TLabel").pack(side="right")

    def build_workspace(self):
        outer = ttk.Frame(self.root, padding=(12, 10, 12, 0))
        outer.pack(fill="both", expand=True)
        cards = ttk.Frame(outer)
        cards.pack(fill="x", pady=(0, 10))
        for index, status in enumerate(STATUSES):
            card = ttk.Frame(cards, style="Card.TFrame", padding=(12, 7))
            card.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 8, 0))
            ttk.Label(card, textvariable=self.count_variables[status], style="CardValue.TLabel").pack(anchor="w")
            ttk.Label(card, text=STATUS_LABELS[status], style="Card.TLabel").pack(anchor="w")
            cards.columnconfigure(index, weight=1)
        self.panes = ttk.Panedwindow(outer, orient="horizontal")
        self.panes.pack(fill="both", expand=True)
        dashboard = ttk.Frame(self.panes, padding=(0, 0, 8, 0))
        self.panes.add(dashboard, weight=3)
        self.build_dashboard(dashboard)
        agent_frame = ttk.Frame(self.panes, padding=(8, 0, 0, 0))
        self.panes.add(agent_frame, weight=2)
        ttk.Label(agent_frame, text="Your AI agent", font=("TkDefaultFont", 11, "bold")).pack(anchor="w", pady=(0, 6))
        self.terminal = TerminalPanel(
            agent_frame, self.workspace, self.command, self.agent_variable.set,
            startup_text=self.agent_startup_prompt,
        )
        self.terminal.pack(fill="both", expand=True)

    def build_dashboard(self, parent):
        filters = ttk.Frame(parent)
        filters.pack(fill="x", pady=(0, 8))
        ttk.Label(filters, text="Search").pack(side="left")
        self.search = ttk.Entry(filters, textvariable=self.search_variable)
        self.search.pack(side="left", fill="x", expand=True, padx=8)
        self.status_box = ttk.Combobox(
            filters, textvariable=self.status_variable, state="readonly", width=15,
            values=["All statuses", *(STATUS_LABELS[status] for status in STATUSES)],
        )
        self.status_box.pack(side="left")
        ttk.Checkbutton(filters, text="Starred", variable=self.starred_variable, command=self.render_tree).pack(side="left", padx=(8, 0))
        self.search_variable.trace_add("write", lambda *_args: self.render_tree())
        self.status_variable.trace_add("write", lambda *_args: self.render_tree())
        details = ttk.Frame(parent, padding=(0, 8, 0, 0))
        details.pack(fill="x", side="bottom")
        tree_area = ttk.Frame(parent)
        tree_area.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tree_area, columns=("type", "status"), selectmode="browse")
        self.tree.heading("#0", text="Project item")
        self.tree.heading("type", text="Type")
        self.tree.heading("status", text="Status")
        self.tree.column("#0", width=430, minwidth=220, stretch=True)
        self.tree.column("type", width=90, minwidth=70, stretch=False)
        self.tree.column("status", width=120, minwidth=100, stretch=False)
        scrollbar = ttk.Scrollbar(tree_area, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        ttk.Label(details, textvariable=self.detail_variable, font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        self.details = tk.Text(details, height=8, wrap="word", relief="flat", background="#f3f5f7", padx=8, pady=8)
        self.details.pack(fill="x", pady=(4, 6))
        self.details.configure(state="disabled")
        actions = ttk.Frame(details)
        actions.pack(fill="x")
        ttk.Button(actions, text="Open in agent", command=self.open_in_agent).pack(side="left")
        self.star_button = ttk.Button(actions, text="Star", command=self.toggle_star)
        self.star_button.pack(side="left", padx=6)
        ttk.Button(actions, text="Mark done", command=self.mark_done).pack(side="left")

    def build_footer(self):
        footer = ttk.Frame(self.root, padding=(12, 8))
        footer.pack(fill="x")
        ttk.Label(footer, textvariable=self.summary_variable).pack(side="left")
        ttk.Label(footer, text="Ctrl+F search · F5 refresh").pack(side="left", padx=16)
        ttk.Button(footer, text="Refresh", command=self.reload).pack(side="right")

    def reload(self):
        try:
            self.events = self.session.events_by_id()
            state = self.session.current_state()
            self.selected_id = state["selected_id"]
            self.starred_ids = set(state["starred_ids"])
            self.children = defaultdict(list)
            for event in self.events.values():
                self.children[event["parent_id"]].append(event)
            for siblings in self.children.values():
                siblings.sort(key=lambda event: (event["type"] != "milestone", event["label"].casefold(), event["id"]))
            self.signature = self.current_signature()
            self.render_tree()
            self.update_summary()
            self.show_details(state["selected"])
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            self.summary_variable.set(f"Unable to load GEM state: {error}")

    def current_signature(self):
        return tuple((path.stat().st_mtime_ns, path.stat().st_size) for path in (self.session.events_path, self.session.state_path))

    def after_refresh(self):
        if self.closed:
            return
        try:
            if self.signature != self.current_signature():
                self.reload()
        except OSError:
            pass
        self.refresh_after_id = self.root.after(750, self.after_refresh)

    def matching_items(self):
        terms = self.search_variable.get().casefold().split()
        selected_status = self.status_variable.get()
        status = next((key for key, label in STATUS_LABELS.items() if label == selected_status), None)
        matches = set()
        for id, event in self.events.items():
            haystack = json.dumps(event, ensure_ascii=False).casefold()
            direct = not terms or all(term in haystack for term in terms)
            if status is not None and event["status"] != status:
                direct = False
            if self.starred_variable.get() and id not in self.starred_ids:
                direct = False
            if direct:
                matches.add(id)
        visible = set(matches)
        for id in matches:
            current = self.events[id]["parent_id"]
            while current is not None:
                visible.add(current)
                current = self.events[current]["parent_id"]
        return visible

    def render_tree(self):
        if not hasattr(self, "tree") or not self.events:
            return
        selected = self.selected_id
        self.restoring_selection = True
        self.tree.delete(*self.tree.get_children())
        visible = self.matching_items()

        def insert(parent_id, parent=""):
            for event in self.children.get(parent_id, []):
                id = event["id"]
                if id not in visible:
                    continue
                label = ("★ " if id in self.starred_ids else "") + event["label"]
                self.tree.insert(
                    parent, "end", iid=id, text=label, open=True,
                    values=(event["type"].replace("_", " ").title(), STATUS_LABELS[event["status"]]),
                )
                insert(id, id)

        insert(None)
        if selected in visible and self.tree.exists(selected):
            self.tree.selection_set(selected)
            self.tree.see(selected)
        self.restoring_selection = False
        self.summary_variable.set(f"{len(visible)} of {len(self.events)} items shown")

    def update_summary(self):
        counts = Counter(event["status"] for event in self.events.values())
        for status in STATUSES:
            self.count_variables[status].set(str(counts[status]))

    def on_select(self, _event=None):
        if self.restoring_selection:
            return
        selection = self.tree.selection()
        if not selection:
            return
        try:
            state = self.session.select(selection[0])
            self.selected_id = selection[0]
            self.starred_ids = set(state["starred_ids"])
            self.signature = self.current_signature()
            self.show_details(state["selected"])
        except (OSError, ValueError) as error:
            self.summary_variable.set(str(error))

    def show_details(self, event):
        self.detail_variable.set(f"{event['label']} · {event['id']}")
        lines = [
            f"Type: {event['type']}    Status: {STATUS_LABELS[event['status']]}    Source: {event['source']}",
            f"Parent: {event['parent_id'] or '—'}",
            "",
            event["details"] or "No details recorded.",
        ]
        if event["metadata"]:
            lines.extend(["", "Metadata:", json.dumps(event["metadata"], indent=2, ensure_ascii=False)])
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", "\n".join(lines))
        self.details.configure(state="disabled")
        self.star_button.configure(text="Unstar" if event["id"] in self.starred_ids else "Star")

    def selected_event(self):
        event = self.events.get(self.selected_id)
        if event is None:
            raise ValueError("Select a dashboard item first")
        return event

    def open_in_agent(self):
        try:
            event = self.selected_event()
            prompt = (
                f"Work on the currently selected GEM item {event['id']}: {event['label']}. "
                "Read the latest selection with gem state, begin it with the exact revision, "
                "inspect the actual project, and record concrete progress in the dashboard."
            )
            self.terminal.submit_agent_request(prompt)
        except ValueError as error:
            self.summary_variable.set(str(error))

    def toggle_star(self):
        try:
            event = self.selected_event()
            state = self.session.set_starred(event["id"], event["id"] not in self.starred_ids)
            self.starred_ids = set(state["starred_ids"])
            self.signature = self.current_signature()
            self.render_tree()
            self.show_details(event)
        except ValueError as error:
            self.summary_variable.set(str(error))

    def mark_done(self):
        try:
            event = self.selected_event()
            updated = self.session.set_status(event["id"], "done", source="human")
            self.reload()
            self.show_details(updated)
        except ValueError as error:
            self.summary_variable.set(str(error))

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.refresh_after_id is not None:
            try:
                self.root.after_cancel(self.refresh_after_id)
            except tk.TclError:
                pass
        self.terminal.stop()
        try:
            self.root.destroy()
        except tk.TclError:
            pass


def run_desktop(session, command=None, workspace=None):
    root = tk.Tk()
    app = DashboardApp(root, session, command, workspace)
    try:
        root.mainloop()
    finally:
        app.close()
    return 0
