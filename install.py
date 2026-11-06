#!/usr/bin/env python3
"""Dependency-free explicit installation; does not configure credentials or change existing skills."""
import argparse
import os
from pathlib import Path
import shutil
import sys


def install(prefix, host=None, skills_dir=None):
    prefix = Path(prefix).expanduser().resolve()
    if prefix.exists():
        raise SystemExit(f"Installation prefix already exists; choose a new prefix: {prefix}")
    hosts = ("hermes", "claude") if host == "both" else (host,) if host else ()
    if len(hosts) == 2 and skills_dir:
        raise SystemExit("--skills-dir selects one exact destination; use --host hermes or claude")
    for selected in hosts:
        base = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))) if selected == "hermes" else Path.home() / ".claude"
        target = Path(skills_dir).expanduser() if skills_dir else base / "skills" / "stack-review"
        if target.exists() or target.is_symlink():
            raise SystemExit(f"Skill destination already exists; left untouched: {target}")
    prefix.mkdir(parents=True)
    source = Path(__file__).resolve().parent / "stack_review"
    shutil.copytree(source, prefix / "lib" / "stack_review", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    executable = prefix / "bin" / "stack-review"
    executable.parent.mkdir()
    executable.write_text(f"#!{sys.executable}\nimport sys\nsys.path.insert(0, {str(prefix / 'lib')!r})\nfrom stack_review.cli import main\nmain()\n")
    executable.chmod(0o755)
    if hosts:
        sys.path.insert(0, str(prefix / "lib"))
        from stack_review.cli import install_skill
        for selected in hosts:
            print(install_skill(selected, skills_dir))
    print(f"Installed {executable}")
    print("Ready. Start a fresh Hermes/Claude session in your project and say /stack-review 123.")
    print("The agent handles first-use setup and all review commands. No PATH change or JSON editing needed.")
    return executable


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, default=Path.home() / ".local/opt/stack-review")
    parser.add_argument("--host", choices=("hermes", "claude", "both"))
    parser.add_argument("--skills-dir", type=Path, help="Exact destination for the stack-review skill")
    args = parser.parse_args()
    if args.skills_dir and not args.host:
        parser.error("--skills-dir requires --host")
    if not args.host:
        detected = []
        if Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))).is_dir():
            detected.append("hermes")
        if (Path.home() / ".claude").is_dir():
            detected.append("claude")
        if len(detected) == 1:
            args.host = detected[0]
            print(f"Found {args.host}; installing its skill.")
        else:
            try:
                answer = input("Install for [1] Hermes, [2] Claude Code, or [3] both? ").strip().lower()
            except EOFError:
                parser.error("Choose a host with --host hermes, --host claude or --host both")
            args.host = {"1": "hermes", "2": "claude", "3": "both", "hermes": "hermes", "claude": "claude", "both": "both"}.get(answer)
            if not args.host:
                parser.error("Choose 1, 2 or 3")
    install(args.prefix, args.host, args.skills_dir)
