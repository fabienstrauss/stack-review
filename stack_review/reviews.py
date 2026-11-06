"""Review memoization. Keys include code trees, requirements, rules and reviewer instructions."""
import difflib
from pathlib import Path

from . import __version__
from .core import Error, atomic_json, digest, git, lock, read_json


def specialists(cfg):
    found, missing = [], []
    for spec in cfg.get("specialist_skills", []):
        source = Path(spec["path"]).expanduser()
        if not source.is_absolute():
            source = Path(cfg["checkout"]) / source
        source = source.resolve()
        if source.is_dir():
            source = source / "SKILL.md"
        if not source.is_file():
            if spec["required"]:
                raise Error(f"Required specialist skill unavailable: {spec['name']} ({source})")
            missing.append(spec["name"])
            continue
        # Freeze Markdown references so changed specialist guidance invalidates cached reviews.
        docs = {}
        total = 0
        for file in sorted(source.parent.rglob("*.md")):
            if file.is_symlink():
                raise Error(f"Specialist documentation contains a symlink: {file}")
            total += file.stat().st_size
            if total > 2_000_000 or len(docs) >= 500:
                raise Error(f"Specialist documentation too large: {spec['name']}")
            docs[str(file.relative_to(source.parent))] = file.read_text()
        found.append({"name": spec["name"], "required": spec["required"], "source": str(source), "documents": docs})
    return {"available": found, "missing_optional": missing}


def cache_dir(home, cfg, number):
    project = digest({"repository": cfg["repository"], "checkout": cfg["checkout"]})
    return Path(home) / "reviews" / project / str(number)


def identities(repo, p, state):
    common = {"method": 3, "runner_version": __version__, "config": state["config"], "context": state["context"],
              "specialists": state.get("specialists", {}), "instructions": state.get("instructions", ""),
              "feedback": p.get("feedback", []), "review_only": state.get("review_only", False),
              "root_base_tree": git(repo, "rev-parse", f"{state['base_sha']}^{{tree}}"),
              "parent_tree": git(repo, "rev-parse", f"{p['base_point']}^{{tree}}"),
              "requirements": {"title": p["title"], "body": p["body"]},
              "stack": [s for s in state.get("stack_context", []) if s["number"] != p["number"]]}
    context_key = digest(common)
    key = digest({"context": context_key, "tree": git(repo, "rev-parse", f"{p['original']}^{{tree}}"),
                  "title": p["title"], "body": p["body"]})
    return key, context_key


def load(home, cfg, number, key):
    path = cache_dir(home, cfg, number) / f"{key}.json"
    return read_json(path) if path.is_file() else None


def prior(home, cfg, number, context_key):
    paths = list(cache_dir(home, cfg, number).glob("*.json"))
    for path in sorted(paths, key=lambda p: p.stat().st_mtime_ns, reverse=True):
        value = read_json(path)
        if value.get("context_key") == context_key:
            return value
    return None


def store(home, cfg, p, directory, patch=None, verdicts=None):
    target = cache_dir(home, cfg, p["number"])
    data = {"key": p["review_key"], "context_key": p["review_context_key"], "findings": p["findings"],
            "diff": patch if patch is not None else (directory / "diff.patch").read_text(),
            "run": directory.parents[1].name, "verdicts": verdicts}
    with lock(target):
        atomic_json(target / f"{p['review_key']}.json", data)


def remember_publication(run):
    """Verified/published fixes establish the next baseline; unresolved decisions remain visible."""
    final = {**run.state, "stack_context": []}
    bodies = {}
    for p in run.state["prs"]:
        file = run.pr_dir(p) / "body.new.md"
        bodies[p["number"]] = file.read_text() if file.exists() else p["body"]
        final["stack_context"].append({"number": p["number"], "title": p["title"], "body": bodies[p["number"]],
                                       "tree": git(run.repo, "rev-parse", f"{p['new']}^{{tree}}")})
    for p in run.state["prs"]:
        if not p.get("selected", True):
            continue
        pending_ids = {v["id"] for v in p.get("verdicts", []) if v["verdict"] != "FIX"}
        findings = [f for f in p.get("findings", []) if f["id"] in pending_ids]
        entry = {**p, "original": p["new"], "base_point": p["new_base"], "body": bodies[p["number"]], "findings": findings}
        entry["review_key"], entry["review_context_key"] = identities(run.repo, entry, final)
        verdicts = [v for v in p.get("verdicts", []) if v["verdict"] != "FIX"]
        patch = git(run.repo, "diff", p["new_base"], p["new"]) + "\n"
        store(run.directory.parents[1], run.cfg, entry, run.pr_dir(p), patch=patch, verdicts=verdicts)


def change_patch(previous, current):
    return "".join(difflib.unified_diff(previous.splitlines(True), current.splitlines(True),
                                        fromfile="previous-review.patch", tofile="current-review.patch"))
