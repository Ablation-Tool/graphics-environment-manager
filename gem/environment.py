import os
from pathlib import Path
import sys


def configure_environment(session, workspace=None):
    workspace = Path(workspace or session.workspace).expanduser().resolve()
    values = {
        "GEM_SESSION": str(session.root),
        "GEM_STATE": str(session.state_path),
        "GEM_EVENTS": str(session.events_path),
        "GEM_CLI": str(session.cli_path),
        "GEM_WORKSPACE": str(workspace),
        "GEM_PROJECT": session.project,
        "GEM_ROOT_ID": session.root_id,
        "GEM_CONFIG": str(session.workspace / "gem.json"),
        "TERM": "xterm-256color",
        "COLORTERM": "truecolor",
    }
    os.environ.update(values)
    path = os.environ.get("PATH", "")
    for directory in (str(Path(sys.executable).parent), str(session.cli_path.parent)):
        if directory not in path.split(os.pathsep):
            path = directory + (os.pathsep + path if path else "")
    os.environ["PATH"] = path
    package_root = str(Path(__file__).resolve().parent.parent)
    os.environ["PYTHONPATH"] = package_root + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else "")
    return os.environ.copy()
