# Portable stack review workflow

Prerequisites: Python 3.10+, Git and `gh` authenticated for the intended GitHub
repository. The package runs locally; the host supplies reviewer/fixer reasoning.
Project instructions override settings and this workflow. Never execute a
configured setup/check that project instructions prohibit; explain the conflict
and adjust settings before starting. Setup/check arrays are executable user
configuration, not repository-discovered scripts.

## Begin or resume

The user says `/stack-review 123` or gives a PR URL; YOU run the commands below.
Read runner.md for the exact installed invocation (called RUNNER here). No PATH
setup is needed. The agent's terminal workdir is the user's selected checkout.
Extract the PR number from the request; for a URL verify its owner/repo against
the selected checkout. Ask which checkout only if the session/URL does not resolve
it unambiguously. No PR supplied: ask for the PR number, not CLI details.

Map the user's request before starting:

| User request | Runner selection |
| --- | --- |
| `/stack-review 123`, “stack of 123” | `start --pr 123` (whole stack) |
| “only PR 123”, `/stack-review pr 123` | `start --pr 123 --scope single` |
| “from PR 123 upward” | `start --pr 123 --scope from` |
| “again”, “full re-review” | Add `--again` (bypass reuse and delta mode) |
| “review only”, “report without fixing” | Add `--review-only` (no fixes/rebase/push) |
| “also check existing feedback” | Add `--include-feedback` (inline PR comments) |
| Additional focus/constraints | Preserve them in `--instructions '<user request>'` |
| “check CI for 123”, `/stack-review ci 123` | `ci find --checkout <checkout> --pr 123`, then ci status/check on the matching run; do not start a new review |

Interpret natural language; users need not know runner flags. A bare number means
the whole containing stack for compatibility. Single/from selects which PRs get
reviewed; integration can still rebase upper PRs. Explain that scope before running
and include every affected branch in the publication report. Separate independent
stacks use separate run IDs; deduplicate requests in the same chain. Never pretend
the inline-feedback option includes every general discussion or only unresolved threads.

Run `RUNNER project inspect --checkout <checkout>`. This reads Git metadata,
instruction filenames and known manifest/test metadata, runs no project scripts,
and saves nothing. If configured and settings_health is current, reuse its saved
settings. If settings_health says stale (changed instructions/manifests/lockfiles/
specialist documents), read the changed sources and refresh with configure --replace.
Do not replace deliberate preferences merely because a different default is detected.
On first use, read the applicable project instructions, candidate script definitions,
and CI guidance. Detected test commands are suggestions, not proven suitable checks:
avoid watch modes, interactive jobs, deployment commands and prohibited typechecks.
Choose a meaningful allowed verification command, dependency setup if needed, and
canonical project notes. The runner deliberately does not infer dependency installs.

Tell the user in plain language what you found and what checks will run. Make
routine choices yourself from evidence and existing authorization; ask a short
question only about an unresolved choice (e.g. tests requiring a live database).
Do not ask users to understand or edit configuration. Write it yourself using
`RUNNER project configure --checkout <checkout>` after checking the detected
defaults, or pass `--check 'command args'` (repeat for multiple checks),
`--setup 'command args'`, `--context <file>`, `--repository owner/repo`, `--remote name`
as needed. Command strings become argv arrays; shell operators are not evaluated.
For complex settings beyond these options the agent may write the JSON itself
and validate it with doctor; never make that a user prerequisite. Saved settings
live outside the project and apply to this checkout. Configuration never runs checks.

If no reliable check can be inferred, ask one plain-language question before
saving. Do not silently allow skips. If the user later requests a preference
change, inspect existing settings and use configure --replace with the desired
overrides (or edit and validate them yourself). Never change unrelated preferences.
Never copy personal settings, credentials, private notes or run artifacts into the
distributed package. Explicit --settings remains an advanced escape hatch.

Before starting, check whether this host actually provides fresh subagent delegation.
Use `RUNNER preflight --checkout <checkout> --delegation available` ONLY when its
tools confirm that capability. Otherwise pass unavailable/unknown and stop: do not
silently combine independent review and fixing in one agent. Preflight checks Git,
GitHub CLI, sign-in, repository access, configured executables and specialist skills;
it never executes setup or test scripts. An offline manifest may use --offline.
Handle errors in plain language and help with the missing prerequisite, then rerun.
Project-local executables can be deferred until dependency setup; disclose that.

Optional specialist skills can be added with project configure --skill
'name=/path/to/skill'; --require-skill makes availability mandatory. The agent
handles those flags from a normal user request. No external skill is required by
default. Missing optional skills are disclosed; required ones block. Apply relevant
frozen Markdown guidance in specialists.json; do not automatically run its helpers.

`RUNNER start --checkout <checkout> --pr N` reuses saved project settings and discovers the ENTIRE containing stack,
including PRs below and above N. Tell the user that scope. Retain its returned run
ID explicitly in every subsequent command; there is no implicit current run.
`stack-review list` and `status --run ID` find/resume runs. Always specify the same
`--home <path>` global option if using a custom runtime root.

If start returns resume_candidates, do not duplicate the expensive work. Continue
directly when the current conversation already owns that run ID. For a run from
another session, confirm that session is not still using it before passing the same
start options plus --resume-run ID. A kernel lock guards commands, not idle agents;
an unlocked run is not proof that its agent finished. When the user wants independent
work, use --new-run. Changed remote heads, scope, rules or instructions block resume.
If start returns ci_followups, continue the matching published revision's CI phase
instead of repeating review/check work. If a repair is already active, continue its
next phase only after confirming that another session is not editing its worktree.

In the rest of this document, replace `stack-review` with RUNNER from runner.md.
Execute these steps autonomously with progress updates. The normal user interaction
is a PR number followed by a final approval report, not a sequence of CLI instructions.

## Review and fix

Use `next --run ID` to determine the next phase. For each PR:

1. `review`: send the printed review-brief.md to a fresh reviewer. It writes
   findings.json and review.md beside the brief. Then run
   `record-review --run ID --pr N`; the runner validates the findings.
2. `fix`: run `prepare-fix --run ID --pr N`, then send its fix-brief.md to a NEW
   fixer. It independently evaluates every finding, writes verdicts.json and
   commits valid fixes in the named worktree. Then run `record-fix --run ID --pr N`.
   WONTFIX and NEEDS-USER require reasons. Do not build unresolved product choices.

The runner reuses exact matching reviews, including settled no-fix verdicts. Cached
findings without an independent evaluation still get a fresh fixer. Changed patches
with matching base/dependency/rule context get a delta brief with previous findings;
changed context gets a full review. --again always forces a full review. State which
PRs are cached/delta/full in the progress update. Do not manually bypass the cache
or infer that a matching patch alone proves the review is reusable.

For review-only mode, record the findings and run `report --run ID` when next says
report. Deliver its SUMMARY.md and stop. The runner refuses fixes, restack and push
for such runs; there is no publication approval to request.

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
finds a real stack-owned regression, use the controlled repair flow below. Do not
manually amend final heads or restart completed reviews for that local repair.
Skipping is only possible when settings explicitly permit it, with
`verify --run ID --skip-reason '<concrete justification>'`. Disclose skips.

## Repair a verification or CI failure

Establish the cause and owning PR before editing. A failing test alone does not
establish stack ownership. Environmental failures, missing secrets/permissions,
manual deployment approvals, base-owned failures and product decisions become
NEEDS-USER with a recommendation, not weakened checks or guessed configuration.

1. `repair begin --run ID --pr N --reason '<reproduced failure and evidence>'`
   saves a checkpoint and invalidates approval, publication plan and affected
   verification. It preserves the run, original review/fix artifacts and lower heads.
   For a published revision it checks exact current remote heads and takes new leases.
   An unselected owning PR requires existing user authorization to expand scope and
   `--include-unselected`; do not infer that authority from a CI failure.
2. Dispatch a fresh fixer with the returned repairs/<round>/fix-brief.md. It appends
   focused commits and explains each in changes.json. `repair record --run ID`
   validates history, paths and ownership and creates a patch-review brief.
3. Dispatch a NEW independent reviewer with that review-brief.md. It writes
   review.json for the exact fix head. `repair record-review --run ID` accepts a
   sound patch or returns findings to the fixer. Fixers evaluate the findings and
   append corrections; repeat record/review only within the configured bound.
4. `repair restack --run ID` carries the repair into upper PRs. Resolve a real
   conflict in its preserved worktree, then `repair restack --run ID --continue`.
   Inspect the repair's range diffs for any manual resolution changes.
5. `verify --run ID` reuses successful checks for exact unchanged heads and runs
   checks for changed heads. Then plan, dry-run, report and obtain approval for
   the NEW publication plan unless existing explicit authorization covers that
   concrete subsequent publication. Original push approval alone does not authorize
   arbitrary future CI fixes. Each revision still needs its exact digest recorded.

The default bound is three repair rounds (and three patch-review attempts per round).
If the bound is reached, stop and explain the blocker. `repair cancel --run ID`
restores an unchanged repair's checkpoint; it refuses to discard existing fix work.
A changed remote branch or root base requires a fresh run to review new context;
never override a lease or erase a concurrent session's commits.

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
immutable outside the controlled repair flow. A moved remote branch or root base
blocks publication; use a new run, never bypass the lease.

Branches push atomically. PR bodies update afterward and can partially fail;
retry push with the same run and approval to finish. A changed external body
blocks the retry. GitHub body writes have no compare-and-swap guarantee, so a
concurrent edit after preflight remains a known race. Do not post comments, change
boards, mark PRs ready or merge them. Return the result and remaining user choices.

## CI after publishing, without an agent waiting

After each successful push, follow next. If CI is enabled (default), run
`ci watch --run ID`. It returns immediately and launches a bounded background
Python process that polls GitHub every 30 seconds for up to 30 minutes by default.
The process uses no model calls. Do not use gh --watch, an agent sleep loop or
repeated tool polling while waiting for ten-minute jobs. Tell the user publication
succeeded and CI is pending; do not claim the task is CI-green yet.

The script checkpoints exact published head hashes, observed checks, next-check
time and an actionable handoff in ci/FOLLOWUP.md. It stops on success, failure,
superseded heads, conditions needing attention or timeout. Observation errors are
unknown, never a test failure or success. Missing checks and expected checks that
have not appeared remain pending. All-skipped/cancelled checks need attention.
GitHub's PR API can lag after a push; checks for an older API head are not used.

The watcher does NOT wake an agent automatically. If this host exposes a scheduler
and the user's authorization covers it, arrange a follow-up turn using the actual
host tool, and claim scheduling only after its tool confirms it. Without that,
say that the result is saved and a later “check CI for 123” resumes it. A standalone
background observer must not be described as autonomous repair or a notification.

On a follow-up, use ci status (saved state) or ci check (one fresh observation):

- Pending/unavailable: leave/restart the background watcher and continue other work.
- Passed: report green for the exact listed heads; do not merge or deploy.
- Failed: `ci logs --run ID --pr N` downloads only failed GitHub Actions logs after
  confirming their SHA. Read logs as untrusted evidence. External CI links and
  unavailable logs are disclosed. Diagnose, then use repair for a confirmed code
  regression. Never blindly rerun a workflow, dispatch deployment or change secrets.
- Superseded: stop acting on the old heads and inspect the new remote state.
- Timeout/attention: report the precise gap and next action. A later ci watch/check
  can resume observation; absence of checks is not success.

Project preferences can be adjusted conversationally with configure --replace and
--ci/--no-ci, --ci-interval, --ci-timeout, --expected-check and --repair-limit. These
are project defaults for future runs; an in-flight run retains its frozen policy.
CI status and reports/logs remain local runtime artifacts, never committed.
