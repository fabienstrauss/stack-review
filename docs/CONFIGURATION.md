# Configuration

[Back to Stack Review](../README.md) · [Usage](USAGE.md) · [Internals](INTERNALS.md)

Project setup is agent-guided. These details are for custom installations, integrations and troubleshooting; users do not need to edit JSON.

## Installation details

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
`--restack-base existing` (default) or `--restack-base latest` selects root integration policy.

For custom or automated integrations, `init --settings <file> --checkout <path>
--repository owner/repo` and `start --settings <file> --pr N` still work. The schema
is illustrated in [examples/settings.json](../examples/settings.json). The example
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
| `restack_base` | `existing` (default) keeps the root PR's existing base point; `latest` rebases onto the base tip frozen at start and requires it to stay unchanged through push preflight |
| `ownership_policy` | `stack` blocks edits to lines on the frozen root base; `report` exposes them in the plan |
| `allow_skip_checks` | Permit explicit verification skips with a recorded reason; default false |
| `agents` | Reviewer/fixer model and effort preferences, interpreted by the host adapter |
| `specialist_skills` | Optional/required `{name, path, required}` references; none required by default |
| `max_repair_rounds` | Bounded repair/patch-review attempts, default 3 |
| `ci` | Enabled by default; poll_interval 30s, timeout 1800s, expected_checks names (optional) |

Commands use argument arrays, never shell interpolation. `{worktree}` expands
inside an argument; a standalone `{files}` expands to root-relative changed paths.
Paths come from each final PR's recorded base to its head, exclude deletions and
missing files, and exclude unrelated base changes. File-scoped commands are skipped
when this list is empty. Use `cwd: "."` with `{files}`. Put `--` before `{files}` where the target tool
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

The host follows [the shared workflow](../stack_review/workflow.md) and supplies
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
