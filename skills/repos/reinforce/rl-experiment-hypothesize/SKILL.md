---
name: rl-experiment-hypothesize
description: >
  Hypothesis-list builder for reinforce RL experiments under
  `backend/pipeline/<competition>/<family>/case<N>/` (competition = Kaggle
  competition or `gymnasium`; family = method group: `reinforce` /
  `rulebase` / `search` / `imitation` / `evolution` — a specific algorithm such as
  PPO / DQN is a case, not a family). Runs **once** per competition / family / case to enumerate the
  hypotheses worth testing via code investigation + (opt-in) web research +
  a structured hearing, and emits
  `docs/experiment/{competition}/{family}/{yyyymmdd}_case{N}_{topic}/hypotheses.md` as a
  checklist together with a skip list (`実施しない検証 / 評価`). The downstream
  `rl-experiment` (loop driver) treats this `hypotheses.md` as the single source
  of truth. Read-only on code: does NOT implement, NOT push, NOT launch RunPod,
  NOT write `iterN_plan.md`. Use whenever the user types
  `/rl-experiment-hypothesize`, or asks to enumerate / brainstorm / organize
  hypotheses for a case — phrases like "gymnasium/reinforce/case1 の仮説をリストアップして",
  "GAE や entropy 周りで試すべき仮説を網羅したい", "新しいアルゴリズムの case の
  調査方針を整理したい", "hypotheses.md を作りたい", "サンプル効率を上げる打ち手を
  並べて" all count. Don't trigger this skill for single-iteration planning of
  one hypothesis (use `rl-experiment-plan`), full-pipeline execution (use
  `rl-experiment-execution`), result interpretation (use `rl-experiment-analysis`),
  or multi-iteration loop orchestration (use `rl-experiment`).
---

# Experiment Hypothesize Skill (reinforce)

Per-case hypothesis-list builder, run **once** per competition / family / case. The single deliverable is `hypotheses.md`. All downstream skills (`rl-experiment-plan` / `rl-experiment-execution` / `rl-experiment-analysis` / `rl-experiment`) consume this file as input.

## When this skill is in charge

- The user typed `/rl-experiment-hypothesize` (explicit trigger), **or**
- The user asked, in plain language, for any of:
  - enumerate hypotheses for a given case
  - brainstorm follow-ups around a knob (e.g. GAE λ, entropy coef, replay-buffer size, network width)
  - organize an investigation plan before opening a new case or family
  - draft a `hypotheses.md`
- The user did **not** ask to plan / implement / run a single hypothesis. Single-shot requests go to `rl-experiment-plan` / `rl-experiment-execution` directly.

If `hypotheses.md` already exists for the target case, ask whether to **rebuild / append / read-only display** before proceeding.

## Scope boundaries (what this skill does NOT do)

- Does not write `iterN_plan.md` or any per-hypothesis plan file. That is `rl-experiment-plan`'s job.
- Does not edit code under `backend/pipeline/`.
- Does not commit or push.
- Does not launch RunPod or run any `dev/*` command.
- Does not iterate. The skill writes `hypotheses.md` once and exits.

## Skill flow

5 phases. Phase 1 = code reality check, Phase 2 = opt-in web research, Phase 3 = hypothesis hearing, Phase 4 = skip list hearing, Phase 5 = write `hypotheses.md`.

### Phase 0 — Confirm the target case

`AskUserQuestion`, 1 question:

| Q | options |
|---|---|
| 対象 case | existing cases found by `ls backend/pipeline/*/*/` (e.g. `gymnasium/reinforce/case1`, `orbit_wars/reinforce/case1`) / `新規 case を切る` / `新規 family を切る` (method group: `reinforce` / `rulebase` / `search` / `imitation` / `evolution`) / `Other` (free-text `competition/family/caseN/topic`) |

Description on the first question: `各質問で「Other」を選ぶと自由記述も可能です。`

A new **family** is only for a new method group (`reinforce` / `rulebase` / `search` / `imitation` / `evolution`); a new algorithm within reinforcement learning (PPO → DQN → SAC) is a new **case** under `reinforce`. For a new case or family, also pin the competition (Kaggle competition Python name such as `orbit_wars`; default `gymnasium` when the work is not tied to a competition). Propose the next free number from `ls backend/pipeline/<competition>/<family>/`. Resolve `{topic}` (snake_case 1–3 words) in the same question (Other recommended).

