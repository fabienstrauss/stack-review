---
name: stack-review
description: Review and fix a chain of dependent GitHub PRs using isolated, resumable runs. Prepare a publication plan and publish only after user approval.
---

Use the installed `stack-review` command. If it is missing, ask the user to run
the package's install.py; do not install a different tool with the same name.
Read [workflow.md](workflow.md) for the shared workflow and artifact contract.

Run the orchestration in the main session. For review and fix phases use Hermes
`delegate_task` with a fresh agent for each phase, passing the printed brief path
and run ID. Use models and effort from `next`'s agents object when your Hermes
delegation configuration supports them. If the available route cannot honor a
requested model, disclose the actual route; do not claim it ran the requested model.
Agents do not delegate recursively. Return short progress updates between phases.
Expose the final summary with `MEDIA:<absolute SUMMARY.md path>` and explain all
branches and PR bodies in the plan before requesting the go to publish.
