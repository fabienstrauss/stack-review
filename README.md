# Portable stack review

A small Python runner and two agent skills for reviewing and fixing GitHub PR
stacks. Hermes or Claude Code supplies the reasoning. The same runner owns the
Git operations, artifacts, verification and publication gates.

This directory is self-contained: copy it into a separate repository to distribute
it. It contains no personal paths, credentials, project notes or live settings.
No nested Git repository or remote is created here. Version 0.2 is a tested local
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

The agent handles setup, review, fixes, verification and the final approval report.
You do not run the pipeline commands, edit JSON, or change PATH. You can also give
a PR URL. `123` selects its entire containing stack, including PRs above and below.

The installer copies the runner under `~/.local/opt/stack-review` and installs the
skill under the chosen host's personal skills directory. Each installed skill
records its own runner invocation, so it works even if `stack-review` is not on
PATH. Installation on disk does not prove the host loaded the skill; a fresh
session is the discovery check. Existing prefixes/skills are preserved, including
the original `pr-stack-review` skill; the installer refuses to overwrite them.

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
offline use. No patch-only cache is used: every run reviews frozen full inputs,
so changed bases and context do not silently reuse an old review.

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
  in the approval plan. Checks that dirty tracked/untracked files block completion.
- Findings and verdicts are validated. Every finding has exactly one verdict and
  every new fix commit must be represented by a FIX verdict. Ownership uses
  per-file line coordinates and blame, not a global set of matching line text.
- Plan digests include exact heads, verification, bodies, findings and verdicts.
  Changing the proposed description invalidates approval. Moving a final local
  head or editing recorded findings/verdicts is refused; create a new run to
  incorporate new fixes after restack.
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

## Scope of version 0.2

Supports linear, same-repository branch stacks, full reviews, independent fix
evaluation, per-head verification, conflict continuation and gated publication.
Ambiguous forks and cyclic stacks are rejected. It intentionally omits automatic
working-branch integration, board changes, comments, merge automation, incremental
review caching and inference of squash merges from commit titles. Already
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

Share `dist/stack-review-0.2.0.zip`; recipients unpack it and run install.py. The
archive includes the tests and both adapters, with no installed dependencies.
Publishing the containing personal-setup repository remains an
explicit action and requires private visibility. This implementation does not
create a remote, publish a package or install into your live agent configuration.
