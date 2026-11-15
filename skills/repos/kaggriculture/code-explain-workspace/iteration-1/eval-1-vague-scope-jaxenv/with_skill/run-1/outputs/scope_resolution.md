# Scope resolution

**User prompt**: 「JAX の環境まわりのコードを読み解いて解説ドキュメントにまとめて」 — no explicit path.

**Resolved scope**: `backend/src/simulate/jaxenv/` (5 files, 1,016 lines)

## How it was decided

1. Repo-wide grep for `jax` across `*.py`, `*.toml`, `*.md`, `*.sh`, `*.yaml` (excluding `node_modules` / `.venv`) returned 10 hits:

   | Path | Verdict |
   |---|---|
   | `backend/src/simulate/jaxenv/{state,env,town,benchmark}.py` | **in scope** — the only JAX implementation in the repo |
   | `backend/tests/e2e/src/simulate/test_jaxenv_equivalence.py` | read as context, not the target |
   | `docs/plans/simulator/jax-gpu.md` | read as prior material (the skill's Step 0 asks for this) |
   | `backend/src/gpu/runpod/execution/onstart_lib/40_uv_and_dvc_pull.sh` | incidental mention, out of scope |
   | `backend/notebook/20260809_text/*.txt` (3 files) | scraped Kaggle notebook text, not this repo's code |

2. The phrase 「環境まわり」 (env-related) maps cleanly onto the package name `jaxenv` and its `EnvState` / `step` core — there is no competing candidate. `jax` is not even a declared dependency in `backend/pyproject.toml` (it arrives transitively via `kaggle-environments`), so no dependency/config surface needed separate treatment.

3. Because the whole scope is only ~1,000 lines, all four non-empty modules were read in full rather than skimmed; the depth note in the document header says so.

## Adjacent material read but not documented as scope

- `backend/tests/e2e/src/simulate/test_jaxenv_equivalence.py` — the sole guarantee that the reimplementation matches the official engine; summarized in 補足 rather than given its own pass.
- `docs/plans/simulator/jax-gpu.md` — the "why" behind the package (GPU benchmark investigation, CUDA vs Metal scatter finding).
- `backend/src/simulate/__init__.py` and `fast.py` — checked to confirm `jaxenv` is **not** re-exported from the `simulate` public API and to position it against `fast.py` (the fidelity-first alternative).

## Confirmation note

The skill says to confirm a vague scope with the user before the deep read. This run was non-interactive, so the resolution was made unilaterally and recorded here; with only one JAX package in the repo the ambiguity was near zero.
