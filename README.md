# Portable stack review

A small Python runner and two agent skills for reviewing and fixing GitHub PR
stacks. Hermes or Claude Code supplies the reasoning. The same runner owns the
Git operations, artifacts, verification and publication gates.

This directory is self-contained: copy it into a separate repository to distribute
it. It contains no personal paths, credentials, project notes or live settings.
No nested Git repository or remote is created here. Version 0.1 is a tested local
implementation; host discovery and a real GitHub publication still need a pilot.

## Install

Requires macOS/Linux, Python 3.10+ and Git. GitHub discovery and PR description
updates also require the GitHub CLI (`gh auth login`). No Python runtime dependencies.

From a copy of this directory:

```sh
python3 install.py --host hermes
# Or:
python3 install.py --host claude
export PATH="$HOME/.local/opt/stack-review/bin:$PATH"
```

The installer copies the runner under `~/.local/opt/stack-review` and installs
`stack-review` under the chosen host's personal skills directory. It refuses an
existing prefix or skill rather than overwriting one. It never replaces your old
`pr-stack-review` skill. To install the second adapter after the first:

```sh
stack-review install-skill --host claude
```

Use `--prefix /custom/path` and `--skills-dir /exact/skill/destination` with
install.py for custom locations. An alternative is `python3 -m pip install .`
followed by `stack-review install-skill --host hermes` (or `claude`). Pip packaging
uses setuptools; the standalone installer needs only Python's standard library.
Start a fresh host session and invoke **`/stack-review`**. Installation on disk
does not prove the host loaded the skill. Both adapters require `stack-review`
on the host process's PATH.

For development without installation: `python3 -m stack_review --help`.

## Configure a project

Keep settings outside this distributable directory (or in ignored `local/`).

```sh
stack-review init --settings /path/to/settings.json \
  --checkout /path/to/checkout --repository owner/repo
stack-review doctor --settings /path/to/settings.json
```

Edit the generated settings to add meaningful checks. See
[examples/settings.json](examples/settings.json). The example is for a Python
project; replace the checks with commands appropriate to your project.

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
by init, list, status or doctor. Project rules still govern permitted commands.

Dependencies and generated code are prepared explicitly in each run. Nothing
links back to the original checkout. Agent preferences are requests to the host;
the runner neither invokes a model nor proves which model was used.

## Run

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

## Scope of version 0.1

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

Share `dist/stack-review-0.1.0.zip`; recipients unpack it and run install.py. The
archive includes the tests and both adapters, with no installed dependencies.
Publishing the containing personal-setup repository remains an
explicit action and requires private visibility. This implementation does not
create a remote, publish a package or install into your live agent configuration.
