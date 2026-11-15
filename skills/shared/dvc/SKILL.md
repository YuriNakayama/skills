---
name: dvc
description: >
  Interactive runner for DVC (Data Version Control) data-management commands in this
  repo. Triggered explicitly by the user with /dvc. Presents the available DVC
  operations (status / diff / pull / push / fetch / add, plus dag / metrics show /
  commit in repos that have a dvc.yaml pipeline) via AskUserQuestion, confirms
  riskier ones, and executes them with the repo's conventions (DVC from the backend
  venv, the shared cache, remote and AWS profile read from the repo's DVC config).
  Use whenever the user types /dvc or asks to run DVC commands such as "push my
  data", "pull the latest weights", "show DVC status", "what changed in the pipeline
  outputs", or "register this directory with DVC", and they have not already
  specified the exact subcommand themselves.
---

# DVC Data Management Skill

Run DVC commands interactively in this repo. The user invokes this with `/dvc` when they want to inspect, sync, or register data without remembering the specific subcommand.

## When this skill is in charge

- The user typed `/dvc` (explicit trigger), or
- The user asked for a DVC operation in plain language and didn't pre-select the subcommand (e.g. "sync my data", "push the weights")

If the user already wrote a specific command (`dvc push`, `dvc status -c`), just run it directly — no need for the menu.

## Step 0 — Read the repo's DVC setup

Do this once per invocation, before the menu. Nothing here is hardcoded per repo; read it from the checkout:

```bash
ROOT=$(git rev-parse --show-toplevel)                                   # this worktree
common=$(git rev-parse --path-format=absolute --git-common-dir)
MAIN=$(dirname "$common")                                               # the main checkout (same from any worktree)
DVC="$ROOT/backend/.venv/bin/dvc"; [ -x "$DVC" ] || DVC=dvc             # the backend venv has dvc[s3]
cd "$ROOT"
[ -d .dvc ] || echo "no .dvc"                                           # see below
[ -f dvc.yaml ] && echo pipeline || echo tracked-dirs                   # which mode this repo uses
"$DVC" remote list                                                      # remotes (the default is usually `s3`)
"$DVC" config --list --show-origin | grep -E 'core\.remote|\.profile'     # default remote and AWS profile (from .dvc/config and .dvc/config.local)
"$DVC" cache dir                                                        # where the cache lives
```

- If `.dvc/` does not exist, stop and tell the user the DVC remote is not set up for this checkout. Point at the repo's own notes if they exist (`.claude/rules/data.md`, `.claude/rules/infra.md`, `docs/**/dvc*`). Do not run `dvc init` on your own.
- Run every command from `$ROOT`. Worktrees normally live under `$MAIN` (e.g. `.claude/worktrees/<branch>/`) or next to it (`<repo>.worktrees/<branch>/`); `git worktree list` shows them. Don't assume a path.
- The cache is usually shared by all worktrees (`"$DVC" cache dir` points under `$MAIN/.dvc/cache`), so multiple worktrees deduplicate — but **don't run two writing DVC commands (`push`, `repro`, `commit`) at the same time** (lock contention). For pull/status the read concurrency is fine.
- The remote and AWS profile come from `.dvc/config` / `.dvc/config.local`; no `--remote` flag is needed when a default remote is set.
- `data/` contents are DVC-managed; only `*.dvc` stubs, `dvc.lock` and `.gitignore` are committed to git. `dvc add` / `dvc commit` autostage stubs into git.

### The two modes

| | **pipeline** (`dvc.yaml` exists) | **tracked-dirs** (no `dvc.yaml`) |
|---|---|---|
| What is tracked | stage outputs declared in `dvc.yaml`, plus any `dvc add`ed paths | only `dvc add`ed directories, each with its own `<path>.dvc` stub (e.g. one per training run under `data/output/models/`) |
| Extra commands | `dvc dag`, `dvc metrics show`, `dvc commit` | none |
| `pull` / `fetch` / `push` | everything by default, or a path/stage | **always a `.dvc` target**. A bare pull finds nothing to restore and can delete directories |

## Interaction flow

The skill walks the user through three quick decisions: **category → command → arguments**, then confirms before executing risky ones. Only offer the commands that exist in this repo's mode.

User-facing strings (AskUserQuestion labels and descriptions, end-of-run summaries) should be in **Japanese** to match the response-language convention. The internal reasoning and SKILL.md instructions stay in English.

### Step 1 — Pick a category

Ask one question with these options:

- **状態確認** (status / diff, and dag / metrics show in pipeline mode) — read-only, fast, free
- **同期** (pull / push / fetch) — talks to the remote, may transfer data
- **管理** (add, and commit in pipeline mode) — registers / updates DVC tracking

Skip directly to the matching subcommand if the user's `/dvc` invocation already named one (e.g. `/dvc push` or "I want to push").

### Step 2 — Pick the specific command

Show only the commands inside the chosen category. Each option's description tells the user what it actually does and any caveats:

**状態確認**:
- `dvc status` — local workspace vs cache differences
- `dvc status --cloud` — local cache vs remote (does my push need to run?)
- `dvc diff [<rev>]` — diff tracked outputs against a git rev (default: HEAD)
- `dvc dag` — render the stage dependency graph *(pipeline mode)*
- `dvc metrics show` — print metrics file contents, e.g. `eval_metrics.json` *(pipeline mode)*

