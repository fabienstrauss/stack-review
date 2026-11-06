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

Run the orchestration in the main session. For review and fix phases use Hermes
`delegate_task` with a fresh agent for each phase, passing the printed brief path
and run ID. Use models and effort from `next`'s agents object when your Hermes
delegation configuration supports them. If the available route cannot honor a
requested model, disclose the actual route; do not claim it ran the requested model.
Agents do not delegate recursively. Return short progress updates between phases.
Expose the final summary with `MEDIA:<absolute SUMMARY.md path>` and explain all
branches and PR bodies in the plan before requesting the go to publish.
Honor single-PR/from/again/review-only requests through the selection table in
workflow.md. Verify delegation capability in preflight; do not claim it from an
installed skill file alone. Routine Git plumbing belongs to the runner; inspect
and resolve code only when a review/fix or actual conflict needs judgment.
Verification/CI repairs keep the run and get an independent patch review; follow
the repair section rather than restarting. After push, launch ci watch and return
control to the user. The watcher checkpoints status; automatic agent wake-up needs
an actual host scheduler and must not be promised merely because a worker started.
