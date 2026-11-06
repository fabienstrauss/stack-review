# Portable stack review workflow

Prerequisites: Python 3.10+, Git and `gh` authenticated for the intended GitHub
repository. The package runs locally; the host supplies reviewer/fixer reasoning.
Project instructions override settings and this workflow. Never execute a
configured setup/check that project instructions prohibit; explain the conflict
and adjust settings before starting. Setup/check arrays are executable user
configuration, not repository-discovered scripts.

## Begin or resume

Use a user-selected settings file. If none exists, propose one with
`stack-review init --settings <path> --checkout <path> --repository owner/repo`.
Configure context_files, standing_decisions and meaningful checks before starting.
Never copy personal settings, tokens, private project notes or run artifacts into
the distributed package. `doctor --settings <path>` is read-only inspection.

`stack-review start --settings <path> --pr N` discovers the ENTIRE containing stack,
including PRs below and above N. Tell the user that scope. Retain its returned run
ID explicitly in every subsequent command; there is no implicit current run.
`stack-review list` and `status --run ID` find/resume runs. Always specify the same
`--home <path>` global option if using a custom runtime root.

## Review and fix

Use `next --run ID` to determine the next phase. For each PR:

1. `review`: send the printed review-brief.md to a fresh reviewer. It writes
   findings.json and review.md beside the brief. Then run
   `record-review --run ID --pr N`; the runner validates the findings.
2. `fix`: run `prepare-fix --run ID --pr N`, then send its fix-brief.md to a NEW
   fixer. It independently evaluates every finding, writes verdicts.json and
   commits valid fixes in the named worktree. Then run `record-fix --run ID --pr N`.
   WONTFIX and NEEDS-USER require reasons. Do not build unresolved product choices.

Run bottom-up. Do not run two agents against the same PR phase. Separate runs can
proceed concurrently. Subagent failure is not evidence that its artifacts are
missing: inspect/validate them before re-dispatching. Do not read transcripts.
Keep cross-PR leads in the review/fix handoff rather than losing them.

## Integrate and verify

`restack --run ID` replays each PR and its fixes onto the new lower head, entirely
inside the private run clone. It does not edit the developer's working branch.
A conflict preserves its worktree and prints the Git error. Inspect
`status --run ID` and run.json's restack_pending PR. Resolve there, stage explicit
paths, and run `restack --run ID --continue`. Preserve both sides' intended behavior;
a product choice remains for the user. Do not remove/recreate paused worktrees.
If a rebase was aborted, start a fresh run; do not rewrite run.json manually.

`verify --run ID` runs configured checks on EVERY final PR head and blocks on
nonzero exits, missing tools and timeouts. Inspect per-PR check logs. If checks
require dependencies, configure setup_commands before starting. If verification
finds a bug requiring new commits after restack, start a fresh run and review it;
this version deliberately refuses mutation of already recorded final heads.
Skipping is only possible when settings explicitly permit it, with
`verify --run ID --skip-reason '<concrete justification>'`. Disclose skips.

## Review and publish

Run `plan --run ID`, read SUMMARY.md AND plan.json (full findings, verdicts and
proposed descriptions), then `push --run ID --dry-run`. Present NEEDS-USER items,
verification/skips, all affected branches and description changes. Wait for the
user's approval of that concrete plan unless their existing authorization
explicitly covers the exact resulting publication. Never infer approval merely
from a request to review or fix.

After approval: `approve --run ID --digest <plan digest>`, then `push --run ID`.
The approval record is a workflow gate, not cryptographic proof of a human act;
the host must only issue approve after actual authorization. Edited descriptions
require a fresh plan and approval. Recorded findings/verdicts and final heads are
immutable; start a new run to revise them. A moved remote branch or root base
blocks publication; use a new run, never bypass the lease.

Branches push atomically. PR bodies update afterward and can partially fail;
retry push with the same run and approval to finish. A changed external body
blocks the retry. GitHub body writes have no compare-and-swap guarantee, so a
concurrent edit after preflight remains a known race. Do not post comments, change
boards, mark PRs ready or merge them. Return the result and remaining user choices.
