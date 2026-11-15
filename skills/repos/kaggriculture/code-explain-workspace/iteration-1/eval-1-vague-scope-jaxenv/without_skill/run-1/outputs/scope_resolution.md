# スコープ決定メモ

## 依頼

「JAX の環境まわりのコードを読み解いて解説ドキュメントにまとめて」— パス指定なし。

## 決定したスコープ

### 中核 (逐行で読んだ)

| パス | 役割 |
|---|---|
| `backend/src/simulate/jaxenv/state.py` | `EnvState` (struct-of-arrays)、作物/市場定数、価格モデル |
| `backend/src/simulate/jaxenv/env.py` | `@jax.jit` された 1 step。全ルールのマスク更新 |
| `backend/src/simulate/jaxenv/town.py` | ショップ解放スケジュールの host 側再現 |
| `backend/src/simulate/jaxenv/benchmark.py` | official / fast / jax のスループット比較 CLI |
| `backend/src/simulate/jaxenv/__init__.py` | 空 |

### 文脈として読んだ (解説に反映)

| パス | 使った理由 |
|---|---|
| `backend/tests/e2e/src/simulate/test_jaxenv_equivalence.py` | 再実装の等価性担保が本モジュール成立の前提。テストが仕様書を兼ねている |
| `docs/plans/simulator/jax-gpu.md` | 実測値 (CUDA 42,929x / Metal 0.26x)、scatter 分析、engine の発見事項、再現手順 |
| `backend/src/simulate/fast.py` (冒頭 docstring) | 3 段階シミュレータの中での jaxenv の位置づけ。プロファイル内訳 |
| `backend/pyproject.toml` | `jax` が直接依存に無いこと、`cuda` グループが**無い**ことの確認 |
| `backend/src/gpu/runpod/execution/onstart_lib/40_uv_and_dvc_pull.sh` | 「JAX の環境まわり」= 実行環境/依存の配線。`uv sync --group cuda` 分岐と dvc pull 順序制約 |
| `backend/pipeline/reinforce/` | GPU 学習の消費先がまだ空であることの確認 |

## 決定の根拠

1. **全文検索から出発**した。`jax` を含むファイルはリポジトリ全体で 7 件しかなく、うち 4 件が `backend/src/simulate/jaxenv/` に集中。ここが唯一の実体だと即座に確定した。

2. **「環境まわり」の二義性を両取りした。** 日本語の「環境」は (a) RL の environment、(b) 実行環境/依存環境、のどちらにも読める。`jaxenv` は名前どおり (a) の environment 実装だが、`state.py` の docstring が `jax-metal` を入れるなと警告し、`jax-gpu.md` が丸ごとバックエンド比較で、onstart スクリプトが `--group cuda` を扱っている。**このコードベースでは両者が不可分**だったので、環境実装の解説と依存/バックエンド事情の両方を含めた。

3. **テストと設計文書を一次資料に含めた。** `state.py` 自身が「等価性テストだけがこのモジュールを使用可能にしている」と書いており、テストを読まずに解説すると成立根拠が抜ける。また `jax-gpu.md` にしかない実測値 (scatter マイクロベンチ、飽和点 65536) は、コードだけからは絶対に導けない。

4. **除外したもの**: `simulate/` の他モジュール (`episode.py` / `runner.py` / `matrix.py` など) は JAX を一切使わないので触れていない。`fast.py` のみ、比較対象として冒頭のプロファイル表を引用する範囲で参照した。

## 判明した副次的な事実

`40_uv_and_dvc_pull.sh` が `uv sync --group cuda` を打つ分岐を持つのに対し、`backend/pyproject.toml` に `cuda` グループは存在しない。`backend/pipeline/reinforce/` も空。インフラ配線が先行し、依存定義と実装が未追随の状態にある。解説ドキュメント §8 のギャップ表に記載した。
