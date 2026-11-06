# Portable stack review

A small Python runner and two agent skills for reviewing and fixing GitHub PR
stacks. Hermes or Claude Code supplies the reasoning. The same runner owns the
Git operations, artifacts, verification and publication gates.

This directory is self-contained: copy it into a separate repository to distribute
it. It contains no personal paths, credentials, project notes or live settings.
No nested Git repository or remote is created here. Version 0.4 is a tested local
implementation; host discovery and a real GitHub publication still need a pilot.

## Install

Requires macOS/Linux, Python 3.10+ and Git. GitHub discovery and PR description
updates also require the GitHub CLI (`gh auth login`). No Python runtime dependencies.

From a copy of this directory:

```sh
python3 install.py
```

It detects a single installed host, or asks **Hermes, Claude Code, or both?**
Then open a fresh session in your project and say:

```text
/stack-review 123
```

The agent handles setup, prerequisite checks, review, fixes, verification and the final approval report.
You do not run the pipeline commands, edit JSON, or change PATH. You can also give
a PR URL. `123` selects its entire containing stack, including PRs above and below.

The installer copies the runner under `~/.local/opt/stack-review` and installs the
skill under the chosen host's personal skills directory. Each installed skill
records its own runner invocation, so it works even if `stack-review` is not on
PATH. Installation on disk does not prove the host loaded the skill; a fresh
session is the discovery check. The original `pr-stack-review` skill and unrelated
skills are preserved. Re-running this installer updates a recognized installation
with a backup. Locally edited or unrecognized files are never overwritten.

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

## What the scripts handle

| Module | Deterministic work |
| --- | --- |
| `install.py`, `installation.py` | Install/update, integrity checks, backup, rollback, uninstall |
| `onboarding.py`, `preflight.py` | Project discovery, saved preferences, drift and prerequisite checks |
| `reviews.py` | Review reuse, delta comparisons, specialist snapshots, accepted baselines |
| `repair.py` | Revision checkpoints, repair validation, independent patch-review gates and propagation into upper PRs |
| `ci.py`, `ci_worker.py` | One-shot CI checks, bounded background polling, failed-log retrieval and persistent agent handoffs |
| `core.py` | PR discovery, frozen clones, worktrees, ownership audits, rebasing/restacking, check execution, summaries, approval and lease-protected atomic pushes |
| `cli.py` | Short machine-readable phase/status commands for either host |
| `package.py` | Build a source archive from an explicit allowlist |

Python invokes Git and the GitHub CLI directly. The original personal Bash
worktree/chain helpers are not required. Agents spend reasoning on reviewing code,
evaluating findings, writing fixes and resolving actual code conflicts. They do
not need to construct a rebase loop, track branch tips or parse successful check
logs. Tool calls still consume some tokens; the scripts reduce repeated reasoning
and keep routine output in files rather than making it “zero-token.”

No third-party skill is required by default. Ask the agent to add a specialist as
optional or required. Missing optional skills are named in the report; missing
required ones block. The runner freezes Markdown guidance for the run and never
automatically executes a specialist's scripts.

## Advanced configuration and runner commands

The sections below document the machinery for contributors and debugging. Normal
use remains `/stack-review <PR number>`; the agent executes these commands.

For unattended installation, choose `python3 install.py --host hermes`,
`--host claude` or `--host both`. `--prefix /custom/path` changes the installation
location; `--skills-dir /exact/destination` is available for one host at a time.
An alternative is `python3 -m pip install .` followed by
`stack-review install-skill --host hermes` (or `claude`). Pip packaging uses
setuptools; the standalone installer needs only Python's standard library.

For development without installation: `python3 -m stack_review --help`.
Installed skills use the exact command in their generated runner.md in place of
`stack-review` below. A console command on PATH is optional for manual CLI use.

The agent's onboarding commands are:

```sh
stack-review project inspect --checkout /path/to/checkout
stack-review project configure --checkout /path/to/checkout
stack-review start --checkout /path/to/checkout --pr 123
```

