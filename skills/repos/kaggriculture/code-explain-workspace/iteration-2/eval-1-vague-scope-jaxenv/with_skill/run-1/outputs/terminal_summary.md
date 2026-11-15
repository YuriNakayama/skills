# ターミナル出力サマリ

JAX 環境まわり = `backend/src/simulate/jaxenv/` と解決し、解説を書きました。

**出力**: `docs/develop/code_explanation/20260811_jaxenv.md`
**対象**: 5 ファイル / 1,016 行（全ファイル精読）/ commit `133e83b`

## 入口

| 入口 | 用途 |
|---|---|
| `state.initial_state(B)` | B 本ぶんの初期状態を作る |
| `env.step(state, op, crop_arg, market_op, market_item, market_qty)` | `@jax.jit` 済み。全環境を 1 ターン進める中心 API |
| `python -m simulate.jaxenv.benchmark` | official / fast / jax のスループット比較 |

`simulate/__init__.py` からは **一切 re-export されていない**ので、サブモジュール直 import が前提。

## 冷たく読むと驚くこと 5 件

1. **全 op が毎ターン実行される。** 「op に応じて 1 つ選ぶ」ではなく plant/water/harvest/dig を全部走らせ、各々が自分のマスクで弾く。トレース値で分岐できないことの帰結で、GPU 並列の理由でもある
2. **`town.py` はどこからも呼ばれていない。** ショップ解放 RNG が盤面依存（`_spawn_weeds` が空きタイル数だけ先に消費する）と判明し、事前テーブル化不能という結論に至ったため。等価性テストはショップを無効化して比較している
3. **市場注文は 1 単位でも失敗すると残数が全部消える。** `remaining` が減衰ではなく即 0。さらに価格が下限 $1 の売却は市場在庫を増やさない
4. **`abstract.md` が実装と食い違う。** 町中心の需要は「11 日目以降 2 倍」ではなく常に 1 個・間隔 24。エンジンのコードが正
5. **Metal GPU では公式エンジンより遅い（0.26x）。** 原因は scatter。CUDA では要素演算と同コストなのに Metal では 9.1 倍。`jax-metal` をリポジトリの venv に入れると `jax.devices()` を乗っ取られ全テストが巻き込まれる

補足: 丸めは `jnp.floor(price + 0.5)` で銀行家丸めを回避、`_shape_fn` は選ばれない枝の NaN 汚染を `1e-12` クランプで防ぐ、など「揃えないと 1 ずれる」類の細工が随所にある。等価性は `weedSpawnChance=0` + ショップ無効の条件下でのみ実測保証。

セルフレビュー: 用語 1 件（pytree）を追加、未検証の推測 2 件に注記（JAX の out-of-bounds クランプ / `max_units=32` の由来）、`_apply_moves` の「クランプ」説明を実装に即して修正、日末の農夫リセットに行アンカーを追加。
