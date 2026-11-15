---
name: code-explain
description: Analyze an existing implementation in three passes — a directory/file tree of what exists, a class/method inventory with responsibilities and input/output, and a step-by-step trace of how the processing actually flows — then write it to docs/develop/code_explanation/{yyyymmdd}_{scope}.md and summarize in the terminal. Use this skill whenever the user asks to understand, read, grasp, explain, walk through, or get up to speed on a module, package, directory, or subsystem — including phrasings like "この実装を把握したい", "◯◯がどう動いているか知りたい", "コードを解説して", "処理の流れを追って", "explain how X works", "walk me through the Y module". This is an explicitly user-invoked skill; do not trigger it on its own during unrelated coding work. It is for reading and documenting code that already exists, not for reviewing quality, finding bugs, or maintaining a whole-repo architecture map.
---

# Code Explain

Read an existing implementation and produce a document that lets someone else pick it up without re-reading every file.

The trap this skill exists to avoid: dumping a file listing and calling it analysis. A list of names tells the reader nothing about how the pieces fit or what actually happens at runtime. The three passes below build on each other deliberately — the tree tells you *what exists*, the inventory tells you *what each piece is responsible for*, and the trace tells you *what actually happens in order*. Skipping to the trace produces a story with no map; stopping at the tree produces a map of a place nobody has visited.

## Inputs and outputs

**Input**: a scope — a directory, package, module, or set of files. If the user says something vague ("the simulator", "the agent stuff"), resolve it to concrete paths and confirm before doing the deep read.

**Output**, both of:

1. `docs/develop/code_explanation/{yyyymmdd}_{scope}.md`
   - `yyyymmdd` is today's date. Get it from the environment (`date -u +%Y%m%d`) rather than guessing.
   - `{scope}` is a short snake_case slug of what was analyzed: `simulate`, `jaxenv`, `rulebase_case7`, `dataset_scrape`.
   - Re-running on the same scope on the same day updates that file rather than creating a second one.
2. A terminal summary — not the whole document, but enough that the user knows what they got: the scope, the file count, the entry points, and the 3–5 things that would surprise someone reading the code cold.

## Step 0 — Scope and orient

Before reading anything closely, get the shape of the target:

```bash
find <scope> -name "*.py" | wc -l                 # how big is this?
find <scope> -name "*.py" | xargs wc -l | tail -1 # how many lines?
```

This decides how deep you can go. A 300-line module can be read line by line; a 5,000-line package cannot, and pretending otherwise produces a document that is confidently wrong in places. If the scope is large, say so in the document and be explicit about what you read closely versus skimmed. A reader who knows which parts are well-covered can trust the rest appropriately.

Also check for existing material before writing your own from scratch — `docs/plans/`, `docs/develop/`, module docstrings, and READMEs often explain *why* something is built the way it is, which reading the code alone will not tell you.

## Pass 1 — Directory and file tree

Produce a tree of the scope where **every entry has a one-line description of what it implements**. A bare `tree` dump adds nothing the reader could not run themselves; the value is entirely in the annotations.

```
backend/src/simulate/
├── __init__.py        Public API re-exports; the surface other packages import
├── config.py          MatchSpec / SimConfig — the frozen parameters of a run
├── episode.py         Runs one episode; independent crash / timeout detection
├── matrix.py          Fans episodes out across opponents and seeds
└── jaxenv/
    ├── env.py         JAX reimplementation of the engine's step function
    └── state.py       Flat array state representation for jit
```

Alongside the tree, note:

- **Entry points** — what does an outside caller actually import or invoke? (`__main__.py`, the names in `__all__`, the CLI commands.) This is where a reader should start.
- **Dependency direction** — which modules import which. If there is a layering (config ← episode ← matrix), state it; it is the fastest way to understand a package.
- **What is *not* here** — if an obvious responsibility lives elsewhere, say where. Absence is as informative as presence.

## Pass 2 — Class and method inventory

For each significant class and function, record its responsibility, its inputs and outputs, and the state it owns. Use a table so it stays scannable:

