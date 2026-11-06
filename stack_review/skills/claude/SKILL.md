---
name: stack-review
description: Review and fix a chain of dependent GitHub PRs using isolated, resumable runs. Prepare a publication plan and publish only after user approval.
---

User interface: `/stack-review 123` (or a PR URL). The user supplies the PR and
the main session handles ALL runner commands, first-use setup and review phases.
Never hand the command sequence or JSON editing back to the user.
Read [runner.md](runner.md) for the installed runner's exact command; PATH is not
required. If this file/runner is missing, report an incomplete installation.
Read [workflow.md](workflow.md) for the shared workflow and artifact contract.

Keep orchestration in the main conversation so the user can inspect and approve
publication. Use fresh Claude Code subagents for review and fix separately,
passing the printed brief path and run ID. Reviewers only write review artifacts;
fixers only edit their run worktree and verdict artifacts. Use the models and
effort in `next`'s agents object where supported by the installed Claude Code.
Disclose unsupported settings rather than silently promising a particular model.
Agents do not delegate recursively. Return short progress updates between phases.
Link the final SUMMARY.md and explain all branches and PR bodies in the plan
before requesting the go to publish.
