"""Incremental repair of verified/restacked heads without discarding completed reviews."""
from copy import deepcopy
from pathlib import Path
import fnmatch
import shutil
import uuid

from .core import Error, atomic_json, command, git, ownership_audit, read_json, validate_findings


def active(run):
    value = run.state.get("active_repair")
    if not value:
        raise Error("No repair is active")
    return value, run.entry(value["pr"]), Path(value["directory"])


def begin(run, number, reason, include_unselected=False):
    run.ready()
    run.assert_heads()
    if not reason.strip():
        raise Error("A repair needs a concrete reason from verification or CI evidence")
    if len(run.state.get("repairs", [])) >= run.cfg.get("max_repair_rounds", 3):
        raise Error("Repair round limit reached; report the remaining blocker instead of looping")
    if run.state.get("publication", {}).get("branches") and not run.state.get("pushed"):
        raise Error("Finish the partial publication before repairing its results")
    p = run.entry(number)
    if not p.get("selected", True) and not include_unselected:
        raise Error("Repair would expand review scope; obtain user authorization and use --include-unselected")
    refs = [run.state["prs"][0]["base"]] + [q["head"] for q in run.state["prs"]]
    observed = {ref: sha for sha, ref in (line.split("\t") for line in
                git(run.repo, "ls-remote", run.state["remote"], *[f"refs/heads/{b}" for b in refs]).splitlines())}
    if observed.get(f"refs/heads/{refs[0]}") != run.state["base_sha"]:
        raise Error("Root base moved; a fresh run must review the changed integration context")
    published = run.state.get("pushed", False)
    for q in run.state["prs"]:
        expected = q["new"] if published else q.get("lease", q["original"])
        if observed.get(f"refs/heads/{q['head']}") != expected:
            raise Error(f"Remote {q['head']} moved; do not repair stale heads")
    round_number = len(run.state.get("repairs", [])) + 1
    directory = run.directory / "repairs" / f"{round_number:03d}-{uuid.uuid4().hex[:8]}"
    directory.mkdir(parents=True)
    atomic_json(directory / "before.json", run.state)
    for filename in ("plan.json", "SUMMARY.md"):
        if (run.directory / filename).exists():
            shutil.copy2(run.directory / filename, directory / filename)
    old_verification = run.state.get("verification") or run.state.get("failed_verification") or {}
    repair = {"pr": number, "reason": reason, "round": round_number, "directory": str(directory),
              "scope_expanded": not p.get("selected", True),
              "stage": "fix", "start": p["new"], "old_heads": run.heads(),
              "old_bases": {str(q["number"]): q["new_base"] for q in run.state["prs"]}, "review_attempts": 0}
    for key in ("verification", "failed_verification", "plan", "approval", "publication"):
        run.state.pop(key, None)
    if published:
        for q in run.state["prs"]:
            q["lease"] = q["new"]
    run.state.update(active_repair=repair, revision=run.state.get("revision", 0) + 1, pushed=False,
                     phase="repairing", reusable_verification=old_verification,
                     ci={"state": "paused_for_repair", "reason": reason})
    p["selected"] = True
    brief = f"""# Repair PR #{number}

Reason: {reason}
Work only in {run.worktree(p)}, starting at {p['new']}.
Read the original review/fix artifacts in {run.pr_dir(p)}, frozen context.json and
specialists.json in {run.directory}, and applicable project rules. Completed reviews
remain valid context; do not repeat the whole review or alter original findings/verdicts.
Read this repair's review.json when present; independently evaluate its feedback.
Make focused, append-only commits that preserve intended behavior. No rebases, resets,
pushes, CI permission changes, workflow dispatches or broad base-branch cleanup.
If the failure is environmental or needs a product decision, report the blocker and
recommendation instead of weakening tests. Keep the worktree clean after committing.

Write changes.json here: an array of {{"commit": "full SHA", "reason": "what and why"}}
covering EVERY new commit after {p['new']}. Update it after any additional fix commits.
If a description needs correcting, edit {run.pr_dir(p) / 'body.new.md'} minimally.
An independent patch reviewer follows before integration; the runner carries the fix upward.
"""
    (directory / "fix-brief.md").write_text(brief)
    run.save()
    return {"brief": str(directory / "fix-brief.md"), "round": round_number}


