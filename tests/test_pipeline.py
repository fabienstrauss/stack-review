"""Integration tests use temporary repositories and bare remotes, never user checkouts."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stack_review import core
from stack_review.cli import dispatch, install_skill, parser
from stack_review import onboarding


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.remote = self.root / "remote.git"
        self.home = self.root / "runtime"
        self.source.mkdir()
        self.g("init", "-b", "main")
        self.g("config", "user.name", "Test")
        self.g("config", "user.email", "test@example.invalid")
        (self.source / "base.txt").write_text("base owned by someone else\n")
        self.g("add", "base.txt")
        self.g("commit", "-m", "base")
        self.base = self.g("rev-parse", "HEAD")
        self.g("switch", "-c", "part-1")
        (self.source / "one.txt").write_text("original first\n")
        self.g("add", "one.txt")
        self.g("commit", "-m", "add first")
        self.first = self.g("rev-parse", "HEAD")
        self.g("switch", "-c", "part-2")
        (self.source / "two.txt").write_text("original second\n")
        self.g("add", "two.txt")
        self.g("commit", "-m", "add second")
        self.second = self.g("rev-parse", "HEAD")
        core.command(["git", "init", "--bare", str(self.remote)])
        self.g("remote", "add", "origin", str(self.remote))
        self.g("push", "origin", "main", "part-1", "part-2")
        self.manifest = self.root / "manifest.json"
        core.atomic_json(self.manifest, [
            {"number": 1, "headRefName": "part-1", "baseRefName": "main", "title": "One", "body": "First"},
            {"number": 2, "headRefName": "part-2", "baseRefName": "part-1", "title": "Two", "body": "Second"},
        ])
        self.config = self.root / "settings.json"
        self.config_data = {"checkout": str(self.source), "repository": "test/project",
                            "checks": [{"name": "files exist", "argv": [sys.executable, "-c",
                                       "from pathlib import Path; assert Path('one.txt').is_file()"]}]}
        core.atomic_json(self.config, self.config_data)

    def g(self, *args):
        return core.git(self.source, *args)

    def start(self, **options):
        options.setdefault("again", True)
        return core.Run(self.home, core.create(self.home, self.config, manifest=self.manifest, **options))

    def finding(self, run, number=1):
        p = run.entry(number)
        core.atomic_json(run.pr_dir(p) / "findings.json", [{
            "id": f"{number}-S1", "axis": "standards", "severity": "bug", "file": "one.txt",
            "line": 1, "summary": "first needs correction", "evidence": "concrete failure"}])
        run.record_review(number)
        run.prepare(number)

    def fix(self, run, number=1, filename="one.txt", content="corrected first\n"):
        p = run.entry(number)
        wt = run.worktree(p)
        (wt / filename).write_text(content)
        core.git(wt, "add", filename)
        core.git(wt, "commit", "-m", "correct first")
        sha = core.git(wt, "rev-parse", "HEAD")
        core.atomic_json(run.pr_dir(p) / "verdicts.json", [{"id": f"{number}-S1", "verdict": "FIX",
                         "reason": "verified against real input", "commit": sha}])
        return sha

    def no_findings(self, run, number):
        core.atomic_json(run.pr_dir(run.entry(number)) / "findings.json", [])
        run.record_review(number)

    def completed(self, with_fix=True):
        run = self.start()
        if with_fix:
            self.finding(run)
            self.fix(run)
            run.record_fix(1)
        else:
            self.no_findings(run, 1)
        self.no_findings(run, 2)
        run.restack()
        run.verify()
        return run

    def test_end_to_end_fix_restack_verify_approve_atomic_publish(self):
        (self.source / "uncommitted.txt").write_text("another session's work\n")
        before = self.g("status", "--porcelain")
        run = self.completed()
        p1, p2 = run.state["prs"]
        self.assertNotEqual(p1["new"], self.first)
        self.assertEqual(core.git(run.worktree(p2), "show", "HEAD:one.txt"), "corrected first")
        self.assertEqual(len(run.state["verification"]["results"]), 2)
        planned = run.plan()
        run.push(dry_run=True)
        with self.assertRaisesRegex(core.Error, "approval"):
            run.push()
        run.approve(planned["digest"])
        run.push()
        self.assertEqual(self.remote_head("part-1"), p1["new"])
        self.assertEqual(self.remote_head("part-2"), p2["new"])
        self.assertEqual(self.g("status", "--porcelain"), before)
        self.assertEqual(self.g("rev-parse", "HEAD"), self.second)
        self.assertTrue(run.state["pushed"])

    def remote_head(self, branch):
        return core.command(["git", "--git-dir", str(self.remote), "rev-parse", f"refs/heads/{branch}"]).stdout.strip()

    def test_two_runs_do_not_share_objects_refs_worktrees_or_config(self):
        a, b = self.start(), self.start()
        self.assertNotEqual(a.directory, b.directory)
        self.finding(a)
        self.finding(b)
        self.fix(a)
        a.record_fix(1)
        self.assertEqual(core.git(b.worktree(b.entry(1)), "show", "HEAD:one.txt"), "original first")
        self.assertNotEqual(core.git(a.repo, "rev-parse", "--git-common-dir"), "../source/.git")
        self.assertFalse((a.repo / ".git/objects/info/alternates").exists())
        self.config_data["standing_decisions"] = ["changed outside run"]
        core.atomic_json(self.config, self.config_data)
        self.assertEqual(core.Run(self.home, a.state["id"]).cfg["standing_decisions"], [])

    def test_remote_movement_blocks_whole_stack(self):
        run = self.completed()
        plan = run.plan()
        run.approve(plan["digest"])
        (self.source / "other.txt").write_text("parallel session\n")
        self.g("add", "other.txt")
        self.g("commit", "-m", "parallel change")
        self.g("push", "origin", "part-2")
        with self.assertRaisesRegex(core.Error, "moved"):
            run.push()
        self.assertEqual(self.remote_head("part-1"), self.first)

    def test_remote_movement_between_preflight_and_push_is_atomic(self):
        run = self.completed()
        plan = run.plan()
        run.approve(plan["digest"])
        (self.source / "parallel.txt").write_text("new remote content\n")
        self.g("add", "parallel.txt")
        self.g("commit", "-m", "racing session")
        moved = self.g("rev-parse", "HEAD")
        # Transfer the object without moving either approved branch.
        self.g("push", "origin", "HEAD:refs/heads/racing-object")
        original_git = core.git

        def racing_git(repo, *args, **kwargs):
            if args and args[0] == "push":
                core.command(["git", "--git-dir", str(self.remote), "update-ref", "refs/heads/part-2", moved])
            return original_git(repo, *args, **kwargs)

        with patch.object(core, "git", side_effect=racing_git):
            with self.assertRaises(core.Error):
                run.push()
        self.assertEqual(self.remote_head("part-1"), self.first)
        self.assertEqual(self.remote_head("part-2"), moved)

    def test_changed_base_invalidates_frozen_context(self):
        run = self.completed()
        plan = run.plan()
        run.approve(plan["digest"])
        self.g("switch", "main")
        (self.source / "base-update.txt").write_text("changed context\n")
        self.g("add", "base-update.txt")
        self.g("commit", "-m", "base evolves")
        self.g("push", "origin", "main")
        with self.assertRaisesRegex(core.Error, "base moved"):
            run.push()
        self.assertEqual(self.remote_head("part-1"), self.first)

    def test_equal_commit_subjects_do_not_drop_unrelated_changes(self):
        (self.source / "two.txt").write_text("upper change with same commit title\n")
        self.g("add", "two.txt")
        self.g("commit", "-m", "correct first")
        self.g("push", "origin", "part-2")
        run = self.completed()
        self.assertEqual(core.git(run.worktree(run.entry(2)), "show", "HEAD:two.txt"), "upper change with same commit title")

    def test_conflict_survives_other_run_and_can_continue(self):
        # Upper PR edits a line the lower PR's fix will also edit.
        (self.source / "one.txt").write_text("upper intent\n")
        self.g("add", "one.txt")
        self.g("commit", "-m", "upper modifies first")
        self.g("push", "origin", "part-2")
        a = self.start()
        self.finding(a)
        self.fix(a)
        a.record_fix(1)
        self.no_findings(a, 2)
        with self.assertRaises(core.Error):
            a.restack()
        paused = a.worktree(a.entry(2))
        conflict = (paused / "one.txt").read_text()
        b = self.completed(False)
        self.assertEqual((paused / "one.txt").read_text(), conflict)
        self.assertNotEqual(a.directory, b.directory)
        (paused / "one.txt").write_text("upper intent plus correction\n")
        core.git(paused, "add", "one.txt")
        a = core.Run(self.home, a.state["id"])
        a.restack(resume=True)
        a.verify()
        self.assertTrue(a.state["restacked"])

    def test_compiler_failure_and_timeout_never_produce_approval(self):
        for script in ("import sys; sys.stderr.write('startup failed'); sys.exit(2)", "import time; time.sleep(3)"):
            self.config_data["checks"] = [{"name": "broken", "argv": [sys.executable, "-c", script]}]
            self.config_data["command_timeout"] = 1
            core.atomic_json(self.config, self.config_data)
            run = self.start()
            self.no_findings(run, 1)
            self.no_findings(run, 2)
            run.restack()
            with self.assertRaisesRegex(core.Error, "Verification failed"):
                run.verify()
            with self.assertRaisesRegex(core.Error, "Verify"):
                run.plan()
            self.assertNotIn("verification", run.state)

    def test_missing_command_and_no_checks_block_verification(self):
        for checks in ([], [{"name": "missing", "argv": ["/no/such/check"]}]):
            self.config_data["checks"] = checks
            core.atomic_json(self.config, self.config_data)
            run = self.start()
            self.no_findings(run, 1)
            self.no_findings(run, 2)
            run.restack()
            with self.assertRaises(core.Error):
                run.verify()
            self.assertNotIn("verification", run.state)

    def test_explicit_skips_are_configurable_and_visible(self):
        run = self.completed(False)
        with self.assertRaisesRegex(core.Error, "Skipping"):
            run.verify("documentation only")
        self.config_data.update(checks=[], allow_skip_checks=True)
        core.atomic_json(self.config, self.config_data)
        run = self.start()
        self.no_findings(run, 1)
        self.no_findings(run, 2)
        run.restack()
        run.verify("documentation only")
        self.assertIn("documentation only", core.canonical(run.publication()))

    def test_body_change_invalidates_exact_approval(self):
        run = self.completed()
        plan = run.plan()
        run.approve(plan["digest"])
        (run.pr_dir(run.entry(1)) / "body.new.md").write_text("New description\n")
        with self.assertRaisesRegex(core.Error, "changed"):
            run.push()
        refreshed = run.plan()
        self.assertNotEqual(refreshed["digest"], plan["digest"])
        self.assertNotIn("approval", run.state)

    def test_recorded_verdict_edits_cannot_silently_change_approved_evidence(self):
        run = self.completed()
        plan = run.plan()
        run.approve(plan["digest"])
        path = run.pr_dir(run.entry(1)) / "verdicts.json"
        verdicts = core.read_json(path)
        verdicts[0]["reason"] = "different reasoning after approval"
        core.atomic_json(path, verdicts)
        with self.assertRaisesRegex(core.Error, "verdicts changed"):
            run.push()

    def test_changed_local_head_and_dirty_verification_block_publication(self):
        run = self.completed()
        worktree = run.worktree(run.entry(1))
        (worktree / "temporary.txt").write_text("leftover")
        with self.assertRaisesRegex(core.Error, "uncommitted"):
            run.plan()
        core.git(worktree, "add", "temporary.txt")
        core.git(worktree, "commit", "-m", "unrecorded change")
        with self.assertRaisesRegex(core.Error, "moved"):
            run.plan()

    def test_findings_verdicts_and_commit_coverage_are_validated(self):
        run = self.start()
        file = run.pr_dir(run.entry(1)) / "findings.json"
        core.atomic_json(file, [{"id": "bad"}])
        with self.assertRaises(core.Error):
            run.record_review(1)
        self.finding(run)
        self.fix(run)
        core.atomic_json(run.pr_dir(run.entry(1)) / "verdicts.json", [])
        with self.assertRaisesRegex(core.Error, "Every finding"):
            run.record_fix(1)

    def test_ownership_uses_file_and_line_not_matching_text(self):
        # A base line matching text added elsewhere must not be treated as stack-owned.
        (self.source / "one.txt").write_text("base owned by someone else\n")
        self.g("add", "one.txt")
        self.g("commit", "-m", "same text in stack file")
        self.g("push", "origin", "part-2")
        run = self.start()
        self.finding(run)
        self.fix(run, filename="base.txt", content="changed someone else's base line\n")
        with self.assertRaisesRegex(core.Error, "outside the stack"):
            run.record_fix(1)
        audit = core.read_json(run.pr_dir(run.entry(1)) / "ownership.json")
        self.assertEqual(audit[0]["file"], "base.txt")

    def test_ownership_handles_tabs_dash_lines_and_binary_base_files(self):
        path = "unusual\tname.txt"
        (self.source / path).write_text("-- base line\n")
        (self.source / "binary.bin").write_bytes(b"old\x00binary")
        self.g("add", path, "binary.bin")
        self.g("commit", "-m", "new base fixtures")
        before = self.g("rev-parse", "HEAD")
        (self.source / path).write_text("new line\n")
        (self.source / "binary.bin").write_bytes(b"new\x00binary")
        self.g("add", path, "binary.bin")
        self.g("commit", "-m", "modify base fixtures")
        after = self.g("rev-parse", "HEAD")
        audit = core.ownership_audit(self.source, before, before, after)
        self.assertEqual({item["file"] for item in audit}, {path, "binary.bin"})

    def test_report_ownership_policy_exposes_base_edits(self):
        self.config_data["ownership_policy"] = "report"
        core.atomic_json(self.config, self.config_data)
        run = self.start()
        self.finding(run)
        self.fix(run, filename="base.txt", content="minimal required change\n")
        run.record_fix(1)
        self.no_findings(run, 2)
        run.restack()
        run.verify()
        self.assertEqual(run.publication()["prs"][0]["ownership_audit"][0]["file"], "base.txt")

    def test_forbidden_path_in_intermediate_commit_is_rejected(self):
        run = self.start()
        self.finding(run)
        p = run.entry(1)
        wt = run.worktree(p)
        (wt / ".env").write_text("placeholder, not a secret\n")
        core.git(wt, "add", ".env")
        core.git(wt, "commit", "-m", "bad intermediate")
        first = core.git(wt, "rev-parse", "HEAD")
        core.git(wt, "rm", ".env")
        core.git(wt, "commit", "-m", "remove intermediate")
        second = core.git(wt, "rev-parse", "HEAD")
        core.atomic_json(run.pr_dir(p) / "verdicts.json", [{"id": "1-S1", "verdict": "FIX", "reason": "test", "commit": first}])
        # First ensure all commits are represented, then check the path guard independently.
        with self.assertRaises(core.Error):
            run.record_fix(1)
        p["findings"].append({**p["findings"][0], "id": "1-S2"})
        core.atomic_json(run.pr_dir(p) / "verdicts.json", [
            {"id": "1-S1", "verdict": "FIX", "reason": "test", "commit": first},
            {"id": "1-S2", "verdict": "FIX", "reason": "test", "commit": second}])
        with self.assertRaisesRegex(core.Error, "forbidden path"):
            run.record_fix(1)

    def test_partial_body_publication_resumes_without_overwriting_external_edits(self):
        run = self.completed()
        body = run.pr_dir(run.entry(1)) / "body.new.md"
        body.write_text("Corrected description")
        plan = run.plan()
        run.approve(plan["digest"])
        original_command = core.command
        calls = []
        current_body = ["First"]

        def fake(argv, **kwargs):
            if argv[:3] == ["gh", "pr", "view"]:
                return subprocess.CompletedProcess(argv, 0, json.dumps({"body": current_body[0]}), "")
            if argv[:3] == ["gh", "pr", "edit"]:
                calls.append(argv)
                if len(calls) == 1:
                    raise core.Error("temporary body update failure")
                current_body[0] = body.read_text()
                return subprocess.CompletedProcess(argv, 0, "", "")
            return original_command(argv, **kwargs)

        with patch.object(core, "command", side_effect=fake):
            with self.assertRaisesRegex(core.Error, "temporary body"):
                run.push()
            self.assertTrue(run.state["publication"]["branches"])
            self.assertEqual(self.remote_head("part-1"), run.entry(1)["new"])
            run = core.Run(self.home, run.state["id"])
            resumed = core.create(self.home, self.config, manifest=self.manifest, again=True, resume_run=run.state["id"])
            self.assertEqual(resumed, run.state["id"])
            current_body[0] = "Another person's edit"
            with self.assertRaisesRegex(core.Error, "body changed"):
                run.push()
            current_body[0] = "First"
            run.push()
        self.assertTrue(run.state["pushed"])
        self.assertEqual(run.state["publication"]["bodies"], [1])

    def test_kernel_lock_blocks_other_process_and_releases_after_exit(self):
        run = self.start()
        script = "from stack_review.core import lock; from pathlib import Path; import sys;\nwith lock(Path(sys.argv[1])): print('acquired')"
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
        with core.lock(run.directory):
            result = subprocess.run([sys.executable, "-c", script, str(run.directory)], env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Another command owns", result.stderr)
        result = subprocess.run([sys.executable, "-c", script, str(run.directory)], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)

    def test_read_only_commands_do_not_execute_settings_or_change_files(self):
        sentinel = self.root / "should-not-exist"
        self.config_data["setup_commands"] = [{"name": "never run by doctor", "argv": [sys.executable, "-c", f"open({str(sentinel)!r},'w').close()"]}]
        core.atomic_json(self.config, self.config_data)
        args = parser().parse_args(["--home", str(self.home), "doctor", "--settings", str(self.config)])
        result = dispatch(args)
        self.assertEqual(result["skill_loaded"], "unknown")
        self.assertFalse(sentinel.exists())
        self.assertFalse(self.home.exists())

    def test_project_discovery_never_executes_manifest_scripts_or_writes_settings(self):
        sentinel = self.root / "never-run"
        core.atomic_json(self.source / "package.json", {"scripts": {"test": f"touch {sentinel}", "deploy": "do not run"}})
        (self.source / "pnpm-lock.yaml").write_text("lockfileVersion: 9\n")
        (self.source / "AGENTS.md").write_text("Read project rules before running tests.\n")
        observed = onboarding.inspect(self.home, self.source)
        self.assertEqual(observed["proposal"]["checks"][0]["argv"], ["pnpm", "run", "test"])
        self.assertEqual(observed["proposal"]["context_files"], ["AGENTS.md"])
        self.assertFalse(sentinel.exists())
        self.assertFalse(self.home.exists())
        self.assertNotIn(str(sentinel), core.canonical(observed))

    def test_guided_configuration_and_start_need_no_settings_argument(self):
        tests = self.source / "tests"
        tests.mkdir()
        (tests / "test_example.py").write_text("import unittest\n")
        result = onboarding.configure(self.home, self.source, repository="test/project")
        self.assertFalse(result["reused"])
        path = Path(result["settings"])
        self.assertTrue(path.is_relative_to(self.home.resolve()))
        self.assertFalse(path.is_relative_to(self.source.resolve()))
        cfg = core.settings(path)
        self.assertEqual(cfg["checks"][0]["argv"], ["python3", "-m", "unittest", "discover", "-s", "tests"])
        (self.source / "subdir").mkdir()
        again = onboarding.configure(self.home, self.source / "subdir", checks=["should not replace saved settings"])
        self.assertTrue(again["reused"])
        self.assertEqual(core.settings(path), cfg)
        args = parser().parse_args(["--home", str(self.home), "start", "--checkout", str(self.source), "--manifest", str(self.manifest)])
        result = dispatch(args)
        self.assertEqual(core.Run(self.home, result["run"]).cfg["checks"], cfg["checks"])

    def test_configure_overrides_and_saved_preferences_are_preserved(self):
        marker = self.root / "setup-never-run"
        result = onboarding.configure(self.home, self.source, repository="test/project", checks=["python3 -m unittest"],
                                      setup=[f"python3 -c {repr('print(123)')}"], contexts=["AGENTS.md"])
        first = core.settings(result["settings"])
        onboarding.configure(self.home, self.source, checks=['python3 -c "print(456)"'], replace=True)
        changed = core.settings(result["settings"])
        self.assertEqual(changed["setup_commands"], first["setup_commands"])
        self.assertEqual(changed["context_files"], ["AGENTS.md"])
        self.assertEqual(changed["checks"][0]["argv"], ["python3", "-c", "print(456)"])
        self.assertFalse(marker.exists())

    def test_unknown_checks_and_ambiguous_remotes_require_agent_choice(self):
        with self.assertRaisesRegex(core.Error, "infer the GitHub"):
            onboarding.configure(self.home, self.source)
        with self.assertRaisesRegex(core.Error, "No verification"):
            onboarding.configure(self.home, self.source, repository="test/project")
        self.assertFalse(self.home.exists())
        self.g("remote", "rename", "origin", "upstream")
        self.g("remote", "add", "fork", str(self.remote))
        with self.assertRaisesRegex(core.Error, "remote"):
            onboarding.configure(self.home, self.source, repository="test/project", checks=["python3 -m unittest"])
        result = onboarding.configure(self.home, self.source, repository="test/project", remote="upstream", checks=["python3 -m unittest"])
        self.assertEqual(core.settings(result["settings"])["remote"], "upstream")


class ContractTests(unittest.TestCase):
    def test_github_remote_detection_never_returns_credentials(self):
        for url in ("git@github.com:someone/project.git", "https://github.com/someone/project.git",
                    "https://placeholder-token@github.com/someone/project.git", "ssh://git@github.com/someone/project.git"):
            self.assertEqual(onboarding.repository_name(url), "someone/project")
        self.assertIsNone(onboarding.repository_name("/local/remote.git"))

    def test_forks_cycles_and_non_contiguous_manifests_rejected(self):
        def pr(n, head, base):
            return {"number": n, "headRefName": head, "baseRefName": base}
        with self.assertRaisesRegex(core.Error, "fork"):
            core.chain([pr(1, "a", "main"), pr(2, "b", "a"), pr(3, "c", "a")], 1)
        with self.assertRaisesRegex(core.Error, "Cycle"):
            core.chain([pr(1, "a", "b"), pr(2, "b", "a")], 1)
        with self.assertRaisesRegex(core.Error, "contiguous"):
            core.validate_manifest([pr(1, "a", "main"), pr(2, "b", "main")])

    def test_settings_reject_typos_shell_strings_and_escaping_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            for extra in ({"chekcs": []}, {"checks": [{"name": "bad", "argv": "echo hi"}]},
                          {"checks": [{"name": "bad", "argv": ["echo"], "cwd": "../outside"}]},
                          {"command_timeout": 0}, {"ownership_policy": "silently-ignore"}):
                core.atomic_json(path, {"checkout": ".", "repository": "test/project", **extra})
                with self.assertRaises(core.Error):
                    core.settings(path)

    def test_run_path_traversal_is_rejected(self):
        with self.assertRaises(core.Error):
            core.Run("/tmp", "../../outside")

    def test_both_installers_ship_shared_workflow_and_refuse_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for host in ("hermes", "claude"):
                target = root / host / "stack-review"
                install_skill(host, target)
                self.assertTrue((target / "workflow.md").is_file())
                self.assertIn("name: stack-review", (target / "SKILL.md").read_text())
                self.assertTrue((target / "runner.md").is_file())
                self.assertTrue((target / "runner.py").is_file())
                env = {**os.environ, "PATH": ""}
                result = subprocess.run([sys.executable, str(target / "runner.py"), "--help"], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                with self.assertRaises(core.Error):
                    install_skill(host, target)

    def test_standalone_installer_runs_from_path_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix="stack review ") as temporary:
            root = Path(temporary)
            package = Path(__file__).resolve().parents[1]
            result = subprocess.run([sys.executable, str(package / "install.py"), "--prefix", str(root / "tool"),
                                     "--host", "claude", "--skills-dir", str(root / "skill")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(root / "tool/bin/stack-review"), "--help"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("record-review", result.stdout)

    def test_installer_supports_both_hosts_without_path_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = Path(__file__).resolve().parents[1]
            env = {**os.environ, "HOME": str(root), "HERMES_HOME": str(root / ".hermes")}
            result = subprocess.run([sys.executable, str(package / "install.py"), "--prefix", str(root / "tool"),
                                     "--host", "both"], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for host in (".hermes", ".claude"):
                runner = root / host / "skills/stack-review/runner.py"
                result = subprocess.run([sys.executable, str(runner), "--help"], env={**env, "PATH": ""}, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_install_without_flags_only_asks_which_host(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = Path(__file__).resolve().parents[1]
            env = {**os.environ, "HOME": str(root), "HERMES_HOME": str(root / ".hermes")}
            result = subprocess.run([sys.executable, str(package / "install.py")], input="2\n", env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((root / ".claude/skills/stack-review/runner.py").is_file())
            self.assertFalse((root / ".hermes").exists())

    def test_install_conflict_does_not_leave_a_new_prefix(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            existing = root / "existing-skill"
            existing.mkdir()
            (existing / "SKILL.md").write_text("existing skill")
            package = Path(__file__).resolve().parents[1]
            result = subprocess.run([sys.executable, str(package / "install.py"), "--prefix", str(root / "tool"),
                                     "--host", "hermes", "--skills-dir", str(existing)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((root / "tool").exists())
            self.assertEqual((existing / "SKILL.md").read_text(), "existing skill")

    def test_distribution_archive_is_complete_and_installs_without_source_checkout(self):
        package = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = subprocess.run([sys.executable, str(package / "package.py"), "--output", str(root / "release.zip")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            with zipfile.ZipFile(root / "release.zip") as archive:
                names = archive.namelist()
                self.assertFalse(any("__pycache__" in n or "/runs/" in n or "/local/" in n for n in names))
                archive.extractall(root / "extracted")
            result = subprocess.run([sys.executable, str(root / "extracted/stack-review/install.py"),
                                     "--prefix", str(root / "installed"), "--host", "hermes",
                                     "--skills-dir", str(root / "hermes-skill")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((root / "hermes-skill/workflow.md").exists())
            result = subprocess.run([str(root / "installed/bin/stack-review"), "list", "--help"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
