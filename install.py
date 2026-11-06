#!/usr/bin/env python3
"""Dependency-free explicit installation; does not configure credentials or change existing skills."""
import argparse
from pathlib import Path
import shutil
import sys


def install(prefix, host=None, skills_dir=None):
    prefix = Path(prefix).expanduser().resolve()
    if prefix.exists():
        raise SystemExit(f"Installation prefix already exists; choose a new prefix: {prefix}")
    if host:
        import os
        base = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))) if host == "hermes" else Path.home() / ".claude"
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
    if host:
        sys.path.insert(0, str(prefix / "lib"))
        from stack_review.cli import install_skill
        print(install_skill(host, skills_dir))
    print(f"Installed {executable}")
    print(f"Add {executable.parent} to PATH, then start a fresh host session.")
    return executable


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, default=Path.home() / ".local/opt/stack-review")
    parser.add_argument("--host", choices=("hermes", "claude"))
    parser.add_argument("--skills-dir", type=Path, help="Exact destination for the stack-review skill")
    args = parser.parse_args()
    if args.skills_dir and not args.host:
        parser.error("--skills-dir requires --host")
    install(args.prefix, args.host, args.skills_dir)
