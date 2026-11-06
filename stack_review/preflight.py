"""Explicit prerequisite checks. Never executes project setup or test commands."""
from pathlib import Path
import shutil

from .core import Error, command, git
from .reviews import specialists


def check(cfg, delegation="unknown", offline=False):
    errors, deferred = [], []
    if not shutil.which("git"):
        errors.append("Git is missing; install Git before reviewing")
    else:
        try:
            git(cfg["checkout"], "rev-parse", "--show-toplevel")
            remote = git(cfg["checkout"], "remote", "get-url", cfg["remote"])
            from .onboarding import repository_name
            owner_repo = repository_name(remote)
            if owner_repo and owner_repo.lower() != cfg["repository"].lower():
                errors.append("The configured GitHub repository does not match the checkout's remote")
        except Error:
            errors.append("The selected checkout or Git remote is unavailable")
    for filename in cfg["context_files"]:
        path = Path(filename).expanduser()
        if not path.is_absolute():
            path = Path(cfg["checkout"]) / path
        if not path.is_file():
            errors.append(f"Project context file is missing: {filename}")
    if delegation != "available":
        errors.append("Fresh reviewer/fixer delegation is unavailable or unverified; the host must verify its tools")
    if not offline:
        if not shutil.which("gh"):
            errors.append("GitHub CLI is missing; install gh and sign in")
        elif command(["gh", "auth", "status"], check=False).returncode:
            errors.append("GitHub sign-in is unavailable; run gh auth login")
        elif command(["gh", "repo", "view", cfg["repository"], "--json", "nameWithOwner"], check=False).returncode:
            errors.append("The GitHub account cannot access the configured repository")
    for group in ("setup_commands", "checks"):
        for spec in cfg[group]:
            executable = spec["argv"][0]
            if "/" in executable or "{worktree}" in executable:
                deferred.append(f"{spec['name']}: verify its project-local executable after worktree setup")
            elif not shutil.which(executable):
                if group == "checks" and cfg["setup_commands"]:
                    deferred.append(f"{spec['name']}: {executable} is missing and may be provided by setup")
                else:
                    errors.append(f"{spec['name']}: command {executable} is missing")
    try:
        skill_status = specialists(cfg)
        missing = skill_status["missing_optional"]
    except Error as exc:
        errors.append(str(exc))
        missing = []
    return {"ready": not errors, "errors": errors, "deferred": deferred,
            "missing_optional_skills": missing, "delegation": delegation,
            "github_checked": not offline, "skill_loaded": "unknown"}
