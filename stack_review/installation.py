"""Managed installation with integrity checks, backup, rollback and removal of owned files only."""
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import shutil
import shlex
import sys
import uuid

from . import __version__
from .core import Error, atomic_json, lock, read_json


def hashes(root, manifest=False):
    result = {}
    for p in Path(root).rglob("*"):
        if "__pycache__" in p.parts or p.suffix == ".pyc":
            continue
        if p.is_symlink():
            raise Error(f"Managed installation contains a symlink; left untouched: {p}")
        if p.is_file() and not (manifest and p == Path(root) / "installation.json"):
            result[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return result


def verify(prefix):
    prefix = Path(prefix).expanduser().resolve()
    manifest = Path(prefix) / "installation.json"
    if not manifest.is_file():
        raise Error("Existing installation has no ownership manifest; left untouched. Use a separate prefix and skill destination to migrate a legacy install")
    data = read_json(manifest)
    if data.get("package") != "portable-stack-review" or data.get("prefix") != str(prefix):
        raise Error("Installation identity mismatch; left untouched")
    if hashes(prefix, manifest=True) != data["files"]:
        raise Error("Installed files were edited or unexpected files were added; preserve those changes before updating/removing")
    for skill in data["skills"]:
        if not Path(skill["path"]).is_dir() or hashes(skill["path"]) != skill["files"]:
            raise Error(f"Installed skill was edited or removed; left untouched: {skill['path']}")
    return data


def skill_path(host):
    import os
    base = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))) if host == "hermes" else Path.home() / ".claude"
    return (base / "skills/stack-review").expanduser().resolve()


def legacy(prefix, hosts, destination):
    """Adopt only byte-for-byte known v0.2 files, including path-specific launchers."""
    expected = read_json(Path(__file__).with_name("legacy-v0.2.json"))
    package = prefix / "lib/stack_review"
    if not package.is_dir() or hashes(package) != expected:
        raise Error("Existing installation has no ownership manifest and is not an unmodified v0.2 release; left untouched")
    launcher = prefix / "bin/stack-review"
    try:
        first = launcher.read_text().splitlines()[0]
    except (OSError, IndexError) as exc:
        raise Error("Legacy launcher is missing; left untouched") from exc
    if not first.startswith("#!"):
        raise Error("Unrecognized legacy launcher; left untouched")
    python = first[2:]
    launch_text = f"#!{python}\nimport sys\nsys.path.insert(0, {str(prefix / 'lib')!r})\nfrom stack_review.cli import main\nmain()\n"
    expected_prefix = {f"lib/stack_review/{name}": value for name, value in expected.items()}
    expected_prefix["bin/stack-review"] = hashlib.sha256(launch_text.encode()).hexdigest()
    if hashes(prefix) != expected_prefix:
        raise Error("Legacy installation contains edits or additional files; left untouched")
    targets = {host: skill_path(host) for host in ("hermes", "claude")}
    if destination and len(hosts) == 1:
        targets[hosts[0]] = Path(destination).expanduser().resolve()
    skills = []
    runner_text = f"import sys\nsys.path.insert(0, {str(prefix / 'lib')!r})\nfrom stack_review.cli import main\nmain()\n"
    for host, target in targets.items():
        if not (target / "runner.py").is_file() or (target / "runner.py").read_text() != runner_text:
            continue
        invocation = shlex.join([python, str(target / "runner.py")])
        runner_md = "# Installed runner\n\nUse this exact command for RUNNER in workflow.md. No PATH change is needed.\n\n```sh\n" + invocation + "\n```\n\nAppend the subcommand and arguments, e.g. `project inspect --checkout <project>`.\n"
        expected_skill = {"SKILL.md": expected[f"skills/{host}/SKILL.md"], "workflow.md": expected["workflow.md"],
                          "runner.py": hashlib.sha256(runner_text.encode()).hexdigest(),
                          "runner.md": hashlib.sha256(runner_md.encode()).hexdigest()}
        if hashes(target) != expected_skill:
            raise Error(f"Legacy skill has edits; left untouched: {target}")
        skills.append({"host": host, "path": str(target), "files": expected_skill})
    return {"package": "portable-stack-review", "version": "0.2.0", "prefix": str(prefix),
            "files": expected_prefix, "skills": skills, "previous_backup": None}


