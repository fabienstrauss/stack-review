<div align="center">
  <img src="assets/logo.svg" width="88" height="88" alt="Stacked review cards with a checkmark" />
  <h1>Stack Review</h1>
  <p>One PR number. A reviewed stack.</p>
  <p><strong>Hermes · Claude Code · GitHub</strong></p>
</div>

---

**Agents review the code. Scripts handle the plumbing. You approve the push.**

Independent reviewers and fixers work through your PR stack in isolated runs.
Rebasing, checks and bookkeeping are scripted. Unchanged reviews are reused;
repairs keep the work you've already done.

## Get started

You'll need **Python 3.10+**, **Git**, and the [GitHub CLI](https://cli.github.com)
signed in with access to your project. Runs on macOS or Linux with Hermes or
Claude Code and subagent support.

```sh
git clone https://github.com/fabienstrauss/stack-review.git
cd stack-review
python3 install.py
```

Choose **Hermes, Claude Code, or both** if asked. Open a fresh agent session in
the project you want reviewed, then:

```text
/stack-review 123
```

The agent discovers your project rules and checks, saves the setup, and runs the
review. **No manual JSON editing. No PATH changes.** It asks about unresolved
choices and presents the exact publication plan before pushing.

## Make the request yours

| Say | Get |
| :--- | :--- |
| `/stack-review 123` | The stack containing PR 123 |
| `/stack-review pr 123` | A review of just that PR |
| `/stack-review from 123` | That PR and the PRs above it |
| “Review PR 123 again” | A fresh full review |
| “Report only, don't fix” | Findings without code changes or publication |
| `/stack-review ci 123` | Resume the existing run's CI follow-up |

Add a focus like “check permissions” or “include existing review comments.”
The agent handles the commands. [More ways to use it →](docs/USAGE.md)

<details>
<summary><strong>What happens after I give it a PR?</strong></summary>

A reviewer finds issues. A fresh fixer checks each finding before changing code.
The runner restacks and verifies the result, then prepares your approval report.
Nothing is published without your authorization.

If verification finds a regression, a focused repair gets its own independent
review. Completed reviews stay intact. “Only this PR” limits review scope;
its fixes can still require rebasing upper PRs, which appear in the push plan.

</details>

<details>
<summary><strong>What about ten-minute CI jobs?</strong></summary>

A background script watches GitHub checks and saves the result without keeping
the agent waiting. On failure, the saved handoff points to logs and the repair flow.

The watcher doesn't wake an agent by itself. A host scheduler can arrange a
follow-up; otherwise, say `/stack-review ci 123` later. It doesn't merge or deploy.
[CI behavior and limits →](docs/USAGE.md#ci-follow-up-without-an-agent-waiting)

</details>

---

[Usage & updates](docs/USAGE.md) · [Configuration](docs/CONFIGURATION.md) · [Internals & recovery](docs/INTERNALS.md)

<sub>Python standard library · Local run data · Early release: live Hermes/Claude execution still needs a pilot.</sub>
