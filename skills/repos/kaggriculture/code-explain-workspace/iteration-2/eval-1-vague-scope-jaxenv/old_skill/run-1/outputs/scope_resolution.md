# Scope Resolution

## User request

「JAX の環境まわりのコードを読み解いて解説ドキュメントにまとめて」 — no path given.

## How the scope was resolved

1. `find` for `*jax*` across the repo + grep for `jax` in `backend/`.
2. Candidates found:

| Candidate | Verdict |
|---|---|
| `backend/src/simulate/jaxenv/` | **Selected.** The only first-party JAX source in the repo. "環境" maps directly to `jaxenv` = JAX env(ironment). |
| `backend/.venv/lib/python3.13/site-packages/jax*` | Rejected — third-party install, not this project's code. |
| `backend/tests/e2e/src/simulate/test_jaxenv_equivalence.py` | Included as **supporting context only** (referenced in 補足), not as primary scope. |
| `docs/plans/simulator/jax-gpu.md` | Included as **prior material** per Step 0 (existing docs check). Read, cited, not modified. |
| `.claude/worktrees/feature-*/…` | Rejected — worktree copies of the same files. |
| `.claude/skills/code-explain-workspace/…` | Rejected — this eval harness itself. |

3. Ambiguity note: 「環境まわり」 could in principle mean "environment setup / dev environment" (venv, tooling). Rejected because the repo has a package literally named `jaxenv` whose docstring calls itself the environment reimplementation, and because there is no JAX-specific dev-environment code — only the `jax-metal` warning, which lives inside `jaxenv/state.py` and is covered in the 補足 section anyway.

## Final scope

- Primary: `backend/src/simulate/jaxenv/` — 5 files, 1,016 lines
  - `__init__.py` (0), `state.py` (245), `env.py` (446), `town.py` (116), `benchmark.py` (209)
- Supporting (read, not documented as scope): `backend/tests/e2e/src/simulate/test_jaxenv_equivalence.py`, `docs/plans/simulator/jax-gpu.md`

Size allowed a full close read of all 5 source files; depth note in the document header says so.

## Not confirmed with the user

The skill says to confirm a vague scope before the deep read. This run was executed non-interactively (batch eval), so the scope was resolved unilaterally and the reasoning recorded here instead.