If a `hypotheses.md` already exists at `docs/experiment/<competition>/<family>/{yyyymmdd}_case{N}_{topic}/hypotheses.md`, follow up with one more `AskUserQuestion`: `再構築` (back up existing and reset) / `追記` (append new hypotheses only) / `読み直すだけ` (display current contents and exit).

### Phase 1 — Code investigation (read-only)

Read the relevant code so the upcoming hearing is concrete. No user interaction.

Mandatory reads (skip those that don't apply):

- `ls backend/pipeline/<competition>/<family>/` — confirm existing case numbers and the next free slot.
- For an existing case: `backend/pipeline/<competition>/<family>/case<N>/` — `README.md`, `config.yaml` (env id, seed list, hyper-parameters, total steps), `train.py` (update rule), `policy.py` (network), `env.py` (env factory, wrappers, whether it is a batched JAX env or a simulator from `backend/simulate/<competition>/`).
- `ls docs/experiment/<competition>/<family>/` — surface prior experiment directories. Read 1–2 recent `result.md` / `iter*_result.md` files to capture what has already been tried + adopted / rejected.
- `ls data/output/models/<competition>/<family>/case<N>/runs/` (if present) — the latest run's `metrics.json` tail tells you where the current baseline plateaus.

Surface a 3–5 line orientation report to the user (in Japanese):

> `pipeline/<competition>/<family>/case<N>/` の現状: env={env id}、{algorithm + 主要ハイパラ}、baseline eval return ≈ X (n seeds)。過去 iter で採用済み: A、却下済み: B。次の調査余地: C / D。

### Phase 2 — Web research (opt-in)

`AskUserQuestion`, 1 question:

| Q | options |
|---|---|
| 外部 web 調査 | `不要 — Phase 1 のコード調査で十分` / `必要 — Other で具体的なクエリを指定` / `必要 — トピックを skill 側で提案` |

If the user picks "不要", skip to Phase 3.

If "必要", run `WebSearch` / `WebFetch` for 2–4 queries (time-box: ≤ 5 minutes). Bias toward authoritative sources (arXiv primary papers, CleanRL / PureJaxRL / Stable-Baselines3 docs and benchmark tables, "implementation details" write-ups, well-cited GitHub). Capture findings as 1–3 bullet points per source — these will be folded into Phase 5's References section. If the topic warrants a deeper survey, recommend `/research-retrieval` or the `solution-researcher` agent and stop.

### Phase 3 — Hypothesis hearing

`AskUserQuestion` runs in **at most 2 rounds** (max 4 questions per round). Selection format with free-text via "Other".

**Round 1: Draft, edit, prioritize**

Generate 5–10 hypothesis drafts from Phase 1 (code) + Phase 2 (web) findings, present them, then ask:

| Q | options |
|---|---|
| 草案のうち採用するもの (multi-select) | `H1: ...` / `H2: ...` / ... / `Other` (add new hypothesis as free-text) |
| 削除する仮説 (multi-select、任意) | `H3 を消す` / `H5 を消す` / ... / `なし` |
| 優先順位の付け方 | `skill 提案順 (新規性 + 工数低い順)` ⭐推薦 / `ユーザが手動で並び替え` / `期待効果順` / `Other` |

Each draft should name the knob, the expected direction on the primary metric, and the mechanism, e.g. `H1: GAE λ 0.95→0.98 — 長期報酬の credit assignment 改善で eval return +10%`.

**Round 2: Shared metadata** for the selected hypotheses

| Q | options |
|---|---|
| 最大 iteration 数 (この hypotheses.md 全体) | `仮説リストを使い切るまで` ⭐推薦 / `5` / `10` / `Other` |
| 主要メトリクス (default) | `固定 seed 評価の eval return 平均 (最終 N step)` ⭐推薦 / `目標 return 到達までの env step 数 (サンプル効率)` / `学習曲線の AUC` / `Other` |
| 既定 seed 数 | `3` ⭐推薦 (最小要件) / `5` / `10` / `Other` |
| 仮説間の依存関係 | `なし` / `あり (Other で「H4 depends on H1」のように記述)` |

The training-batch return is never offered as a metric (`学習バッチの return は引用しない` is a project default).

### Phase 4 — Skip list hearing (実施しない検証 / 評価)

`AskUserQuestion`, 1 round, multi-select with Other free-text. Bucketed by category:

**Q1. Evaluation / analysis skips** (multi-select; "どれもスキップしない" を選んだ場合は他選択を無視して空とする)
- `どれもスキップしない (default)` — defaults `学習バッチの return は引用しない` / `seed<3 の結果で結論を出さない` のみ自動 ON
- `10 seed 確認は行わない` — 既定 seed 数での評価のみで採否
- `学習曲線分析 (rl-experiment-analysis) は実施しない` — result.md の数値だけで採否
- `wall-clock 比較は行わない` — サンプル効率のみで判断
- `Other`

**Q2. Execution skips**
- `どれもスキップしない (default, Recommended)`
- `smoke test (dev/train --smoke) を skip`
- `dev/test を skip`
- `RunPod を使わない (local CPU only)`
- `auto-recover loop を使わない (失敗時は手動)`
- `Other`

**Conflict checks**:
- User tries to remove `学習バッチの return は引用しない` → reject (project rule: headline numbers come from the fixed-seed eval; see `.claude/CLAUDE.md` "What counts as a result").
- User selects a default seed count < 3, or asks to drop `seed<3 の結果で結論を出さない` → warn (a single-seed curve is a smoke test, not a finding) and confirm before allowing.

No individual confirmation dialog is required for `smoke test skip` / `dev/test skip` — record the user's choice as-is.

**Per-hypothesis exceptions**: free-text input via Other. Examples like "10 seed 確認は基本しないが H4 だけは inconclusive なら 10 seed で確認したい" are recorded in Phase 5's `例外条件` section.

### Phase 5 — Write `hypotheses.md`

Output path (per `.claude/rules/docs.md`):

```
docs/experiment/{competition}/{family}/{yyyymmdd}_case{N}_{topic}/hypotheses.md
```

- `{yyyymmdd}` — session injected `currentDate` (NOT shell `date`)
- `{competition}` — hyphenated slug (`orbit-wars`) or `gymnasium`
- `{topic}` — snake_case from Phase 0
- For "追記" mode, overwrite the same path (Phase 0 already backed it up).

Template:

```markdown
# Hypotheses — {competition}/{family}/case{N} {topic}

> 作成日: {yyyy-mm-dd}
> 最終更新: {yyyy-mm-dd}
> 状態: in_progress
> 最大 iteration: {N | リスト消化まで}
> 主要メトリクス: {例: 固定 seed 評価の eval return 平均 (最終 100k step), env={env id}}
> 既定 seed 数: {3 | 5 | ...}
> baseline: {例: gymnasium/reinforce/case1 run_id=20260926-120000 (eval return 480 ± 12, 3 seeds)}

## 実施しない検証 / 評価 (skip list)

### 評価
- 学習バッチの return は引用しない
- {例: 10 seed 確認は行わない (3 seed で採否)}

### 分析
- seed<3 の結果で結論を出さない
- {例: 学習曲線分析は実施しない}

### 実行
- {例: なし | smoke test (dev/train --smoke) を skip ⚠️ | RunPod を使わない (local CPU only)}

### 例外条件
- {例: H4 のみ「採否が inconclusive なら 10 seed で追加評価」}

## 仮説リスト (priority 順)

- [ ] (P1) H1: {一文 hypothesis} — {期待効果 / mechanism}
- [ ] (P1) H2: {...}
- [ ] (P2, depends on H1) H3: {...}
- [ ] (P3) H4: {...}
- [ ] (deferred) H5: {...}  # 工数大 / 後回し

## Iteration log

(各 iter 完了時に rl-experiment-execution / rl-experiment-analysis が追記)

| iter | 開始 | 仮説# | plan path | run_id | 主要メトリクス | 採否 | result path | analysis path |
|---|---|---|---|---|---|---|---|---|

## 参考 (References)  # Phase 2 を実施した場合のみ

- {URL} — {1 行所感}
```

The two project-default skip-list entries (`学習バッチの return は引用しない` / `seed<3 の結果で結論を出さない`) are **literal contract strings** (see `.claude/rules/docs.md`) — write them verbatim.

Write directly via `Write`, then report 3–5 lines to the user (in Japanese):

- written path
- hypothesis count + priority distribution
- key skip-list entries
- next-step suggestion: `/rl-experiment` to consume the list, or `/rl-experiment-plan` for a single iteration

Do not auto-spawn `rl-experiment-plan` / `rl-experiment`. Wait for the user to invoke them.

## Risk gates this skill enforces

- **Never offer the training-batch return as a metric.** The skip list keeps `学習バッチの return は引用しない` default ON; reject if the user tries to remove it.
- **Warn on fewer than 3 seeds.** When a seed count < 3 is selected, surface a one-line warning and confirm.
- **Record a baseline.** The header must name the baseline case / run the hypotheses are compared against (same env id, same evaluation seeds). If none exists yet, write `baseline: 未確立 (H1 で確立)` and make establishing it the first hypothesis.
- **Do not edit code.** Read-only; only `hypotheses.md` is written.
- **Time-box web research to ≤ 5 minutes.** Deeper surveys belong to `/research-retrieval`.
- **Don't silently overwrite an existing `hypotheses.md`.** Phase 0 must offer rebuild / append / read-only.

## Common shapes

| User says… | Skill behavior |
|---|---|
| `/rl-experiment-hypothesize gymnasium/reinforce/case1 gae` | Phase 0 skipped (target given). Phase 1 reads case1 + latest run metrics. Phase 2 likely 不要. Phases 3–5 produce 5–10 hypotheses + skip list and write `hypotheses.md`. |
| "gymnasium/reinforce/case3 (DQN) で LunarLander のサンプル効率を上げたい、Rainbow の各要素も参考にして" | Phase 0 confirms gymnasium/reinforce/case3. Phase 2 runs web research on Rainbow ablations. Hypotheses one per component (double / dueling / PER / n-step / noisy / distributional). |
| "SAC を試す case を新しく切りたい、何から試すか整理して" | Phase 0 `新規 case を切る` → next free `gymnasium/reinforce/case<N>` (a new RL algorithm is a new case, not a new family; competition defaults to `gymnasium`). First hypothesis = establish the baseline; header `baseline: 未確立 (H1 で確立)`. |
| "orbit_wars でルールベースの bot から始めたい、何を試すか整理して" | Phase 0 `新規 family を切る` (method group changes) → `orbit_wars/rulebase/case1`. First hypothesis = establish the baseline; header `baseline: 未確立 (H1 で確立)`. |
| "gymnasium/reinforce/case1 の hypotheses.md もう古いから作り直して" | Phase 0 picks `再構築`, backs up the existing file, resets. |
| "実験プランを書いて" (vague) | Belongs to `rl-experiment-plan`. Redirect. |

## Things to avoid

- Running this skill more than once for the same case to grow `hypotheses.md`. Rule: 1 case = 1 `hypotheses.md`.
- Running Phase 2 web research for more than 5 minutes. Deeper surveys belong to another skill.
- Writing `iterN_plan.md` content into `hypotheses.md`. Keep file responsibilities separate.
- Leaving the skip list without the two project defaults (`学習バッチの return は引用しない`, `seed<3 の結果で結論を出さない`).
- Hypotheses without a measurable direction on the primary metric ("try a transformer" is not a hypothesis; "replace the MLP with a 2-layer transformer over the last 8 frames — expect eval return +20% on the partially-observable variant" is).
- Overwriting an existing `hypotheses.md` without user confirmation.
- Auto-spawning `rl-experiment-plan` or `rl-experiment` after writing the file. Suggest by name only.

## Language

- Internal reasoning and thinking should be in English
- **All user-facing output, AskUserQuestion labels/descriptions, and the written `hypotheses.md` body must be in Japanese** (per `.claude/CLAUDE.md`)
