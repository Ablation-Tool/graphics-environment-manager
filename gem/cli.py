import argparse
import json
import os
from pathlib import Path
import shutil
import sys

from . import __version__
from .agent_bridge import parse_agent_command
from .session import NODE_TYPES, ROOT_ID, SOURCES, STATUSES, Session, write_default_config


def resolved(value):
    return Path(value).expanduser().resolve()


def session_path(value=None):
    return resolved(value or os.environ.get("GEM_SESSION", ".gem"))


def detect_agent():
    for name in ("kimi", "claude", "codex"):
        executable = shutil.which(name)
        if executable:
            return [executable]
    return None


def print_json(value):
    print(json.dumps(value, indent=2, ensure_ascii=False))


def command_init(args):
    workspace = resolved(args.workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    if not workspace.is_dir():
        raise ValueError(f"workspace is not a directory: {workspace}")
    config = write_default_config(workspace)
    session = Session(workspace / ".gem", workspace)
    print(f"Initialized {session.project}")
    print(f"Configuration: {config}")
    print(f"Session: {session.root}")
    print(f"Next: gem open {workspace} --agent kimi")
    return 0


def command_open(args):
    workspace = resolved(args.workspace)
    if not workspace.is_dir():
        raise ValueError(f"workspace is not a directory: {workspace}; run gem init first")
    session = Session(resolved(args.session) if args.session else workspace / ".gem", workspace)
    if args.no_agent:
        command = None
    elif args.agent_command or args.agent:
        command = parse_agent_command(args.agent_command or args.agent)
    else:
        command = detect_agent()
    from .app import run_desktop
    return run_desktop(session, command, resolved(args.agent_workspace) if args.agent_workspace else workspace)


def command_state(args):
    print_json(Session(session_path(args.session)).current_state())
    return 0


def command_tree(args):
    session = Session(session_path(args.session))
    events = session.events()
    if args.json:
        print_json(events)
        return 0
    children = {}
    for event in events:
        children.setdefault(event["parent_id"], []).append(event)
    pending = [(None, 0)]
    while pending:
        parent_id, depth = pending.pop()
        descendants = children.get(parent_id, [])
        for event in descendants:
            print(f"{'  ' * depth}{event['label']} [{event['status']}] ({event['id']})")
        for event in reversed(descendants):
            pending.append((event["id"], depth + 1))
    return 0


def command_begin(args):
    state = Session(session_path(args.session)).begin_selected_work(
        args.expected_id, args.expected_revision, args.details,
    )
    print_json(state)
    return 0


def command_emit(args):
    metadata = json.loads(args.metadata)
    if not isinstance(metadata, dict):
        raise ValueError("--metadata must be a JSON object")
    event = Session(session_path(args.session)).emit(
        args.id, args.parent, args.type, args.label, args.status,
        args.source, args.details, metadata,
    )
    print_json(event)
    return 0


def command_done(args):
    event = Session(session_path(args.session)).set_status(args.id, "done", args.source, args.details)
    print_json(event)
    return 0


def command_select(args):
    print_json(Session(session_path(args.session)).select(args.id))
    return 0


def add_session(parser):
    parser.add_argument("--session", "-s", help="session directory (default: $GEM_SESSION or .gem)")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="gem",
        description="Graphics Environment Manager — a reusable dashboard for you and your AI agent",
    )
    parser.add_argument("--version", action="version", version=f"GEM {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    command = commands.add_parser("init", help="create a sample gem.json and initialize a project session")
    command.add_argument("workspace", nargs="?", default=".")
    command.set_defaults(function=command_init)

    command = commands.add_parser("open", help="open the native dashboard with an optional embedded agent")
    command.add_argument("workspace", nargs="?", default=".")
    command.add_argument("--session", help="session directory (default: WORKSPACE/.gem)")
    command.add_argument("--agent-workspace", help="different working directory for the agent")
    agents = command.add_mutually_exclusive_group()
    agents.add_argument("--agent", help="interactive agent executable, such as kimi, claude, or codex")
    agents.add_argument("--agent-command", help="complete interactive agent command")
    agents.add_argument("--no-agent", action="store_true", help="open only the dashboard")
    command.set_defaults(function=command_open)

    command = commands.add_parser("state", help="print the selected dashboard item")
    add_session(command)
    command.set_defaults(function=command_state)

    command = commands.add_parser("tree", help="print current dashboard items")
    add_session(command)
    command.add_argument("--json", action="store_true")
    command.set_defaults(function=command_tree)

    command = commands.add_parser("select", help="select an item by ID")
    add_session(command)
    command.add_argument("id")
    command.set_defaults(function=command_select)

    command = commands.add_parser("begin", help="begin selected work if its ID and revision are unchanged")
    add_session(command)
    command.add_argument("--expected-id", required=True)
    command.add_argument("--expected-revision", required=True, type=int)
    command.add_argument("--details")
    command.set_defaults(function=command_begin)

    command = commands.add_parser("emit", help="add or update a dashboard item")
    add_session(command)
    command.add_argument("--id", required=True)
    command.add_argument("--parent", default=ROOT_ID)
    command.add_argument("--type", required=True, choices=NODE_TYPES)
    command.add_argument("--label", required=True)
    command.add_argument("--status", default="not_started", choices=STATUSES)
    command.add_argument("--source", default="agent", choices=SOURCES)
    command.add_argument("--details", default="")
    command.add_argument("--metadata", default="{}", help="JSON object for your own fields")
    command.set_defaults(function=command_emit)

    command = commands.add_parser("done", help="mark an item done")
    add_session(command)
    command.add_argument("id")
    command.add_argument("--source", default="human", choices=SOURCES)
    command.add_argument("--details")
    command.set_defaults(function=command_done)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.function(args)
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"gem: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