def snapshot(prefix, data):
    parent = prefix.parent / ".stack-review-backups" / prefix.name
    target = parent / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8])
    target.mkdir(parents=True)
    shutil.copytree(prefix, target / "prefix", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if not (target / "prefix/installation.json").exists():
        atomic_json(target / "prefix/installation.json", data)
    for i, skill in enumerate(data["skills"]):
        shutil.copytree(skill["path"], target / f"skill-{i}", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    atomic_json(target / "backup.json", {"prefix": str(prefix), "skills": data["skills"]})
    return target


def remove_owned(prefix, data):
    for skill in data["skills"]:
        shutil.rmtree(skill["path"])
    shutil.rmtree(prefix)


def restore(prefix, backup):
    data = read_json(backup / "backup.json")
    if data["prefix"] != str(prefix):
        raise Error("Backup belongs to another installation")
    recorded = read_json(backup / "prefix/installation.json")
    if hashes(backup / "prefix", manifest=True) != recorded["files"]:
        raise Error("Backup files changed; refusing to restore it")
    for i, skill in enumerate(data["skills"]):
        if hashes(backup / f"skill-{i}") != skill["files"]:
            raise Error("Backup skill files changed; refusing to restore them")
    shutil.copytree(backup / "prefix", prefix)
    for i, skill in enumerate(data["skills"]):
        shutil.copytree(backup / f"skill-{i}", skill["path"])


def install(prefix, hosts, destination=None):
    from .cli import install_skill
    prefix = Path(prefix).expanduser().resolve()
    if len(hosts) > 1 and destination:
        raise Error("A custom skill destination is for one host; choose Hermes or Claude")
    # Lock lives outside the removable prefix and is shared by install/rollback/uninstall.
    with lock(prefix.parent / ".stack-review-locks" / prefix.name):
        previous = (verify(prefix) if (prefix / "installation.json").is_file()
                    else legacy(prefix, hosts, destination)) if prefix.exists() else None
        targets = {s["host"]: Path(s["path"]) for s in previous["skills"]} if previous else {}
        for host in hosts:
            target = Path(destination).expanduser().resolve() if destination else targets.get(host, skill_path(host))
            if target.exists() and not any(s["path"] == str(target) for s in (previous or {}).get("skills", [])):
                raise Error(f"Skill destination already exists; left untouched: {target}")
            if host in targets and target != targets[host]:
                raise Error("Changing an installed skill destination requires uninstalling that installation first")
            targets[host] = target
        if len(set(targets.values())) != len(targets):
            raise Error("Host skill destinations must be distinct")
        backup = snapshot(prefix, previous) if previous else None
        if previous:
            remove_owned(prefix, previous)
        created = []
        try:
            prefix.mkdir(parents=True)
            source = Path(__file__).resolve().parent
            shutil.copytree(source, prefix / "lib/stack_review", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            executable = prefix / "bin/stack-review"
            executable.parent.mkdir()
            executable.write_text(f"#!{sys.executable}\nimport sys\nsys.dont_write_bytecode = True\nsys.path.insert(0, {str(prefix / 'lib')!r})\nfrom stack_review.cli import main\nmain()\n")
            executable.chmod(0o755)
            skills = []
            for host, target in targets.items():
                install_skill(host, target, runtime_root=prefix / "lib")
                created.append(target)
                skills.append({"host": host, "path": str(target), "files": hashes(target)})
            manifest = {"package": "portable-stack-review", "version": __version__, "prefix": str(prefix),
                        "files": hashes(prefix, manifest=True), "skills": skills, "previous_backup": str(backup) if backup else None}
            atomic_json(prefix / "installation.json", manifest)
        except Exception:
            for target in created:
                shutil.rmtree(target)
            if prefix.exists():
                shutil.rmtree(prefix)
            if backup:
                restore(prefix, backup)
            raise
    return {"installed": str(executable), "version": __version__, "hosts": list(targets),
            "updated": previous is not None, "backup": str(backup) if backup else None,
            "next": "Start a fresh agent session and say /stack-review 123. No PATH change or JSON editing needed"}


def uninstall(prefix):
    prefix = Path(prefix).expanduser().resolve()
    with lock(prefix.parent / ".stack-review-locks" / prefix.name):
        data = verify(prefix)
        backup = snapshot(prefix, data)
        remove_owned(prefix, data)
    return {"removed": str(prefix), "backup": str(backup), "preserved": "Project preferences, run data and previous backups"}


def rollback(prefix):
    prefix = Path(prefix).expanduser().resolve()
    with lock(prefix.parent / ".stack-review-locks" / prefix.name):
        data = verify(prefix)
        if not data.get("previous_backup"):
            raise Error("No previous managed installation to restore")
        backup = Path(data["previous_backup"]).resolve()
        allowed = (prefix.parent / ".stack-review-backups" / prefix.name).resolve()
        if not backup.is_relative_to(allowed):
            raise Error("Invalid backup location")
        # Validate backup contents before removing the current release.
        recorded = read_json(backup / "prefix/installation.json")
        backup_info = read_json(backup / "backup.json")
        if (backup_info["prefix"] != str(prefix) or hashes(backup / "prefix", manifest=True) != recorded["files"]
                or any(hashes(backup / f"skill-{i}") != s["files"] for i, s in enumerate(backup_info["skills"]))):
            raise Error("Backup contents changed; current installation left untouched")
        # Keep the current release too, so rollback does not destroy it.
        snapshot(prefix, data)
        remove_owned(prefix, data)
        restore(prefix, backup)
    return {"restored": str(prefix), "version": read_json(prefix / "installation.json")["version"]}
