---
name: stack-review
description: Review and fix a chain of dependent GitHub PRs using isolated, resumable runs. Prepare a publication plan and publish only after user approval.
---

Use the installed `stack-review` command. If it is missing, ask the user to run
the package's install.py; do not install a different tool with the same name.
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