`inspect` returns observed metadata and a proposed configuration without saving
or executing scripts. `configure` saves validated preferences. `--check 'pnpm run
test:ci'`, `--setup 'pnpm install --frozen-lockfile'`, `--context /path/to/notes`,
`--repository owner/repo` and `--remote upstream` override detected defaults.
Repeated `--check` or `--setup` adds commands. `--replace` explicitly revises an
existing configuration while retaining preferences not overridden.
`--skill 'name=/path'` adds optional specialist guidance; `--require-skill` makes
it mandatory. These replace the saved specialist list when explicitly supplied.
`--ci`/`--no-ci`, `--ci-interval`, `--ci-timeout`, `--expected-check` and
`--repair-limit` set CI and repair preferences without editing JSON.

For custom or automated integrations, `init --settings <file> --checkout <path>
--repository owner/repo` and `start --settings <file> --pr N` still work. The schema
is illustrated in [examples/settings.json](examples/settings.json). The example
uses Python tests; it is not a universal default.

| Setting | Meaning |
| --- | --- |
| `checkout` | Source clone used to create independent run clones; relative to settings file |
| `repository` | GitHub `owner/repo`; must match the selected checkout's remote |
| `remote` | Named remote in the source checkout, default `origin` |
| `context_files` | Explicit project notes, standards and decisions; relative to checkout or absolute |
| `standing_decisions` | Review decisions to preserve, expressed as strings |
| `checks` | Named argv arrays, optional worktree-relative `cwd`; run on every final PR head |
| `setup_commands` | Named argv arrays to prepare each private worktree (e.g. dependency installation) |
| `command_timeout` | Timeout in seconds for each setup/check command |
| `forbidden_paths` | Case-sensitive glob patterns blocked in every fix commit |
| `ownership_policy` | `stack` blocks edits to lines on the frozen root base; `report` exposes them in the plan |
| `allow_skip_checks` | Permit explicit verification skips with a recorded reason; default false |
| `agents` | Reviewer/fixer model and effort preferences, interpreted by the host adapter |
| `specialist_skills` | Optional/required `{name, path, required}` references; none required by default |
| `max_repair_rounds` | Bounded repair/patch-review attempts, default 3 |
| `ci` | Enabled by default; poll_interval 30s, timeout 1800s, expected_checks names (optional) |

Commands use argument arrays, never shell interpolation. `{worktree}` expands
inside an argument; a standalone `{files}` expands to root-relative changed paths.
Use `cwd: "."` with `{files}`. Put `--` before `{files}` where the target tool
accepts it. Setup/check commands are trusted executable configuration: review
settings before using someone else's file. No scripts are auto-discovered or run
by project inspect/configure, init, list, status or doctor. Project rules still govern permitted commands.

Dependencies and generated code are prepared explicitly in each run. Nothing
links back to the original checkout. Agent preferences are requests to the host;
the runner neither invokes a model nor proves which model was used.

### Runner lifecycle (handled by the agent)

```sh
stack-review preflight --settings /path/to/settings.json --delegation available
stack-review start --settings /path/to/settings.json --pr 101
# Keep the returned ID; every following command requires it:
stack-review next --run RUN_ID
stack-review record-review --run RUN_ID --pr 101
stack-review prepare-fix --run RUN_ID --pr 101
stack-review record-fix --run RUN_ID --pr 101
# Repeat review/fix for the remaining PRs, then:
stack-review restack --run RUN_ID
stack-review verify --run RUN_ID
stack-review plan --run RUN_ID
stack-review push --run RUN_ID --dry-run
# Review SUMMARY.md and plan.json; after user authorization:
stack-review approve --run RUN_ID --digest PLAN_DIGEST
stack-review push --run RUN_ID
```

The host follows [the shared workflow](stack_review/workflow.md) and supplies
agents between commands. `start --pr N` selects the entire containing stack,
including PRs below and above N. An explicit
`--manifest examples/manifest.json` replaces GitHub discovery for controlled or
offline use. Review reuse checks frozen code trees, surrounding stack/base trees,
requirements, user focus, context and runner version. A matching patch alone is
insufficient. Use --again to force a full review; --new-run explicitly keeps a
session independent of matching unfinished runs.

