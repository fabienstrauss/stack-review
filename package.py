#!/usr/bin/env python3
"""Build a source zip from an explicit allowlist; never include settings, caches or runtime data."""
import argparse
from pathlib import Path
import zipfile

FILES = (
    ".gitignore", "README.md", "install.py", "package.py", "pyproject.toml",
    "examples/manifest.json", "examples/settings.json",
    "stack_review/__init__.py", "stack_review/__main__.py",
    "stack_review/core.py", "stack_review/cli.py", "stack_review/workflow.md",
    "stack_review/onboarding.py",
    "stack_review/reviews.py", "stack_review/preflight.py", "stack_review/installation.py",
    "stack_review/repair.py", "stack_review/ci.py", "stack_review/ci_worker.py",
    "stack_review/legacy-v0.2.json",
    "stack_review/skills/hermes/SKILL.md", "stack_review/skills/claude/SKILL.md",
    "tests/test_pipeline.py", "tests/test_features.py", "tests/test_repair_ci.py",
)


def build(output):
    source = Path(__file__).resolve().parent
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation avoids accidentally replacing a previous release.
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            file = source / name
            if file.is_symlink():
                raise ValueError(f"Distribution input must not be a symlink: {name}")
            entry = zipfile.ZipInfo(f"stack-review/{name}", date_time=(2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, file.read_bytes())
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("dist/stack-review-0.4.0.zip"))
    args = parser.parse_args()
    print(build(args.output))
