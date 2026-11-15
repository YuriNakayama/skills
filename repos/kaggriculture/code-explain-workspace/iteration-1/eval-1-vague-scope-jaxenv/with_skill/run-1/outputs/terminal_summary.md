`backend/src/simulate/jaxenv/` を精読して解説ドキュメントにまとめました。

**出力**: `docs/develop/code_explanation/20260811_jaxenv.md`
**対象**: 5 ファイル / 1,016 行（全ファイル精読、コミット `133e83b`）

## 何をするコードか

公式エンジン（`kaggle-environments`）を JAX で**再実装**したバッチ版シミュレータ。状態を `(B, 2, H, W)` の struct-of-arrays に平坦化し、`B` 個の環境を 1 本の `jax.jit` 済み `step` で同時に進める。GPU バッチ化の効果検証が目的（CUDA で 42,929x、Metal では逆に 0.26x）。

## 入口

| 入口 | 用途 |
|---|---|
| `python -m simulate.jaxenv.benchmark` | official / fast / jax のスループット比較 |
| `initial_state(B)` + `env.step(...)` | バッチ状態の生成と 1 ターン進行 |
| `market_price(inventory)` | 価格モデル単体 |

## 冷静に読んで驚く 5 点

1. **`town.py` は誰からも呼ばれていない。** ショップ需要テーブル生成関数はあるが `env.step` に受け口がなく、実装済みの町需要は町中心（24 step ごと 1 個）だけ。
2. **ショップ解放の RNG は盤面依存。** `_spawn_weeds` が同じ RNG を先に消費し、その回数は空きタイル数と等しい（1 日目 50 → 雑草が出ると 49）。seed だけでは解放スケジュールが決まらないので、等価性テストはショップを無効化している。
3. **`docs/competition/abstract.md` と実装が食い違う。** abstract は町中心需要に「11 日目以降 2 倍」と書くが、このエンジン版は常に 1 個・間隔 24。エンジンのコードが正。
4. **市場だけベクトル化を諦めている。** 両プレイヤーを同じ約定前在庫で見積もって 1 単位ずつコミットする逐次依存が本物なので、固定長 32 回の `fori_loop`。`market_qty > 32` は**エラーにならず静かに打ち切られる**。
5. **`jax-metal` をリポジトリの venv に入れると全テストが壊れる。** `jax.devices()` が METAL を返し、このワークロードは CPU より約 100 倍遅い。原因は scatter（Metal は要素演算の 9.1 倍、CUDA は 0.95 倍）。

そのほか、`consecutive_unwatered` が植えた瞬間に 1 で始まる（当日中に水をやらないと 2 日目で雑草）、`BUY_SEED` は市場在庫を減らさない（種は発行される）、`market_price` は `jnp.round` の銀行家丸めを避けて `floor(x+0.5)` にしてある、なども本文に記載しています。

**等価性の担保範囲**: 小麦ループ 15 日、価格 9 商品 × 9 在庫点、バッチ独立性のみ（`weedSpawnChance=0` かつショップ無効）。hand / 家畜 / 土地 / 肥料は実装外で未検証 — この範囲を超えると黙って公式と乖離します。