Runtime data defaults to `~/.local/share/stack-review`; override with
`STACK_REVIEW_HOME` or the global `--home` option before the subcommand. Runtime
data is private and can include source code, PR descriptions and project notes;
keep it out of shared Git repositories and unencrypted shared folders.

## Reliability and recovery

- Each run owns a full clone, refs, worktrees and frozen settings/context. Starting
  or restacking another run cannot remove its conflict or move its local heads.
- Mutating CLI commands take a kernel lock for that run. State writes use atomic
  replacement. Kernel locks release on process exit; no stale-lock deletion needed.
- A paused rebase stays in its own PR worktree. Resolve and stage there, then use
  `restack --run ID --continue`. The clone disables hooks and rerere; it does not
  inherit hidden hook execution or old conflict resolutions from the source.
- Verification runs after integration, on every final head. Missing commands,
  timeouts and nonzero exits block publication. An explicit allowed skip is visible
  in the approval plan. During repair, successful checks on identical heads can
  be reused and are labeled as such. Checks that dirty tracked/untracked files block completion.
- Findings and verdicts are validated. Every finding has exactly one verdict and
  every new fix commit must be represented by a FIX verdict. Ownership uses
  per-file line coordinates and blame, not a global set of matching line text.
- Plan digests include exact heads, verification, bodies, findings and verdicts.
  Changing the proposed description invalidates approval. Moving a final local
  head outside a recorded repair or editing original findings/verdicts is refused.
  The repair flow retains review evidence and requires a fresh exact publication plan.
- All branch updates use one atomic push with exact remote leases. A server that
  does not support atomic push fails; there is no unsafe sequential fallback.
- A moved root base blocks publication at preflight. The base itself is not
  pushed, so a base update after preflight can still race with publication.
- Body updates happen after branch publication. Progress is journaled, so a retry
  can finish a partial publication. External body edits are checked beforehand,
  but GitHub has no conditional PR-body write: concurrent edits can still race
  between that check and the write. Branches and bodies are not one transaction.

`list` and `status --run ID` locate interrupted work. Failed initialization leaves
an identifiable run for diagnosis; start a new run rather than reusing partial
inputs. Completed run directories can be deleted manually when no agent/command
is using them. The source checkout is never changed, stashed, checked out or used
to land fixes. After publication, update your developer checkout normally.

The approval record enforces workflow ordering; it cannot authenticate that a
human authorized it. The agent must respect user authorization. It is not a
sandbox against an agent that can run arbitrary Git commands.

## Scope of version 0.4

Supports linear, same-repository branch stacks, single/from/whole-stack selection,
full/delta/cached reviews, review-only reports, inline-feedback evaluation, specialist
guidance, independent fix evaluation, per-head verification, conflict continuation,
safe resume discovery, managed installation lifecycle and gated publication.
Also includes controlled repairs without restarting, independent repair-patch
reviews, reusable unchanged-head checks, bounded background CI observations and
failed-log handoffs. Automatic host wake-up, workflow reruns, merging and deployment
are not implemented by the background worker.
Ambiguous forks, cyclic stacks and PR histories with merge commits are rejected;
the runner does not silently flatten merge resolutions. It intentionally omits automatic
working-branch integration, board changes, comment publication, merge automation
and inference of squash merges from commit titles. Already
squash-merged lower layers may need manual cleanup before starting a run.

Clones use more disk than shared worktrees. The first release targets macOS/Linux
because it uses `fcntl` kernel locks; native Windows is not supported. Tests cover
real local Git repositories and bare remotes, plus mocked GitHub-body failures.
They do not establish live Hermes/Claude discovery or GitHub server behavior.

## Develop and share

```sh
python3 -m unittest discover -s tests -v
```

Copy this directory to share the package; run artifacts and private settings must
stay outside it. To build a source zip containing only explicitly allowlisted files:

```sh
python3 package.py
```

Share `dist/stack-review-0.4.0.zip`; recipients unpack it and run install.py. The
archive includes the tests and both adapters, with no installed dependencies.
Publishing the containing personal-setup repository remains an
explicit action and requires private visibility. This implementation does not
create a remote, publish a package or install into your live agent configuration.
