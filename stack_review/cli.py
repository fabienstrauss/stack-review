"""Command interface; every operation on an existing run requires its ID."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

from .core import DEFAULTS, Error, Run, atomic_json, command, create, git, lock, settings


def home():
    return Path(os.environ.get("STACK_REVIEW_HOME", str(Path.home() / ".local/share/stack-review"))).expanduser()


def install_skill(host, destination=None):
    base = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))) if host == "hermes" else Path.home() / ".claude"
    target = Path(destination).expanduser() if destination else base / "skills" / "stack-review"
    if target.exists() or target.is_symlink():
        raise Error(f"Skill destination already exists; left untouched: {target}")
    source = Path(__file__).parent / "skills" / host
    target.parent.mkdir(parents=True, exist_ok=True)
    # Publish a complete directory; never leave a partially copied live skill.
    temporary = Path(tempfile.mkdtemp(prefix=".stack-review-", dir=target.parent))
    try:
        for file in source.iterdir():
            shutil.copy2(file, temporary / file.name)
        shutil.copy2(Path(__file__).parent / "workflow.md", temporary / "workflow.md")
        temporary.rename(target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return {"installed": str(target), "host": host, "activation": "not verified; start a fresh host session and invoke /stack-review"}


def parser():
    ap = argparse.ArgumentParser(description="Portable PR stack review (Python 3.10+, Git, optional gh)")
    ap.add_argument("--home", type=Path, default=home(), help="Private runtime data directory")
    sp = ap.add_subparsers(dest="command", required=True)
    init = sp.add_parser("init", help="Write a settings proposal; no Git or live-agent changes")
    init.add_argument("--settings", required=True, type=Path)
    init.add_argument("--checkout", required=True, type=Path)
    init.add_argument("--repository", required=True)
    doctor = sp.add_parser("doctor", help="Read-only prerequisite/configuration inspection")
    doctor.add_argument("--settings", required=True, type=Path)
    install = sp.add_parser("install-skill", help="Explicitly install one host adapter; refuses replacement")
    install.add_argument("--host", choices=("hermes", "claude"), required=True)
    install.add_argument("--destination", type=Path)
    start = sp.add_parser("start")
    start.add_argument("--settings", required=True, type=Path)
    group = start.add_mutually_exclusive_group(required=True)
    group.add_argument("--pr", type=int, help="Discover the entire stack containing this PR")
    group.add_argument("--manifest", type=Path, help="Explicit PR array, bottom to top (offline discovery)")
    sp.add_parser("list", help="List run metadata without executing any commands")
    for name in ("status", "next", "record-review", "prepare-fix", "record-fix", "restack", "verify", "plan", "approve", "push"):
        p = sp.add_parser(name)
        p.add_argument("--run", required=True)
        if name in ("record-review", "prepare-fix", "record-fix"):
            p.add_argument("--pr", required=True, type=int)
        if name == "restack":
            p.add_argument("--continue", dest="resume", action="store_true")
        if name == "verify":
            p.add_argument("--skip-reason")
        if name == "approve":
            p.add_argument("--digest", required=True)
        if name == "push":
            p.add_argument("--dry-run", action="store_true")
    return ap


def dispatch(a):
    if a.command == "init":
        if a.settings.exists():
            raise Error("Settings already exist; refusing to overwrite")
        cfg = {**DEFAULTS, "checkout": str(a.checkout.expanduser().resolve()), "repository": a.repository}
        atomic_json(a.settings, cfg)
        return {"settings": str(a.settings), "next": "Configure checks and project context; then run doctor"}
    if a.command == "doctor":
        cfg = settings(a.settings)
        result = {"python": sys.version.split()[0], "git": shutil.which("git"), "gh": shutil.which("gh"),
                  "checks_configured": len(cfg["checks"]), "agents": cfg["agents"]}
        if not result["git"]:
            raise Error("Git is required")
        result["checkout"] = git(cfg["checkout"], "rev-parse", "--show-toplevel")
        result["remote_configured"] = bool(git(cfg["checkout"], "remote", "get-url", cfg["remote"]))
        result["skill_loaded"] = "unknown"
        return result
    if a.command == "install-skill":
        return install_skill(a.host, a.destination)
    if a.command == "start":
        return {"run": create(a.home, a.settings, a.pr, a.manifest)}
    if a.command == "list":
        rows = []
        for path in sorted((a.home / "runs").glob("*/run.json")):
            from .core import read_json
            state = read_json(path)
            rows.append({"run": state["id"], "phase": state["phase"], "prs": [p["number"] for p in state["prs"]]})
        return rows
    # Lock before reading state to avoid stale writers. Read-only commands do not create files.
    if a.command in ("status", "next"):
        run = Run(a.home, a.run)
        return run.next() if a.command == "next" else {
            "run": a.run, "phase": run.state["phase"], "next": run.next(),
            "prs": [{k: p.get(k) for k in ("number", "phase", "original", "new")} for p in run.state["prs"]],
            "directory": str(run.directory), "verification": run.state.get("verification"),
            "failed_verification": run.state.get("failed_verification"), "publication": run.state.get("publication")}
    # Validate identity before choosing the lock path, but reload state under lock.
    run = Run(a.home, a.run)
    with lock(run.directory):
        run = Run(a.home, a.run)
        if run.state.get("pushed"):
            if a.command == "push":
                return run.push(a.dry_run)
            raise Error("Published runs are immutable; start a fresh run")
        if a.command == "record-review":
            return run.record_review(a.pr)
        if a.command == "prepare-fix":
            return {"brief": run.prepare(a.pr)}
        if a.command == "record-fix":
            return run.record_fix(a.pr)
        if a.command == "restack":
            return run.restack(a.resume)
        if a.command == "verify":
            return run.verify(a.skip_reason)
        if a.command == "plan":
            return run.plan()
        if a.command == "approve":
            return run.approve(a.digest)
        if a.command == "push":
            return run.push(a.dry_run)
    raise Error("Unknown command")


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result = dispatch(args)
        print(json.dumps(result if result is not None else {"ok": True}, indent=2))
    except (Error, KeyError, TypeError, ValueError) as exc:
        print(f"stack-review: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc
