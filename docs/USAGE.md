# Usage

[Back to Stack Review](../README.md) · [Configuration](CONFIGURATION.md) · [Internals](INTERNALS.md)

Start with `/stack-review <PR number>` in Hermes or Claude Code. The agent runs the commands; you choose the scope and approve publication.

## Tell the agent what to review

| Say | Behavior |
| --- | --- |
| `/stack-review 123` | Review the stack containing PR 123 |
| `/stack-review pr 123` or “only PR 123” | Review just that PR |
| `/stack-review from 123` | Review PR 123 and the PRs above it |
| “review PR 123 again” | Force a fresh full review |
| “review PR 123 only, report without fixing” | Findings only; no fixes, rebasing or push |
| “also check existing review comments” | Evaluate inline comments against current code |
| “focus on permissions” | Freeze that focus into the review brief and reuse identity |

Unchanged, previously reviewed inputs reuse their review. A changed patch with
matching surrounding context gets a delta brief; changed base/dependency trees,
requirements, instructions or specialist guidance get a full review. “Again”
overrides reuse. Cached findings that have not been independently evaluated still
get a fixer. Settled no-fix verdicts and verified published fixes can establish the
next review baseline; unresolved decisions remain visible.

“Only PR 123” limits **review scope**. If its fixes affect stacked branches above
it, the runner still rebases those branches and includes them in the publication
plan. Use “review only, no fixes” when you want inspection with no integration.
Feedback handling currently includes inline comments, not all general discussion
and not an assertion that every returned comment is unresolved.

An unfinished matching run is offered for resume instead of repeating expensive
work. Another session may still own it, so takeover is explicit. A request for
independent work creates a separate run; there is never an implicit global current run.

## First review in a project

The agent inspects the checkout, GitHub remote, project instructions and likely
test commands. It reads the relevant project rules and chooses suitable checks.
If something cannot be inferred safely, it asks in plain language—for example,
whether tests need a database. It writes and reuses the settings for you under
`~/.local/share/stack-review/projects/`, outside your repository.

Typical interaction:

```text
You: /stack-review 123
Agent: I found this project's instructions and pnpm tests. I'll use those checks
       and remember the setup for future reviews.
       [Reviews, independently evaluates fixes, restacks and verifies.]
Agent: Here are the fixes, remaining decisions and exact publication plan.
You: Go ahead.
```

Later, say “use the integration tests for this project” or “also load these project
notes” and the agent updates the saved preferences. You do not need to know the
settings schema. Discovery only reads allowlisted metadata; it never runs detected
scripts. Checks and dependency setup run only during the actual review workflow.

Before work, the agent runs preflight for Git, GitHub CLI/sign-in/repository access,
configured tools, optional/required specialist skills and actual subagent capability.
The runner cannot introspect the host's tools: the adapter must report delegation
availability truthfully. Missing prerequisites are explained before the review.
Project-local commands may need dependency setup before they can be checked.
Changed manifests, lockfiles, project instructions, CI files or specialist guidance
flag saved settings for the agent to revalidate. It preserves deliberate preferences.

## Repair without starting over

When verification exposes a real regression, the agent repairs it in the same run:

1. Preserve completed reviews and checkpoint the current revision.
2. Make a focused fix and have a fresh agent independently review just that patch.
3. Carry the fix up the stack using scripts, preserving any conflict for resolution.
4. Rerun checks on changed heads; reuse successful checks for exact unchanged heads.
5. Present a new publication plan and obtain the required authorization before pushing.

Each revision keeps its previous evidence. Old approval cannot silently authorize
changed commits. Repairs default to at most three rounds, with bounded patch-review
attempts. A moved remote branch or changed root base still needs a fresh run to
review that new context. Unselected PRs require authorization before expanding scope.

## CI follow-up without an agent waiting

After pushing, the agent starts a small background Python watcher and returns
control to you. It polls GitHub every 30 seconds for up to 30 minutes by default.
Waiting does not use model calls or keep an agent sleep loop active.

The watcher records exact published heads, check results and what should happen
next in `ci/FOLLOWUP.md` inside the private run directory. It stops on failure,
success, timeout, superseded heads or a condition needing attention. Passing checks
get a second stable observation before success, allowing delayed checks to appear.
Known expected check names can be configured to avoid treating missing jobs as green.
Results describe observed checks, not a guarantee about future jobs.

Later, simply say:

```text
/stack-review ci 123
# Or: check CI for PR 123
```

The agent finds the existing run. A code regression leads to the repair flow;
transient infrastructure failures get a diagnosis and bounded-rerun recommendation;
missing secrets, permissions, deployment approvals and product choices need you.
The runner downloads failed GitHub Actions logs only after checking their commit.
It does not blindly rerun workflows, merge PRs or trigger deployments. External
providers are observed through checks they report to GitHub; separate CD systems
without those checks are not independently monitored.

**The background watcher does not automatically wake Hermes or Claude.** A host
with scheduling support can arrange a follow-up turn; otherwise, the result waits
for your next interaction. The computer must remain available for the local
watcher to run. Checkpoints survive interruptions; a fresh check/watch can resume.
Never describe a pending, missing, all-skipped, cancelled or unavailable check as green.

CI policy is configured conversationally too: “check every minute,” “allow 20
minutes,” “expect lint and unit tests,” or “disable CI follow-up for this project.”
These saved preferences apply to future runs; active runs keep their frozen policy.

## Update, roll back or uninstall

From your clone of this repository:

```sh
git pull
python3 install.py
```

Managed updates keep the selected host(s), back up the previous installation and
restore it if installation fails. Preferences and review runs live separately and
are preserved. An unmodified v0.2 installation is recognized by exact source hashes
and path-specific launcher contents; unknown or customized installations are left
untouched. Start a fresh agent session after an update.

```sh
python3 install.py --rollback
python3 install.py --uninstall
```

Use the same `--prefix` if you chose a custom installation location. Rollback and
uninstall refuse changed installed files. Uninstall preserves project settings,
run data and backups; it does not alter shell profiles or other skills.
