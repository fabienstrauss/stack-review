"""Real Git repair integration plus mocked GitHub CI and a detached-worker fixture."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import test_pipeline as fixtures
from stack_review import core, repair, ci
from stack_review.cli import dispatch, parser


class RepairAndCITests(unittest.TestCase):
    setUp = fixtures.PipelineTests.setUp
    g = fixtures.PipelineTests.g
    start = fixtures.PipelineTests.start
    finding = fixtures.PipelineTests.finding
    fix = fixtures.PipelineTests.fix
    no_findings = fixtures.PipelineTests.no_findings
    completed = fixtures.PipelineTests.completed
    remote_head = fixtures.PipelineTests.remote_head

    def published(self):
        run = self.completed()
        plan = run.plan()
        run.approve(plan["digest"])
        run.push()
        return run

    def commit_repair(self, run, filename="one.txt", content="repaired first\n"):
        current = run.state["active_repair"]
        p = run.entry(current["pr"])
        worktree = run.worktree(p)
        (worktree / filename).write_text(content)
        core.git(worktree, "add", filename)
        core.git(worktree, "commit", "-m", "repair verification failure")
        head = core.git(worktree, "rev-parse", "HEAD")
        directory = Path(current["directory"])
        commits = core.git(worktree, "rev-list", "--reverse", f"{current['start']}..{head}").splitlines()
        core.atomic_json(directory / "changes.json", [{"commit": commit, "reason": "fix the reproduced failure"} for commit in commits])
        repair.record(run)
        return head

    def accept_repair(self, run):
        current = run.state["active_repair"]
        core.atomic_json(Path(current["directory"]) / "review.json", {"head": current["head"], "findings": []})
        repair.record_review(run)

    def github(self, run, buckets=None, api_lag=False, log_head=None):
        original = core.command
        buckets = buckets or {1: "pass", 2: "pass"}
        def fake(argv, **kwargs):
            if argv[:3] == ["gh", "pr", "view"]:
                number = int(argv[3])
                value = "a" * 40 if api_lag else run.entry(number)["new"]
                return subprocess.CompletedProcess(argv, 0, json.dumps({"headRefOid": value}), "")
            if argv[:3] == ["gh", "pr", "checks"]:
                number = int(argv[3])
                bucket = buckets[number]
                items = [] if bucket == "absent" else [{"name": "tests", "bucket": bucket, "state": "IN_PROGRESS" if bucket == "pending" else "COMPLETED",
                         "link": f"https://github.com/test/project/actions/runs/{number}/job/{number + 10}", "workflow": "CI"}]
                return subprocess.CompletedProcess(argv, 8 if bucket == "pending" else 1 if bucket == "fail" else 0, json.dumps(items), "")
            if argv[:3] == ["gh", "run", "view"]:
                number = int(argv[3])
                if "--json" in argv:
                    return subprocess.CompletedProcess(argv, 0, json.dumps({"headSha": log_head or run.entry(number)["new"]}), "")
                return subprocess.CompletedProcess(argv, 0, "failed assertion in owned code\n", "")
            return original(argv, **kwargs)
        return fake

    def test_failed_verification_repair_keeps_reviews_and_requires_new_plan(self):
        self.config_data["checks"] = [{"name": "must be fixed", "argv": [sys.executable, "-c",
            "from pathlib import Path; assert Path('one.txt').read_text() == 'repaired first\\n'"]}]
        core.atomic_json(self.config, self.config_data)
        run = self.start()
        self.no_findings(run, 1)
        self.no_findings(run, 2)
        run.restack()
        with self.assertRaises(core.Error):
            run.verify()
        findings = (run.pr_dir(run.entry(1)) / "findings.json").read_bytes()
        repair.begin(run, 1, "the local assertion reproduced a regression")
        self.commit_repair(run)
        with self.assertRaisesRegex(core.Error, "active repair"):
            run.verify()
        self.accept_repair(run)
        repair.restack(run)
        run.verify()
        self.assertEqual(run.state["id"], run.directory.name)
        self.assertEqual((run.pr_dir(run.entry(1)) / "findings.json").read_bytes(), findings)
        self.assertEqual(core.git(run.worktree(run.entry(2)), "show", "HEAD:one.txt"), "repaired first")
        plan = run.plan()
        with self.assertRaisesRegex(core.Error, "approval"):
            run.push()
        run.approve(plan["digest"])
        run.push()
        self.assertEqual(self.remote_head("part-2"), run.entry(2)["new"])

    def test_published_ci_repair_uses_new_leases_and_reuses_unchanged_lower_checks(self):
        run = self.published()
        old_plan = run.state["plan"]
        old_head = self.remote_head("part-1")
        original = (run.pr_dir(run.entry(1)) / "review-brief.md").read_bytes()
        repair.begin(run, 2, "CI failed in upper PR")
        self.assertNotIn("approval", run.state)
        self.assertEqual(run.entry(1)["lease"], old_head)
        self.commit_repair(run, "two.txt", "repaired upper\n")
        self.accept_repair(run)
        repair.restack(run)
        real_command = core.command
        checks = []
        def count(argv, **kwargs):
            if argv[0] == sys.executable:
                checks.append(kwargs.get("cwd"))
            return real_command(argv, **kwargs)
        with patch.object(core, "command", side_effect=count):
            run.verify()
        self.assertEqual(len(checks), 1)
        self.assertTrue(run.state["verification"]["results"][0]["reused"])
        self.assertEqual((run.pr_dir(run.entry(1)) / "review-brief.md").read_bytes(), original)
        self.assertNotEqual(run.plan()["digest"], old_plan)
        run.approve(run.state["plan"])
        run.push()
        self.assertEqual(self.remote_head("part-1"), old_head)
        self.assertEqual(self.remote_head("part-2"), run.entry(2)["new"])
        self.assertEqual(len(run.state["repairs"]), 1)

    def test_repair_conflict_preserves_work_and_resumes(self):
        (self.source / "one.txt").write_text("upper intent\n")
        self.g("add", "one.txt")
        self.g("commit", "-m", "upper intent")
        self.g("push", "origin", "part-2")
        run = self.completed(False)
        repair.begin(run, 1, "fix lower regression")
        self.commit_repair(run)
        self.accept_repair(run)
        with self.assertRaises(core.Error):
            repair.restack(run)
        worktree = run.worktree(run.entry(2))
        self.assertIn("<<<<<<<", (worktree / "one.txt").read_text())
        (worktree / "one.txt").write_text("upper intent with repair\n")
        core.git(worktree, "add", "one.txt")
        run = core.Run(self.home, run.state["id"])
        repair.restack(run, resume=True)
        run.verify()
        self.assertNotIn("active_repair", run.state)

    def test_repair_rejects_unreviewed_scope_stale_heads_and_excess_rounds(self):
        run = self.start(number=1, scope="single")
        self.no_findings(run, 1)
        run.restack()
        run.verify()
        with self.assertRaisesRegex(core.Error, "expand review scope"):
            repair.begin(run, 2, "fix upper")
        run.cfg["max_repair_rounds"] = 1
        repair.begin(run, 1, "one bounded repair")
        self.commit_repair(run)
        self.accept_repair(run)
        repair.restack(run)
        with self.assertRaisesRegex(core.Error, "limit reached"):
            repair.begin(run, 1, "another repair")

    def test_repair_reviewer_can_reject_and_stale_review_cannot_approve_new_head(self):
        run = self.completed()
        repair.begin(run, 1, "reproduced bug")
        self.commit_repair(run)
        current = run.state["active_repair"]
        file = Path(current["directory"]) / "review.json"
        core.atomic_json(file, {"head": "a" * 40, "findings": []})
        with self.assertRaisesRegex(core.Error, "current fix head"):
            repair.record_review(run)
        core.atomic_json(file, {"head": current["head"], "findings": [{"id": "repair-1", "axis": "spec", "severity": "bug",
            "file": "one.txt", "line": 1, "summary": "still wrong", "evidence": "a concrete failure remains"}]})
        result = repair.record_review(run)
        self.assertFalse(result["accepted"])
        self.assertEqual(run.next()["action"], "repair-fix")
        self.commit_repair(run, content="second repair\n")
        self.accept_repair(run)
        repair.restack(run)

    def test_cancel_only_restores_an_unchanged_repair(self):
        run = self.completed()
        old_plan = run.plan()
        repair.begin(run, 1, "investigate")
        repair.cancel(run)
        self.assertEqual(run.state["plan"], old_plan["digest"])
        repair.begin(run, 1, "real fix")
        self.commit_repair(run)
        with self.assertRaisesRegex(core.Error, "unchanged repair"):
            repair.cancel(run)

    def test_ci_pending_and_pass_are_checkpointed_without_waiting(self):
        run = self.published()
        self.assertEqual(run.next()["action"], "ci-start")
        with patch.object(ci, "command", side_effect=self.github(run, {1: "pending", 2: "pass"})):
            result = ci.check(run)
        self.assertEqual(result["action"], "ci-pending")
        self.assertTrue((run.directory / "ci/FOLLOWUP.md").exists())
        with patch.object(ci, "command", side_effect=self.github(run)):
            ci.check(run)
            ci.check(run, now=run.state["ci"]["pass_candidate_at"] + run.cfg["ci"]["poll_interval"])
        self.assertEqual(run.next()["action"], "done")
        self.assertEqual(run.state["ci"]["state"], "passed")

    def test_ci_missing_skipped_cancelled_expected_and_timeout_are_not_green(self):
        run = self.published()
        for bucket, expected in (("absent", "pending"), ("skipping", "attention"), ("cancel", "attention")):
            with patch.object(ci, "command", side_effect=self.github(run, {1: bucket, 2: "pass"})):
                ci.check(run)
            self.assertEqual(run.state["ci"]["state"], expected)
        run.cfg["ci"]["expected_checks"] = ["a required check not returned yet"]
        with patch.object(ci, "command", side_effect=self.github(run)):
            ci.check(run)
            self.assertEqual(run.state["ci"]["state"], "pending")
            ci.check(run, now=run.state["ci"]["deadline"] + 1)
        self.assertEqual(run.state["ci"]["state"], "timed_out")

    def test_ci_ignores_old_api_heads_and_stops_after_remote_branch_moves(self):
        run = self.published()
        with patch.object(ci, "command", side_effect=self.github(run, {1: "fail", 2: "fail"}, api_lag=True)):
            ci.check(run)
        self.assertEqual(run.state["ci"]["state"], "pending")
        self.g("push", "--force", "origin", f"{self.second}:refs/heads/part-2")
        with patch.object(ci, "command") as api:
            ci.check(run)
            api.assert_not_called()
        self.assertEqual(run.state["ci"]["state"], "superseded")
        with self.assertRaisesRegex(core.Error, "moved"):
            repair.begin(run, 2, "must not fix stale code")

    def test_ci_failures_produce_exact_head_logs_and_an_actionable_handoff(self):
        run = self.published()
        with patch.object(ci, "command", side_effect=self.github(run, {1: "fail", 2: "pending"})):
            ci.check(run)
            result = ci.logs(run, 1)
        self.assertEqual(run.next()["action"], "ci-triage")
        self.assertIn("failed assertion", Path(result["logs"][0]["path"]).read_text())
        with patch.object(ci, "command", side_effect=self.github(run, {1: "fail", 2: "pending"}, log_head="b" * 40)):
            with self.assertRaisesRegex(core.Error, "different commit"):
                ci.logs(run, 1)
        self.assertIn("NEEDS-USER", (run.directory / "ci/FOLLOWUP.md").read_text())

    def test_ci_observation_errors_are_unknown_not_test_failures(self):
        run = self.published()
        with patch.object(ci, "command", side_effect=core.Error("network unavailable")):
            ci.check(run)
        self.assertEqual(run.state["ci"]["state"], "unavailable")
        self.assertNotEqual(run.next()["action"], "done")

    def test_ci_stable_success_is_independent_of_check_order(self):
        run = self.published()
        original = self.github(run)
        reverse = [False]
        def ordered(argv, **kwargs):
            if argv[:3] == ["gh", "pr", "checks"]:
                checks = [{"name": name, "bucket": "pass", "link": "", "state": "COMPLETED", "workflow": "CI"}
                          for name in ("lint", "tests")]
                return subprocess.CompletedProcess(argv, 0, json.dumps(list(reversed(checks)) if reverse[0] else checks), "")
            return original(argv, **kwargs)
        with patch.object(ci, "command", side_effect=ordered):
            ci.check(run)
            self.assertEqual(run.state["ci"]["state"], "pending")
            reverse[0] = True
            ci.check(run, now=run.state["ci"]["pass_candidate_at"] + run.cfg["ci"]["poll_interval"])
        self.assertEqual(run.state["ci"]["state"], "passed")

    def test_ci_logs_recheck_a_recovered_failure_before_fetching_old_logs(self):
        run = self.published()
        with patch.object(ci, "command", side_effect=self.github(run, {1: "fail", 2: "pass"})):
            ci.check(run)
        with patch.object(ci, "command", side_effect=self.github(run)):
            with self.assertRaisesRegex(core.Error, "No failed check observation"):
                ci.logs(run, 1)
        self.assertNotEqual(run.state["ci"]["state"], "failed")

    def test_cli_repair_routes_published_runs_to_controlled_revision(self):
        run = self.published()
        args = parser().parse_args(["--home", str(self.home), "repair", "begin", "--run", run.state["id"],
                                    "--pr", "1", "--reason", "the current CI failure is reproduced"])
        result = dispatch(args)
        self.assertTrue(Path(result["brief"]).is_file())
        run = core.Run(self.home, run.state["id"])
        self.assertFalse(run.state["pushed"])
        self.assertEqual(run.next()["action"], "repair-fix")
        result = dispatch(parser().parse_args(["--home", str(self.home), "repair", "cancel", "--run", run.state["id"]]))
        self.assertIn("cancelled", result)
        self.assertTrue(core.Run(self.home, run.state["id"]).state["pushed"])

    def test_background_watcher_polls_without_an_agent_and_exits_on_success(self):
        run = self.published()
        run.cfg["ci"].update(poll_interval=1, timeout=10)
        run.save()
        fake_bin = self.root / "fake-bin"
        fake_bin.mkdir()
        fake_gh = fake_bin / "gh"
        heads = run.heads()
        fake_gh.write_text(f"#!{sys.executable}\nimport json,sys\na=sys.argv[1:]\nheads={heads!r}\n"
                           f"from pathlib import Path\ncounter=Path({str(fake_bin / 'calls')!r})\n"
                           "if a[:2]==['pr','view']: print(json.dumps({'headRefOid':heads[a[2]]}))\n"
                           "elif a[:2]==['pr','checks']:\n n=int(counter.read_text())+1 if counter.exists() else 1\n counter.write_text(str(n))\n print(json.dumps([{'name':'tests','bucket':'pending' if n<3 else 'pass','state':'IN_PROGRESS' if n<3 else 'SUCCESS','link':'','workflow':'CI'}]))\n"
                           "else: sys.exit(2)\n")
        fake_gh.chmod(0o755)
        env = {**os.environ, "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
               "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
        launched = subprocess.run([sys.executable, "-m", "stack_review", "--home", str(self.home),
                                  "ci", "watch", "--run", run.state["id"]], env=env,
                                 capture_output=True, text=True, timeout=3)
        self.assertEqual(launched.returncode, 0, launched.stderr)
        result = json.loads(launched.stdout)
        self.assertFalse(result["agent_wait_required"])
        deadline = time.monotonic() + 12
        try:
            while time.monotonic() < deadline:
                observed = core.Run(self.home, run.state["id"])
                if observed.state.get("ci", {}).get("state") == "passed" and not observed.state["ci"].get("worker_token"):
                    break
                time.sleep(0.1)
            else:
                self.fail((run.directory / "ci/worker.log").read_text())
            self.assertEqual(observed.state["ci"]["state"], "passed")
        finally:
            # Stopping clears a generation token, never signals an unrelated PID.
            observed = core.Run(self.home, run.state["id"])
            if observed.state["ci"].get("worker_token"):
                with core.lock(observed.directory):
                    ci.stop(observed)

    def test_ci_find_and_read_only_status_do_not_create_a_new_review(self):
        run = self.published()
        result = ci.find(self.home, self.source, 1)
        self.assertEqual(result[0]["run"], run.state["id"])
        state_file = run.directory / "run.json"
        before = state_file.read_bytes()
        args = parser().parse_args(["--home", str(self.home), "ci", "status", "--run", run.state["id"]])
        dispatch(args)
        self.assertEqual(state_file.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