**同期**:
- `dvc pull [<target>]` — fetch from the remote to local cache + workspace
- `dvc fetch [<target>]` — like pull but only into cache (no workspace materialization)
- `dvc push [<target>]` — upload locally-changed tracked data to the remote (can be large: datasets, checkpoints)

**管理**:
- `dvc add <path>` — start tracking a directory/file (creates `<path>.dvc`). In tracked-dirs mode the typical target is a finished run directory under `data/output/models/`
- `dvc commit [<stage>]` — record current outs to `dvc.lock` without re-running stages (use after manual edits the user trusts) *(pipeline mode)*

### Step 3 — Gather arguments

Ask only when the chosen command needs a target:

- `dvc status` / `dvc status --cloud` / `dvc dag` / `dvc metrics show` — no extra question
- `dvc diff` — ask for the git ref (default: HEAD)
- `dvc pull` / `dvc fetch` / `dvc push`:
  - pipeline mode — ask whether to act on everything or a specific path/stage; default = everything
  - tracked-dirs mode — **always ask for the `.dvc` target**; list candidates with `find data -name '*.dvc'`
- `dvc add` — ask for the path (free text). Resolve relative to `$ROOT`.
- `dvc commit` — ask which stage(s); default = all stages with `--force`

### Step 4 — Confirm before executing if it could surprise the user

Re-confirm with a yes/no AskUserQuestion **only** for these cases — they either move data on the network, change git-tracked files, or are hard to undo:

- `dvc push` — uploads to the remote, possibly large. Run `dvc status --cloud` first if you can do it cheaply, and quote how many objects are out of sync (e.g. "S3 に N 件 push しますか?"); otherwise just confirm the action.
- `dvc add <path>` — creates a `.dvc` stub and may modify `.gitignore` under the path.
- `dvc commit --force` — overwrites recorded hashes; the user is asserting the current outs are intentional.
- a `pull` / `fetch` without a target in tracked-dirs mode — don't run it; ask for a target instead.

For everything else, announce what you're about to run and execute. The user already chose it.

### Step 5 — Run

Execute via Bash with cwd at `$ROOT`:

```bash
"$DVC" <subcommand> [args]
```

For long-running operations (`dvc push`, `dvc pull` of a fresh checkout, `dvc add` on a multi-GB directory), use Bash with `run_in_background: true`. The user gets a notification on completion. Don't poll in a loop.

After completion, show a one-line summary (e.g. "1423 files pushed", "remote in sync", or the truncated tail of stderr on failure). For `dvc diff`, `dvc dag` and `dvc metrics show`, just print the output verbatim.

## Why this skill exists (not just "run dvc")

Three reasons the menu is worth the few seconds:

1. **The repo has tribal knowledge** — venv path, profile, lock-contention rule, autostage behaviour, which mode the repo uses. Reading these in Step 0 saves the user from "command not found" / "no credentials" / wrecking a parallel job.
2. **A handful of DVC commands are destructive or expensive** — `commit --force`, a bare `pull` in tracked-dirs mode, `push` of a multi-GB dataset. A 5-second confirmation prevents an irreversible mistake.
3. **The user wants to pick from a list, not memorize flags** — that's the explicit ask. Driving the choice with AskUserQuestion lets them scan options instead of recalling syntax.

## Examples

**Example 1 — explicit trigger, no subcommand**

User: `/dvc`

You: Step 0, then ask Step 1 (category), then Step 2 (subcommand), then Step 3 if needed, confirm if Step 4 applies, then run.

**Example 2 — natural-language**

User: "push my changes to S3"

You: Step 0. Skip Step 1 (category is 同期). Skip Step 2 (subcommand is `push`). In tracked-dirs mode ask for the `.dvc` target. Run `"$DVC" status --cloud` to count out-of-sync objects, Step 4 confirms, then run `"$DVC" push [<target>]`.

**Example 3 — already specific**

User: "run `dvc status --cloud`"

You: don't run the menu — just execute it (no confirmation needed for read-only). Print the output.

**Example 4 — ambiguous**

User: "is my data up to date?"

You: this needs a read of remote vs local. Run `"$DVC" status --cloud` directly and report. No menu — the question maps to one specific command.

## Failure modes to handle

- **`dvc: command not found`** — fall back to `uv run --directory backend dvc ...`. If that also fails, tell the user the backend environment needs to be set up (the repo's `dev/setup`, i.e. `uv sync`).
- **`Unable to locate credentials`** — the AWS profile from Step 0 isn't configured. Point the user at the repo's DVC setup script if it has one (e.g. `dev/dvc setup`) and `~/.aws/credentials`.
- **`... is outside of git repository` / `Cannot add files inside symlinked directories` / `failed to commit`** — the worktree's `data/` is usually a symlink to the main checkout's `data/` (see the repo's `dev/create-worktree` if present). Run `dvc add` / `dvc commit` from the main checkout (`$MAIN`) instead, use the repo's data-sync script if the worktree accidentally holds real data (e.g. `dev/sync-data`), and check the repo's own DVC notes (`.claude/rules/data.md`, `docs/**/dvc*`) rather than improvising.
- **lock contention** (`Unable to acquire lock`) — another DVC process (probably another worktree) is running. Don't retry blindly; tell the user, suggest waiting or `ps -ef | grep dvc`.

When a command fails, paste the last 10–20 lines of stderr verbatim. Don't paraphrase — the actual DVC error message usually tells the user exactly what to fix.
