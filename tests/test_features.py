"""Selection, reuse, dependency and installation lifecycle regression tests."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_pipeline as fixtures
from stack_review import core, onboarding, preflight
from stack_review.cli import dispatch, parser
from stack_review import installation


class ReviewFeatures(unittest.TestCase):
    setUp = fixtures.PipelineTests.setUp
    g = fixtures.PipelineTests.g
    start = fixtures.PipelineTests.start
    finding = fixtures.PipelineTests.finding
    fix = fixtures.PipelineTests.fix
    no_findings = fixtures.PipelineTests.no_findings
    completed = fixtures.PipelineTests.completed
    remote_head = fixtures.PipelineTests.remote_head

    def test_single_and_from_select_only_requested_reviews(self):
        single = self.start(number=2, scope="single")
        self.assertEqual(single.entry(1)["review"], "unselected")
        self.assertEqual(single.next()["pr"], 2)
        self.no_findings(single, 2)
        self.assertEqual(single.next()["action"], "restack")
        upward = self.start(number=2, scope="from")
        self.assertEqual([p["number"] for p in upward.state["prs"] if p["selected"]], [2])

    def test_single_lower_fix_carries_to_unreviewed_upper_and_is_disclosed(self):
        run = self.start(number=1, scope="single")
        self.finding(run)
        self.fix(run)
        run.record_fix(1)
        run.restack()
        run.verify()
        run.plan()
        self.assertFalse(run.publication()["prs"][1]["selected"])
        self.assertEqual(core.git(run.worktree(run.entry(2)), "show", "HEAD:one.txt"), "corrected first")
        self.assertIn("unselected upper PRs", (run.directory / "SUMMARY.md").read_text())

    def test_exact_reuse_skips_review_and_again_overrides_it(self):
        first = self.start(again=False)
        self.no_findings(first, 1)
        self.no_findings(first, 2)
        second = self.start(again=False)
        self.assertEqual([p["review"] for p in second.state["prs"]], ["cached", "cached"])
        self.assertEqual(second.next()["action"], "restack")
        forced = self.start(again=True)
        self.assertEqual([p["review"] for p in forced.state["prs"]], ["full", "full"])

    def test_changed_patch_gets_delta_and_changed_rules_get_full_review(self):
        first = self.start(again=False)
        self.no_findings(first, 1)
        self.no_findings(first, 2)
        self.g("switch", "part-1")
        (self.source / "one.txt").write_text("new first code\n")
        self.g("add", "one.txt")
        self.g("commit", "-m", "change first")
        self.g("push", "origin", "part-1")
        changed = self.start(again=False)
        self.assertEqual(changed.entry(1)["review"], "delta")
        self.assertIn("new first code", (changed.pr_dir(changed.entry(1)) / "changes-since-review.patch").read_text())
        self.config_data["standing_decisions"] = ["new project rule"]
        core.atomic_json(self.config, self.config_data)
        rules = self.start(again=False)
        self.assertEqual(rules.entry(1)["review"], "full")

    def test_cached_findings_still_require_independent_fix_evaluation(self):
        first = self.start(again=False)
        self.finding(first)
        second = self.start(again=False)
        self.assertEqual(second.entry(1)["review"], "cached")
        self.assertEqual(second.next()["action"], "fix")
        self.assertFalse(second.entry(1).get("prepared"))

    def test_settled_wontfix_is_reused_without_another_fixer(self):
        first = self.start(again=False)
        self.finding(first)
        core.atomic_json(first.pr_dir(first.entry(1)) / "verdicts.json", [{"id": "1-S1", "verdict": "WONTFIX", "reason": "expected behavior"}])
        first.record_fix(1)
        second = self.start(again=False)
        self.assertEqual(second.entry(1)["phase"], "done")
        self.assertEqual(second.entry(1)["verdicts"][0]["verdict"], "WONTFIX")

    def test_published_fixes_establish_next_review_baseline(self):
        first = self.completed()
        plan = first.plan()
        first.approve(plan["digest"])
        first.push()
        next_run = self.start(again=False)
        self.assertEqual(next_run.entry(1)["review"], "cached")
        self.assertEqual(next_run.entry(1)["phase"], "done")
        # Unselected or context-changed PRs must not be claimed as reviewed automatically.
        self.assertEqual(next_run.entry(2)["review"], "cached")

    def test_review_only_generates_findings_and_cannot_fix_restack_or_push(self):
        run = self.start(number=1, scope="single", review_only=True)
        p = run.entry(1)
        core.atomic_json(run.pr_dir(p) / "findings.json", [{"id": "bug", "axis": "spec", "severity": "bug",
            "file": "one.txt", "line": 1, "summary": "reported only", "evidence": "a concrete scenario"}])
        run.record_review(1)
        self.assertEqual(run.next()["action"], "report")
        for operation in (lambda: run.prepare(1), run.restack, run.push):
            with self.assertRaises(core.Error):
                operation()
        report = run.report()
        self.assertIn("reported only", Path(report["summary"]).read_text())
        self.assertEqual(run.next()["action"], "done")
        self.assertFalse((run.directory / "worktrees").exists())
        self.assertEqual(self.remote_head("part-1"), self.first)

    def test_resume_discovery_never_silently_takes_over_another_session(self):
        first = self.start(again=False)
        self.no_findings(first, 1)
        core.atomic_json(self.home / "runs/corrupted-unrelated/run.json", ["not a run object"])
        result = core.create(self.home, self.config, manifest=self.manifest, resume=True)
        self.assertEqual(result["resume_candidates"], [first.state["id"]])
        resumed = core.create(self.home, self.config, manifest=self.manifest, resume_run=first.state["id"])
        self.assertEqual(resumed, first.state["id"])
        self.assertEqual(core.Run(self.home, resumed).next()["pr"], 2)
        with self.assertRaisesRegex(core.Error, "no longer matches"):
            core.create(self.home, self.config, manifest=self.manifest, resume_run=resumed, instructions="different focus")
        independent = self.start(again=False)
        self.assertNotEqual(independent.state["id"], resumed)

    def test_saved_configuration_becomes_stale_when_manifests_or_notes_change(self):
        (self.source / "AGENTS.md").write_text("Original rules\n")
        result = onboarding.configure(self.home, self.source, repository="test/project", checks=["python3 -m unittest"])
        cfg = core.settings(result["settings"])
        self.assertFalse(onboarding.stale(result["settings"], cfg)["stale"])
        (self.source / "AGENTS.md").write_text("New test restrictions\n")
        self.assertTrue(onboarding.inspect(self.home, self.source)["settings_health"]["stale"])
        args = parser().parse_args(["--home", str(self.home), "start", "--checkout", str(self.source), "--manifest", str(self.manifest)])
        with self.assertRaisesRegex(core.Error, "changed"):
            dispatch(args)
        onboarding.configure(self.home, self.source, replace=True)
        self.assertFalse(onboarding.stale(result["settings"], cfg)["stale"])

    def test_specialists_required_missing_blocks_and_optional_missing_is_reported(self):
        self.config_data["specialist_skills"] = [{"name": "security", "path": str(self.root / "absent"), "required": True}]
        core.atomic_json(self.config, self.config_data)
        with self.assertRaisesRegex(core.Error, "Required specialist"):
            self.start()
        self.config_data["specialist_skills"][0]["required"] = False
        core.atomic_json(self.config, self.config_data)
        run = self.start(review_only=True)
        self.no_findings(run, 1)
        self.no_findings(run, 2)
        run.report()
        self.assertIn("security", (run.directory / "SUMMARY.md").read_text())

    def test_specialist_documents_are_frozen_and_changes_invalidate_cache(self):
        skill = self.root / "specialist"
        skill.mkdir()
        (skill / "SKILL.md").write_text("Review domain invariants.\n")
        self.config_data["specialist_skills"] = [{"name": "domain", "path": str(skill), "required": True}]
        core.atomic_json(self.config, self.config_data)
        first = self.start(again=False)
        self.no_findings(first, 1)
        (skill / "SKILL.md").write_text("Different domain guidance.\n")
        second = self.start(again=False)
        self.assertEqual(second.entry(1)["review"], "full")
        self.assertIn("Review domain invariants", (first.directory / "specialists.json").read_text())

    def test_preflight_reports_missing_tools_and_unverified_delegation_without_running_checks(self):
        cfg = core.settings(self.config)
        with patch.object(preflight.shutil, "which", return_value=None), patch.object(preflight, "command") as execute:
            result = preflight.check(cfg)
            self.assertFalse(result["ready"])
            self.assertIn("Git is missing", " ".join(result["errors"]))
            self.assertIn("delegation", " ".join(result["errors"]))
            execute.assert_not_called()
        with patch.object(preflight.shutil, "which", return_value="/fake/bin/tool"), patch.object(preflight, "command", return_value=subprocess.CompletedProcess([], 0, "{}", "")) as execute:
            result = preflight.check(cfg, delegation="available")
            self.assertTrue(result["ready"])
            self.assertEqual([call.args[0][:3] for call in execute.call_args_list], [["gh", "auth", "status"], ["gh", "repo", "view"]])

    def test_merge_resolutions_are_not_silently_flattened(self):
        self.g("switch", "-c", "side", "main")
        (self.source / "side.txt").write_text("side change\n")
        self.g("add", "side.txt")
        self.g("commit", "-m", "side change")
        self.g("switch", "part-2")
        self.g("merge", "--no-ff", "side", "-m", "merge resolution")
        self.g("push", "origin", "part-2")
        with self.assertRaisesRegex(core.Error, "merge commits"):
            self.start()

    def test_feedback_is_frozen_as_untrusted_review_input(self):
        original = core.command
        comments = [{"id": 5, "path": "one.txt", "line": 1, "body": "Check this behavior", "html_url": "https://example.invalid/5"}]
        def fake(argv, **kwargs):
            if argv[:2] == ["gh", "api"]:
                return subprocess.CompletedProcess(argv, 0, json.dumps(comments), "")
            return original(argv, **kwargs)
        with patch.object(core, "command", side_effect=fake):
            run = self.start(include_feedback=True)
        self.assertEqual(run.entry(1)["feedback"][0]["id"], 5)


class ManagedInstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.prefix = self.root / "tool"
        self.skill = self.root / "skill"

    def test_update_backup_rollback_and_uninstall_preserve_external_settings(self):
        installed = installation.install(self.prefix, ["claude"], self.skill)
        original = (self.skill / "SKILL.md").read_bytes()
        preferences = self.root / "runtime/projects/settings.json"
        core.atomic_json(preferences, {"keep": True})
        with patch.object(installation, "__version__", "0.3.1"):
            updated = installation.install(self.prefix, ["claude"], self.skill)
        self.assertTrue(updated["updated"])
        self.assertTrue(Path(updated["backup"]).is_dir())
        self.assertEqual(installation.verify(self.prefix)["version"], "0.3.1")
        rolled = installation.rollback(self.prefix)
        self.assertEqual(rolled["version"], installed["version"])
        self.assertEqual((self.skill / "SKILL.md").read_bytes(), original)
        installation.uninstall(self.prefix)
        self.assertFalse(self.prefix.exists())
        self.assertFalse(self.skill.exists())
        self.assertEqual(core.read_json(preferences), {"keep": True})

    def test_modified_skills_or_unknown_files_are_never_overwritten_or_deleted(self):
        installation.install(self.prefix, ["hermes"], self.skill)
        (self.skill / "SKILL.md").write_text("user customization")
        for operation in (lambda: installation.install(self.prefix, ["hermes"], self.skill), lambda: installation.uninstall(self.prefix)):
            with self.assertRaisesRegex(core.Error, "edited"):
                operation()
        self.assertEqual((self.skill / "SKILL.md").read_text(), "user customization")

    def test_failed_update_restores_previous_installation(self):
        installation.install(self.prefix, ["claude"], self.skill)
        from stack_review import cli
        with patch.object(cli, "install_skill", side_effect=core.Error("simulated installation failure")):
            with self.assertRaisesRegex(core.Error, "simulated"):
                installation.install(self.prefix, ["claude"], self.skill)
        installation.verify(self.prefix)
        result = subprocess.run([str(self.prefix / "bin/stack-review"), "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_legacy_prefix_and_foreign_skill_are_left_untouched(self):
        self.prefix.mkdir()
        (self.prefix / "private.txt").write_text("unmanaged data")
        with self.assertRaisesRegex(core.Error, "no ownership manifest"):
            installation.install(self.prefix, ["claude"], self.skill)
        self.assertEqual((self.prefix / "private.txt").read_text(), "unmanaged data")


if __name__ == "__main__":
    unittest.main()
