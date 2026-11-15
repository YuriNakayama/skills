JAX 環境まわりのコードを読み解き、解説ドキュメントにまとめました。

**スコープ**: `backend/src/simulate/jaxenv/` (state / env / town / benchmark) を中核に、等価性テスト・設計文書・依存配線まで。「環境」を RL environment と実行環境の両義で取りました。

**出力**: `jaxenv_explained.md`

| 章 | 内容 |
|---|---|
| 0 | 3 段階シミュレータ (official 850 / fast 13k / jax 276k-36.5M steps/s) の中での位置づけ |
| 1 | 依存事情 — `jax` を pyproject に書かない理由、`jax-metal` 禁止 |
| 2 | `state.py` — struct-of-arrays、`_shape_fn` の NaN ガード、丸め互換 |
| 3 | `env.py` — マスク更新パターン、market の `fori_loop`、`tree_map` 日末処理 |
| 4 | `town.py` — ショップ RNG が盤面依存で事前テーブル化できない件 |
| 5 | 等価性検証がこのモジュールの生命線である理由 |
| 6-7 | benchmark 設計と計測結果 |
| 8 | 現状のギャップ |

**設計上の要点 3 つ**

1. **全ルールが `jnp.where` のマスク更新**。トレース値に Python 分岐を書かないので、どの盤面でも同一命令列が走る。`_end_of_day` は日が変わらない環境でも計算して捨てる
2. **市場だけ逐次**。エンジンは 1 個ずつ約定して都度価格が動くため、`lax.fori_loop` を固定長 32 回。両プレイヤーが同じ板に売るので `market_inv` は `axis=1` で合算
3. **`BUY_SEED` は市場在庫を減らさない**（種は「発行」される）

**「GPU なら速い」は誤り**

| バックエンド | scatter / 要素演算 比 | official 比 |
|---|---|---|
| CPU | 0.7x | 60x |
| Metal | **9.1x** | **0.26x** |
| CUDA | 0.95x | 42,929x (batch 65536) |

タイルベース環境は `.at[].set` の塊なので scatter 性能がそのまま環境性能になります。Metal は batch を増やしてもレイテンシが減らずスケールしません。

**気づいた不整合**

- `40_uv_and_dvc_pull.sh` が `uv sync --group cuda` を打つが、`pyproject.toml` に `cuda` グループが**無い**
- `backend/pipeline/reinforce/` は空（36.5M steps/s の消費先が未実装）
- `_town_consume` のコメントどおり、`docs/competition/abstract.md` の「町中心需要の日次倍率」は実装に存在しない
