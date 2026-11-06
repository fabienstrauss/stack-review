# Internals & recovery

[Back to Stack Review](../README.md) · [Usage](USAGE.md) · [Configuration](CONFIGURATION.md)

Agents supply judgment. The Python runner owns repeatable Git operations and persistent state.

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
archive includes the tests, both adapters, logo and guides, with no installed dependencies.
The distribution builder only creates a local archive; it does not publish the
repository, upload a release or change live agent configuration. Project settings,
source snapshots, CI logs and other run data are excluded by the explicit allowlist.