| Name | Kind | Responsibility | Input | Output |
|---|---|---|---|---|
| `MatchSpec` | frozen dataclass | One match's parameters | case, opponent, seed, steps | — (value object) |
| `run_episode` | function | Execute one episode, detect failures | `MatchSpec`, `validate_actions` | `EpisodeOutcome` |
| `ActionValidator` | class | Check actions against engine rules | observation, action | `list[ValidationIssue]` |

"Significant" means it carries responsibility a reader needs to know about. A private one-line helper does not need a row; a 200-line method certainly does. Cover the whole surface without padding the table with trivia.

Also capture the **core objects** — the data structures that flow between these pieces. These matter more than the functions: once a reader knows the shape of the central types, most of the code becomes predictable. For each, list its fields with types and a note on what the field means when it is not obvious from the name.

Where a name is misleading or a signature hides something (a function that mutates its argument, a "get" that performs IO), flag it. That is exactly the kind of thing a reader would otherwise discover the hard way.

## Pass 3 — Processing steps

Trace what actually happens, in order, for the main path. Number the steps and anchor each one to the code that does it, so the reader can jump straight there:

```
1. `__main__.main()` parses CLI args into a `SimConfig`         (config.py:88)
2. `run_matrix(config)` expands it into one `MatchSpec` per
   (opponent × seed) pair                                       (matrix.py:41)
3. Each spec is dispatched to a worker process                  (matrix.py:73)
4. `run_episode(spec)` builds the env and runs 720 turns        (episode.py:112)
5. Per turn, the agent's action is timed and optionally
   validated; a raised exception is caught and recorded rather
   than propagated                                              (episode.py:170)
6. Results aggregate into a `MatrixReport`                       (report.py:64)
```

Then cover the paths that are not the main one, because that is where the real behaviour lives:

- **Branches** — what conditions change the flow, and what happens in each case.
- **Error handling** — what is caught, what is allowed to propagate, and what fails silently. Silent failure is worth calling out loudly; it is invisible when reading casually and expensive when it bites.
- **Side effects** — files written, network calls, global or cached state.

A diagram earns its place when the flow branches or loops in a way prose makes tedious. Use a mermaid block when that is true, and skip it when the numbered list already reads clearly.

## Document structure

Write the file with this shape. The header block exists so a reader six months later knows how much to trust it:

```markdown
# {Scope} 実装解説

> 対象: `<paths>`
> 規模: N ファイル / M 行
> 分析日: YYYY-MM-DD
> コミット: <short sha>
> 読み込み深度: <全ファイル精読 | 主要ファイルのみ精読、残りは概観>

## 概要
<3-5 行。何をするコードか、なぜ存在するか、外から見た入口はどこか>

## 1. ディレクトリ構成
<annotated tree, entry points, dependency direction>

## 2. クラス / メソッド一覧
<responsibility tables, core object definitions>

## 3. 処理ステップ
<numbered trace, branches, error handling, side effects>

## 補足
<gotchas, surprising behaviour, open questions, links to related docs>
```

Recording the commit sha matters: code moves, and a document that cannot be dated against the source becomes actively misleading. Get it with `git rev-parse --short HEAD`.

Write the document in the language the user is using — this project's convention is Japanese for user-facing output, with code identifiers left as-is.

## After writing: stay available for revision

This skill does not end when the file is written. The first pass is a draft and the user will often want to go deeper on one part, correct a misreading, or add a section. Treat follow-up requests as continuations: re-read the relevant code, edit the existing document in place, and keep the header's depth note accurate as coverage grows.

When the user corrects something, they usually know the code better than the document does — take the correction, and check whether the same misunderstanding leaked into other sections.

## What this skill is not for

- **Code review / bug hunting** → `/code-review` or `/python-review`. Analysis here describes what the code *does*, not whether it is good. Note genuine landmines in 補足, but do not turn the document into a critique.
- **Whole-repo architecture maps** → `/update-codemaps`. This skill goes deep on one scope; that one stays shallow across everything.
- **Planning new work** → `/plan` or `/feature-plan`.