def record(run):
    repair, p, directory = active(run)
    if repair["stage"] != "fix":
        raise Error("This repair is not awaiting fix commits")
    worktree = run.worktree(p)
    run.clean(worktree)
    head = git(worktree, "rev-parse", "HEAD")
    if command(["git", "merge-base", "--is-ancestor", repair["start"], head], cwd=worktree, check=False).returncode:
        raise Error("Repair commits must append to the frozen repair head")
    commits = git(worktree, "rev-list", "--reverse", f"{repair['start']}..{head}").splitlines()
    if not commits or git(worktree, "rev-list", "--merges", f"{repair['start']}..{head}"):
        raise Error("Repair requires new linear fix commits")
    changes = read_json(directory / "changes.json")
    if (not isinstance(changes, list) or any(not isinstance(c, dict) or not isinstance(c.get("reason"), str)
            or not c["reason"].strip() or c.get("commit") not in commits for c in changes)
            or len(changes) != len(commits) or {c["commit"] for c in changes} != set(commits)):
        raise Error("changes.json must explain every new repair commit exactly once")
    audit = []
    for commit in commits:
        for filename in filter(None, git(worktree, "diff-tree", "--no-commit-id", "--name-only", "-z", "-r", commit, raw=True).split("\0")):
            if any(fnmatch.fnmatchcase(filename, pat) for pat in run.cfg["forbidden_paths"]):
                raise Error(f"Repair changes forbidden path: {filename}")
        audit.extend(ownership_audit(worktree, run.state["base_sha"], f"{commit}^", commit))
    atomic_json(directory / "ownership.json", audit)
    if audit and run.cfg["ownership_policy"] == "stack":
        raise Error("Repair changes base-owned lines; report the required scope decision")
    repair.update(stage="review", head=head, commits=commits, changes=changes, ownership_audit=audit)
    (directory / "repair.patch").write_text(git(worktree, "diff", repair["start"], head) + "\n")
    (directory / "review-brief.md").write_text(f"""# Independently review repair of PR #{p['number']}

Read fix-brief.md, changes.json, repair.patch, original project context and PR description.
Inspect {worktree} read-only at {head}. Review the new repair commits and relevant
callers; do not redo unrelated completed reviews. Verify the stated failure is fixed
without weakening checks or changing intended behavior. Write review.json here as
{{"head": "{head}", "findings": [...]}}. Findings use the normal id/axis/severity/file/
line/summary/evidence schema; [] means the repair is sound. Do not fix code yourself.
""")
    git(run.repo, "update-ref", f"refs/stack-review/repair/{repair['round']}/{p['number']}", head)
    run.save()
    return {"brief": str(directory / "review-brief.md")}


def record_review(run):
    repair, p, directory = active(run)
    if repair["stage"] != "review":
        raise Error("This repair is not awaiting independent review")
    run.clean(run.worktree(p))
    result = read_json(directory / "review.json")
    if not isinstance(result, dict) or result.get("head") != repair["head"] or git(run.worktree(p), "rev-parse", "HEAD") != repair["head"]:
        raise Error("Repair review does not cover the current fix head")
    validate_findings(result.get("findings"))
    repair["review_attempts"] += 1
    atomic_json(directory / f"review-{repair['review_attempts']}.json", result)
    if result["findings"]:
        repair["stage"] = "blocked" if repair["review_attempts"] >= run.cfg.get("max_repair_rounds", 3) else "fix"
        run.save()
        return {"accepted": False, "next": repair["stage"], "findings": len(result["findings"])}
    repair.update(stage="restack", index=run.state["prs"].index(p) + 1)
    p["new"] = repair["head"]
    run.save()
    return {"accepted": True, "next": "repair-restack"}


def restack(run, resume=False):
    repair, target, directory = active(run)
    if repair["stage"] != "restack":
        raise Error("Independently review the repair before integrating it")
    if repair.get("pending") and not resume:
        raise Error("Resolve the paused upper worktree and use repair restack --continue")
    prs = run.state["prs"]
    while repair["index"] < len(prs):
        index = repair["index"]
        p, below = prs[index], prs[index - 1]["new"]
        worktree = run.worktree(p)
        if repair.get("pending") == p["number"]:
            marker = Path(git(worktree, "rev-parse", "--absolute-git-dir")) / "rebase-merge"
            if marker.exists():
                git(worktree, "rebase", "--continue")
            elif command(["git", "merge-base", "--is-ancestor", below, "HEAD"], cwd=worktree, check=False).returncode:
                raise Error("Repair rebase was aborted or did not start; inspect before continuing")
        else:
            run.clean(worktree)
            if git(worktree, "rev-parse", "HEAD") != repair["old_heads"][str(p["number"])]:
                raise Error("An upper worktree moved during repair; refusing to overwrite it")
            repair["pending"] = p["number"]
            run.save()
            git(worktree, "rebase", "--merge", "--onto", below, repair["old_bases"][str(p["number"])])
        run.clean(worktree)
        p["new"], p["new_base"] = git(worktree, "rev-parse", "HEAD"), below
        git(run.repo, "update-ref", f"refs/stack-review/{p['number']}/restacked", p["new"])
        (directory / f"{p['number']}-range-diff.txt").write_text(git(run.repo, "range-diff",
            f"{repair['old_bases'][str(p['number'])]}..{repair['old_heads'][str(p['number'])]}", f"{below}..{p['new']}") + "\n")
        repair["index"] += 1
        repair.pop("pending", None)
        run.save()
    run.clean(run.worktree(target))
    if git(run.worktree(target), "rev-parse", "HEAD") != repair["head"]:
        raise Error("Repair target moved after its review")
    run.state.setdefault("repairs", []).append({"round": repair["round"], "pr": repair["pr"], "reason": repair["reason"],
        "commits": repair["commits"], "directory": str(directory), "reviewed_head": repair["head"],
        "ownership_audit": repair["ownership_audit"], "scope_expanded": repair["scope_expanded"]})
    run.state.pop("active_repair")
    run.state.update(restacked=True, phase="restacked")
    run.save()
    return {"next": "verify", "revision": run.state["revision"]}


def cancel(run):
    repair, p, directory = active(run)
    run.clean(run.worktree(p))
    if repair["stage"] != "fix" or git(run.worktree(p), "rev-parse", "HEAD") != repair["start"]:
        raise Error("Only an unchanged repair can be cancelled; existing repair work is preserved")
    run.state = read_json(directory / "before.json")
    # A previous detached CI worker must not resume after restoring an old token.
    if run.state.get("ci"):
        run.state["ci"].pop("worker_token", None)
    run.save()
    return {"cancelled": str(directory), "next": run.next()}
