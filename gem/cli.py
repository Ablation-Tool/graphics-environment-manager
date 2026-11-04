from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .agent import DEFAULT_AGENT_COMMAND, solve
from .geometry import VerificationReport, verify
from .model import Scene, demo_scene
from .render import write_png, write_svg
from .runner import export_run, replay, verify_vdi, write_failed_run
from .vdi import write_metafile


def _parser():
    parser = argparse.ArgumentParser(
        prog="gem",
        description="GEM (Graphics Environment Manager): Lab, Spatial IR, VDI, and deterministic verification",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    demo = commands.add_parser("demo", help="export the verified house example")
    demo.add_argument("--output", required=True, help="new or empty run directory")

    verify_parser = commands.add_parser("verify", help="verify a Spatial IR scene")
    verify_parser.add_argument("scene", help="scene JSON path")
    verify_parser.add_argument("--vdi", action="store_true", help="also recover and verify a GEM metafile")
    verify_parser.add_argument("--json", action="store_true", help="emit machine-readable reports")

    render = commands.add_parser("render", help="render a scene to SVG, PNG, or GEM VDI")
    render.add_argument("scene", help="scene JSON path")
    render.add_argument("--output", required=True, help="output artifact path")
    render.add_argument("--format", choices=("svg", "png", "gem"), help="default: infer from output suffix")
    render.add_argument("--width", type=int, default=1200, help="SVG/PNG width in pixels")

    replay_parser = commands.add_parser("replay", help="recompute verification from run artifacts")
    replay_parser.add_argument("run", help="GEM run directory")
    replay_parser.add_argument("--json", action="store_true", help="emit the complete recomputed report")

    agent = commands.add_parser("solve", help="generate, verify, and repair a scene with an external agent")
    agent.add_argument("request", help="natural-language drawing request")
    agent.add_argument("--output", required=True, help="new or empty run directory")
    agent.add_argument("--agent-command", default=DEFAULT_AGENT_COMMAND, help="command template; {prompt} is replaced, otherwise prompt uses stdin")
    agent.add_argument("--attempts", type=int, default=3, help="total generation/repair attempts, from 1 to 10")
    agent.add_argument("--timeout", type=float, default=120, help="timeout for each agent process in seconds")
    agent.add_argument("--constraints", help="JSON file containing required constraint objects")
    agent.add_argument("--cwd", help="working directory for the external agent")

    lab = commands.add_parser("lab", help="open GEM Lab as an application inside the GEM environment")
    lab.add_argument("target", help="binary file or material directory")
    lab.add_argument("--session", required=True, help="investigation session directory")
    lab.add_argument("--workspace", help="embedded agent working directory")
    lab.add_argument("--toolkit", choices=("auto", "gtk", "tk"), default="auto")
    agents = lab.add_mutually_exclusive_group()
    agents.add_argument("--agent", help="interactive agent executable")
    agents.add_argument("--agent-command", help="complete interactive agent command")
    agents.add_argument("--no-agent", action="store_true", help="open the Lab without an embedded agent")

    state = commands.add_parser("lab-state", help="inspect unified investigation and derived spatial objects")
    state.add_argument("--session", required=True, help="investigation session directory")

    predict = commands.add_parser("predict", help="measure next-token accessible volume for the selected Lab context")
    predict.add_argument("--session", required=True, help="investigation session directory")
    predict.add_argument("--model-dir", help="local distilgpt2 model cache (default: per-user GEM data directory)")
    predict.add_argument("--thresholds", default="0.02,0.05,0.10,0.15,0.30,0.50", help="comma-separated probability thresholds")
    predict.add_argument("--json", action="store_true", help="print the complete measurement report")

    steer = commands.add_parser("steer", help="recommend a cautious next action from the current prediction and its trend")
    steer.add_argument("--session", required=True, help="investigation session directory")
    steer.add_argument("--model-dir", help="local distilgpt2 model cache (default: per-user GEM data directory)")
    steer.add_argument("--thresholds", default="0.02,0.05,0.10,0.15,0.30,0.50", help="comma-separated probability thresholds")
    steer.add_argument("--json", action="store_true", help="print the complete measurement and advisory report")

    tournament = commands.add_parser("tournament", help="attack fixed and adaptive equations plus context variants without changing policy")
    tournament.add_argument("--session", required=True, help="investigation session directory")
    tournament.add_argument("--model-dir", help="local distilgpt2 model cache (default: per-user GEM data directory)")
    tournament.add_argument("--thresholds", default="0.02,0.05,0.10,0.15,0.30,0.50", help="comma-separated probability thresholds")
    tournament.add_argument("--json", action="store_true", help="print the complete tournament report")

    landmarks = commands.add_parser("landmarks", help="fit a Procrustes similarity and export replayable landmark evidence")
    landmarks.add_argument("correspondences", help="JSON document containing a correspondences array")
    landmarks.add_argument("--session", required=True, help="investigation session directory")
    landmarks.add_argument("--allow-reflection", action="store_true", help="permit orientation-reversing orthogonal alignment")
    landmarks.add_argument("--json", action="store_true", help="print the complete alignment report")

    launch = commands.add_parser("launch", help="open GEM and choose a target inside the application")
    launch.add_argument("--toolkit", choices=("auto", "gtk", "tk"), default="auto")
    launch_agents = launch.add_mutually_exclusive_group()
    launch_agents.add_argument("--agent", help="interactive agent executable")
    launch_agents.add_argument("--agent-command", help="complete interactive agent command")
    launch_agents.add_argument("--no-agent", action="store_true")

    for name in ("state", "tree", "begin", "emit", "emit-many", "review"):
        command = commands.add_parser(name, help=f"{name} investigation state through the shared Lab protocol")
        command.add_argument("--session", default="gem-session")

    tree = commands.choices["tree"]
    tree.add_argument("--json", action="store_true")
    begin = commands.choices["begin"]
    begin.add_argument("--expected-id", required=True)
    begin.add_argument("--expected-revision", required=True, type=int)
    begin.add_argument("--note")
    emit = commands.choices["emit"]
    emit.add_argument("--id", required=True)
    emit.add_argument("--parent")
    emit.add_argument("--type", required=True, choices=("artifact", "function", "evidence", "observation", "hypothesis", "finding", "note"))
    emit.add_argument("--label", required=True)
    emit.add_argument("--status", default="not_started", choices=("not_started", "in_progress", "partial", "blocked", "reviewed", "complete_scoped", "rejected", "not_applicable"))
    emit.add_argument("--source", default="agent", choices=("system", "agent", "tool", "human"))
    emit.add_argument("--evidence", default="")
    emit.add_argument("--note", default="")
    emit.add_argument("--scope")
    commands.choices["emit-many"].add_argument("--file", required=True)
    review = commands.choices["review"]
    review.add_argument("id")
    review.add_argument("--status", required=True, choices=("partial", "blocked", "reviewed", "rejected"))
    review.add_argument("--note")
    return parser


def _print_report(report):
    print(VerificationReport(report["scene_id"], report["results"]).text())


def main(argv=None):
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "landmarks":
            from gem.events import Session
            from .host import GemLabHost

            document = json.loads(Path(arguments.correspondences).read_text(encoding="utf-8"))
            pairs = document.get("correspondences") if isinstance(document, dict) else None
            if not isinstance(pairs, list):
                raise ValueError("correspondence JSON must contain a correspondences array")
            source = [pair["source"] for pair in pairs]
            target = [pair["target"] for pair in pairs]
            result = GemLabHost(Session(arguments.session)).align_landmarks(
                source, target, allow_reflection=arguments.allow_reflection,
            )
            if arguments.json:
                print(json.dumps(result.report, indent=2, ensure_ascii=False, sort_keys=True))
            else:
                alignment = result.alignment
                print(f"Scale: {alignment.scale:.10f}")
                print(f"Angle: {alignment.angle_degrees:.6f}°")
                print(f"RMS: {alignment.rms:.6g}")
                print(f"Determinant: {alignment.determinant:.1f}")
                print(f"Run: {result.path}")
                print(f"Evidence: {result.evidence['id']}")
            return 0
        if arguments.command == "lab-state":
            from gem.events import Session
            from .host import GemLabHost

            snapshot = GemLabHost(Session(arguments.session)).snapshot()
            print(json.dumps(snapshot, indent=2, ensure_ascii=False, sort_keys=True))
            return 0
        if arguments.command == "predict":
            from gem.events import Session
            from .host import GemLabHost

            result = GemLabHost(Session(arguments.session)).measure_prediction(
                model_dir=arguments.model_dir, thresholds=arguments.thresholds,
            )
            if arguments.json:
                print(json.dumps(result.report, indent=2, ensure_ascii=False, sort_keys=True))
            else:
                for measurement in result.report["threshold_sweep"]:
                    print(
                        f"τ={measurement['tau']:.2f} "
                        f"A(S)={measurement['accessible_volume']} "
                        f"normalized={measurement['normalized_accessible_volume']:.8f}"
                    )
            if not arguments.json:
                print(f"Run: {result.path}")
                print(f"Evidence: {result.evidence['id']}")
            return 0
        if arguments.command == "steer":
            from gem.events import Session
            from .host import GemLabHost

            result = GemLabHost(Session(arguments.session)).advise_next_action(
                model_dir=arguments.model_dir, thresholds=arguments.thresholds,
            )
            advisory = result.report["advisory"]
            if arguments.json:
                print(json.dumps(result.report, indent=2, ensure_ascii=False, sort_keys=True))
            else:
                print(f"Advisory: {advisory['label']}")
                print(advisory["summary"])
                for reason in advisory["reasons"]:
                    print(f"Reason: {reason}")
                print("Allowed action categories: " + ", ".join(advisory["allowed_actions"]))
                print("Autonomous execution and permission escalation are not authorized.")
            if not arguments.json:
                print(f"Run: {result.path}")
                print(f"Evidence: {result.evidence['id']}")
            return 0
        if arguments.command == "tournament":
            from gem.events import Session
            from .host import GemLabHost

            result = GemLabHost(Session(arguments.session)).run_equation_tournament(
                model_dir=arguments.model_dir, thresholds=arguments.thresholds,
            )
            tournament = result.report["tournament"]
            if arguments.json:
                print(json.dumps(result.report, indent=2, ensure_ascii=False, sort_keys=True))
            else:
                print(f"Equation tournament: {tournament['advisory_flip_count']} advisory flips")
                for variant in tournament["variants"]:
                    largest = variant["largest_disagreement"]
                    print(
                        f"{variant['name']}: fixed={variant['fixed_advisory_mode']} "
                        f"flips={variant['advisory_flip_count']} "
                        f"largest A(0.05) delta={largest['fixed_005_delta']} "
                        f"(alpha={largest['alpha']}, beta={largest['beta']})"
                    )
                print("Sensitivity only; no equation winner is inferred without verified outcomes.")
                print(f"Run: {result.path}")
                print(f"Evidence: {result.evidence['id']}")
            return 0
        if arguments.command == "lab":
            from gem.lab_cli import main as gem_main

            command = [
                "desktop", arguments.target, "--session", arguments.session,
                "--toolkit", arguments.toolkit,
            ]
            if arguments.workspace:
                command.extend(["--workspace", arguments.workspace])
            if arguments.agent_command:
                command.extend(["--agent-command", arguments.agent_command])
            elif arguments.agent:
                command.extend(["--agent", arguments.agent])
            elif arguments.no_agent:
                command.append("--no-agent")
            return gem_main(command)
        if arguments.command == "launch":
            from gem.lab_cli import main as gem_main

            command = ["launch", "--toolkit", arguments.toolkit]
            if arguments.agent_command:
                command.extend(["--agent-command", arguments.agent_command])
            elif arguments.agent:
                command.extend(["--agent", arguments.agent])
            elif arguments.no_agent:
                command.append("--no-agent")
            return gem_main(command)
        if arguments.command in {"state", "tree", "begin", "emit", "emit-many", "review"}:
            from gem.lab_cli import main as gem_main

            command = [arguments.command, "--session", arguments.session]
            if arguments.command == "tree" and arguments.json:
                command.append("--json")
            elif arguments.command == "begin":
                command.extend([
                    "--expected-id", arguments.expected_id,
                    "--expected-revision", str(arguments.expected_revision),
                ])
                if arguments.note is not None:
                    command.extend(["--note", arguments.note])
            elif arguments.command == "emit":
                command.extend(["--id", arguments.id, "--type", arguments.type, "--label", arguments.label])
                for name in ("parent", "status", "source", "evidence", "note", "scope"):
                    value = getattr(arguments, name)
                    if value is not None:
                        command.extend([f"--{name}", str(value)])
            elif arguments.command == "emit-many":
                command.extend(["--file", arguments.file])
            elif arguments.command == "review":
                command.extend([arguments.id, "--status", arguments.status])
                if arguments.note is not None:
                    command.extend(["--note", arguments.note])
            return gem_main(command)
        if arguments.command == "demo":
            result = export_run(demo_scene(), arguments.output, trajectory=[{
                "sequence": 1, "kind": "builtin_demo", "outcome": "exported",
            }])
            _print_report(result.source.to_dict())
            print(f"VDI: {'PASS' if result.vdi.passed else 'FAIL'}")
            for profile, report in result.devices.items():
                print(f"{profile}: {'PASS' if report['passed'] else 'FAIL'}")
            print(f"Run: {result.path}")
            return 0 if result.passed else 1
        if arguments.command == "verify":
            scene = Scene.load(arguments.scene)
            source = verify(scene)
            documents = {"source": source.to_dict()}
            if arguments.vdi:
                documents["vdi"] = verify_vdi(scene).to_dict()
            if arguments.json:
                print(json.dumps(documents, indent=2, sort_keys=True))
            else:
                _print_report(documents["source"])
                if "vdi" in documents:
                    print()
                    _print_report(documents["vdi"])
            return 0 if all(report["passed"] for report in documents.values()) else 1
        if arguments.command == "render":
            scene = Scene.load(arguments.scene)
            output = Path(arguments.output)
            kind = arguments.format or output.suffix.lower().lstrip(".")
            if kind == "svg":
                write_svg(scene, output, arguments.width)
            elif kind == "png":
                write_png(scene, output, arguments.width)
            elif kind == "gem":
                write_metafile(scene, output)
            else:
                raise ValueError("output format must be svg, png, or gem")
            print(f"{kind}: {output} ({output.stat().st_size} bytes)")
            return 0
        if arguments.command == "replay":
            result = replay(arguments.run)
            if arguments.json:
                print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
            else:
                _print_report(result.source)
                _print_report(result.vdi)
                for profile, report in result.devices.items():
                    print(f"{profile}: {'PASS' if report['passed'] else 'FAIL'} · source+VDI+invariants")
                print(f"Recorded reports match: {result.matches_recorded}")
            return 0 if result.passed and result.matches_recorded else 1
        if arguments.command == "solve":
            constraints = []
            if arguments.constraints:
                constraints = json.loads(Path(arguments.constraints).read_text(encoding="utf-8"))
                if not isinstance(constraints, list):
                    raise ValueError("constraint file must contain a JSON array")
            result = solve(
                arguments.request, arguments.agent_command, constraints,
                max_attempts=arguments.attempts, timeout=arguments.timeout, cwd=arguments.cwd,
            )
            if result.scene is None:
                path = write_failed_run(arguments.output, result.trajectory, result.error or "no valid scene returned")
                print(f"No valid Spatial IR scene after {result.attempts} attempts. Trajectory: {path}", file=sys.stderr)
                return 1
            run = export_run(result.scene, arguments.output, trajectory=result.trajectory)
            _print_report(run.source.to_dict())
            print(f"Attempts: {result.attempts}")
            print(f"Source+VDI+devices: {'PASS' if run.passed else 'FAIL'}")
            print(f"Run: {run.path}")
            return 0 if run.passed else 1
    except (OSError, RuntimeError, ValueError) as error:
        print(f"gem: {error}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
