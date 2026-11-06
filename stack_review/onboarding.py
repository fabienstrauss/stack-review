"""Read-only project discovery and explicit local configuration. Never runs project scripts."""
import ast
import hashlib
import json
from pathlib import Path
import re
import shlex
import tempfile

from .core import DEFAULTS, Error, atomic_json, git, lock, read_json, settings


def checkout_root(checkout):
    return Path(git(Path(checkout).expanduser(), "rev-parse", "--show-toplevel")).resolve()


def project_path(home, checkout):
    root = checkout_root(checkout)
    identity = hashlib.sha256(str(root).encode()).hexdigest()[:20]
    return Path(home).expanduser().resolve() / "projects" / identity / "settings.json"


def repository_name(url):
    # Extract only the owner/repository; never return a credential-bearing remote URL.
    match = re.fullmatch(r"(?:git@github\.com:|https://(?:[^/@]+@)?github\.com/|ssh://git@github\.com/)([\w.-]+/[\w.-]+?)(?:\.git)?/?", url)
    return match.group(1) if match else None


def inspect(home, checkout):
    root = checkout_root(checkout)
    path = project_path(home, root)
    remotes = git(root, "remote").splitlines()
    remote = "origin" if "origin" in remotes else remotes[0] if len(remotes) == 1 else None
    repository = repository_name(git(root, "remote", "get-url", remote)) if remote else None
    context = [name for name in ("AGENTS.md", "CLAUDE.md", ".hermes.md") if (root / name).is_file()]
    cfg = {**DEFAULTS, "checkout": str(root), "repository": repository, "remote": remote or "origin", "context_files": context}
    candidates = []
    evidence = []
    package = root / "package.json"
    if package.is_file():
        data = read_json(package)
        if not isinstance(data, dict):
            raise Error("package.json must be an object")
        manager = "pnpm" if (root / "pnpm-lock.yaml").is_file() else "yarn" if (root / "yarn.lock").is_file() else "bun" if any((root / n).exists() for n in ("bun.lock", "bun.lockb")) else "npm"
        scripts = data.get("scripts", {})
        if isinstance(scripts, dict):
            for name in ("test:ci", "test", "typecheck", "check", "lint"):
                if isinstance(scripts.get(name), str):
                    candidates.append({"name": name, "argv": [manager, "run", name], "cwd": "."})
        evidence.append({"file": "package.json", "package_manager": manager,
                         "script_names": [c["name"] for c in candidates]})
    tests = list((root / "tests").glob("test_*.py"))
    if tests:
        unittest_only = True
        for file in tests:
            try:
                tree = ast.parse(file.read_text())
                uses_unittest = any(isinstance(node, ast.Import) and any(a.name == "unittest" for a in node.names)
                                    or isinstance(node, ast.ImportFrom) and node.module == "unittest"
                                    for node in ast.walk(tree))
                unittest_only = unittest_only and uses_unittest
            except (OSError, SyntaxError, UnicodeError):
                unittest_only = False
        if unittest_only:
            candidates.append({"name": "unit tests", "argv": ["python3", "-m", "unittest", "discover", "-s", "tests"], "cwd": "."})
        evidence.append({"file": "tests/", "test_file_count": len(tests), "unittest_imports_in_all": unittest_only})
    for name in ("pyproject.toml", "pytest.ini", "Makefile", "Cargo.toml", "go.mod", "pnpm-workspace.yaml"):
        if (root / name).is_file():
            evidence.append({"file": name})
    # One recommended command, never all possible lint/typecheck/test jobs by default.
    if candidates:
        cfg["checks"] = [candidates[0]]
    existing = settings(path) if path.exists() else None
    return {"checkout": str(root), "settings_path": str(path), "configured": existing is not None,
            "settings": existing, "proposal": cfg, "check_candidates": candidates,
            "evidence": evidence, "remote_names": remotes,
            "needs": (["Git remote"] if not remote else []) + (["GitHub repository"] if not repository else []) + (["verification command"] if not candidates else []),
            "notice": "Suggestions only. Read project rules and script definitions before accepting; nothing was executed or saved."}


def configure(home, checkout, repository=None, remote=None, checks=None, setup=None, contexts=None, replace=False):
    observed = inspect(home, checkout)
    path = Path(observed["settings_path"])
    if observed["configured"] and not replace:
        return {"settings": str(path), "reused": True}
    cfg = observed["settings"] or observed["proposal"]
    if remote:
        if remote not in observed["remote_names"]:
            raise Error(f"Unknown remote {remote}")
        cfg["remote"] = remote
        cfg["repository"] = repository_name(git(cfg["checkout"], "remote", "get-url", remote))
    if repository:
        cfg["repository"] = repository
    if cfg["remote"] not in observed["remote_names"]:
        raise Error("Choose the project remote with --remote; no unambiguous remote was detected")
    for key, values in (("checks", checks), ("setup_commands", setup)):
        if values is not None:
            cfg[key] = [{"name": f"{key}-{i + 1}", "argv": shlex.split(value), "cwd": "."} for i, value in enumerate(values)]
    if contexts is not None:
        cfg["context_files"] = contexts
    if not cfg["repository"]:
        raise Error("Could not infer the GitHub repository. Supply --repository owner/repo")
    if not cfg["checks"]:
        raise Error("No verification command found. Supply --check 'your test command'; project scripts were not executed")
    # Validate before creating persistent state. Validation does not execute any configured command.
    with tempfile.TemporaryDirectory() as temporary:
        proposal = Path(temporary) / "settings.json"
        atomic_json(proposal, cfg)
        cfg = settings(proposal)
    with lock(path.parent):
        if path.exists() and not replace:
            return {"settings": str(path), "reused": True}
        atomic_json(path, cfg)
    return {"settings": str(path), "reused": False, "next": "Project ready. Start the requested review; do not ask the user to run CLI commands."}
