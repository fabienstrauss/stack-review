"""Command interface; every operation on an existing run requires its ID."""
import argparse
import json
import os
from pathlib import Path
import shutil
import shlex
import sys
import tempfile

from .core import DEFAULTS, Error, Run, atomic_json, command, create, git, lock, settings


def home():
    return Path(os.environ.get("STACK_REVIEW_HOME", str(Path.home() / ".local/share/stack-review"))).expanduser()


def install_skill(host, destination=None, runtime_root=None):
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
        runner = temporary / "runner.py"
        runtime = Path(runtime_root) if runtime_root else Path(__file__).resolve().parent.parent
        runner.write_text("import sys\nsys.dont_write_bytecode = True\n" + f"sys.path.insert(0, {str(runtime)!r})\n" +
                          "from stack_review.cli import main\nmain()\n")
        invocation = shlex.join([sys.executable, str(target.resolve() / "runner.py")])
        (temporary / "runner.md").write_text(
            "# Installed runner\n\nUse this exact command for RUNNER in workflow.md. No PATH change is needed.\n\n```sh\n" +
            invocation + "\n```\n\nAppend the subcommand and arguments, e.g. `project inspect --checkout <project>`.\n")
        temporary.rename(target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return {"installed": str(target), "host": host, "activation": "not verified; start a fresh host session and invoke /stack-review"}


def parser():
    ap = argparse.ArgumentParser(description="Portable PR stack review (Python 3.10+, Git, optional gh)")
    ap.add_argument("--home", type=Path, default=home(), help="Private runtime data directory")
    sp = ap.add_subparsers(dest="command", required=True)
    project = sp.add_parser("project", help="Agent-guided project onboarding; users do not edit JSON")
    ps = project.add_subparsers(dest="project_action", required=True)
    for name in ("inspect", "configure"):
        p = ps.add_parser(name)
        p.add_argument("--checkout", type=Path, default=Path.cwd())
        if name == "configure":
            p.add_argument("--repository")
            p.add_argument("--remote")
            p.add_argument("--check", action="append", help="Quoted command; parsed as argv, never a shell expression")
            p.add_argument("--setup", action="append")
            p.add_argument("--context", action="append")
            p.add_argument("--replace", action="store_true", help="Explicitly revise saved project preferences")
            p.add_argument("--skill", action="append", help="Optional name=/path/to/skill")
            p.add_argument("--require-skill", action="append", help="Required name=/path/to/skill")
    preflight = sp.add_parser("preflight", help="Check tools, GitHub access and specialist availability before work")
    preflight.add_argument("--settings", type=Path)
    preflight.add_argument("--checkout", type=Path, default=Path.cwd())
    preflight.add_argument("--delegation", choices=("available", "unavailable", "unknown"), default="unknown")
    preflight.add_argument("--offline", action="store_true", help="Skip GitHub auth/access checks for offline manifests")
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
    start.add_argument("--settings", type=Path, help="Advanced: override saved project settings")
    start.add_argument("--checkout", type=Path, default=Path.cwd())
    group = start.add_mutually_exclusive_group(required=True)
    group.add_argument("--pr", type=int, help="Discover the entire stack containing this PR")
    group.add_argument("--manifest", type=Path, help="Explicit PR array, bottom to top (offline discovery)")
    start.add_argument("--anchor", type=int, help="Selection anchor when using a manifest")
    start.add_argument("--scope", choices=("stack", "single", "from"), default="stack")
    start.add_argument("--again", action="store_true", help="Force a full review instead of cached/delta results")
    start.add_argument("--review-only", action="store_true", help="Findings only; no fixes, restack or publication")
    start.add_argument("--instructions", default="", help="User-requested review focus, frozen into cache identity")
    start.add_argument("--include-feedback", action="store_true", help="Evaluate existing inline review comments too")
    resume = start.add_mutually_exclusive_group()
    resume.add_argument("--new-run", action="store_true", help="Keep this session independent of matching pending runs")
    resume.add_argument("--resume-run", help="Resume a matching run after confirming another session is not using it")
    sp.add_parser("list", help="List run metadata without executing any commands")
    for name in ("status", "next", "record-review", "prepare-fix", "record-fix", "restack", "verify", "plan", "approve", "push", "report"):
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
    if a.command == "project":
        from . import onboarding
        if a.project_action == "inspect":
            return onboarding.inspect(a.home, a.checkout)
        return onboarding.configure(a.home, a.checkout, a.repository, a.remote, a.check, a.setup, a.context, a.replace,
                                    a.skill, a.require_skill)
    if a.command == "preflight":
        from .onboarding import project_path, stale
        from .preflight import check
        path = a.settings or project_path(a.home, a.checkout)
        cfg = settings(path)
        result = check(cfg, a.delegation, a.offline)
        if not a.settings:
            health = stale(path, cfg)
            result["settings_health"] = health
            if health["stale"]:
                result["ready"] = False
                result["errors"].append("Project metadata changed; have the agent revalidate saved settings and configure --replace")
        return result
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
        from .onboarding import project_path, stale
        config = a.settings or project_path(a.home, a.checkout)
        if not config.is_file():
            raise Error("This project is not configured yet. Use project inspect, then project configure; the agent handles these steps")
        if not a.settings and stale(config, settings(config))["stale"]:
            raise Error("Project instructions, manifests or skill documents changed; revalidate settings with project inspect/configure --replace")
        result = create(a.home, config, a.pr or a.anchor, a.manifest, a.scope, a.again, a.review_only,
                        a.instructions, not a.new_run, a.resume_run, a.include_feedback)
        return {"run": result} if isinstance(result, str) else result
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
        if a.command == "report":
            return run.report()
    raise Error("Unknown command")


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result = dispatch(args)
        print(json.dumps(result if result is not None else {"ok": True}, indent=2))
        if args.command == "preflight" and not result["ready"]:
            raise SystemExit(3)
    except (Error, KeyError, TypeError, ValueError) as exc:
        print(f"stack-review: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc
