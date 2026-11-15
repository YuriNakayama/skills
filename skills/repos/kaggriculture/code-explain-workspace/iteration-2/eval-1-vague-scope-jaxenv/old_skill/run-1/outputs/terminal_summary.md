JAX 環境まわり = `backend/src/simulate/jaxenv/` と解釈して解説ドキュメントを書きました。

**対象**: `backend/src/simulate/jaxenv/` — 5 ファイル / 1,016 行（全ファイル精読）
**出力**: `docs/develop/code_explanation/20260811_jaxenv.md`

**入口**

| 入口 | 用途 |
|---|---|
| `state.initial_state(batch_size)` | 初期 `EnvState` 生成 |
| `env.step(state, op, crop_arg, market_op, market_item, market_qty)` | 1 ターン進行（`@jax.jit`） |
| `python -m simulate.jaxenv.benchmark` | official / fast / jax のスループット比較 CLI |

`__init__.py` は空なので、利用側は必ずサブモジュールを名指しします。

**冷たく読むと驚くところ 5 つ**

1. **これはラッパーではなく再実装。** 公式エンジンとの一致は構造的に保証されず、`tests/e2e/.../test_jaxenv_equivalence.py` だけが担保。テストが正当性の定義そのもの。
2. **実装範囲がかなり狭い。** 農夫 1 人のみ、NW 象限のみ、雇い人・動物・肥料・ショップ・雑草発生なし、市場は 1 ターン 1 注文（本来 10）。ベンチ数値は完全移植の下限。
3. **`town.py` は書かれているが `env.py` から呼ばれていない。** ショップ解禁は `_spawn_weeds` と RNG を共有し、空きタイル数で乱数消費数が変わるため事前表化できない。動いているのは町の中心（24 ステップ間隔）だけ。
4. **市場決済だけベクトル化を諦めている。** 両者が同一板に 1 単位ずつ売る逐次依存が本物なので `fori_loop` を固定 32 回。**`market_qty > 32` は黙って切り捨て**。
5. **`jax-metal` をこの venv に入れると壊れる。** 全テストの `jax.devices()` を乗っ取り、CPU の約 1/118 まで遅くなる（公式エンジンより遅い 0.26x）。一方 CUDA では batch 65536 で 42,929x。

**その他の細かい罠**

- `market_price` は `jnp.round`（銀行家丸め）ではなく `jnp.floor(x+0.5)`。1 ずれると等価性テストが落ちる。
- LOCKED 判定は **移動前**の足元、タイル操作は **移動後**の足元に効く。
- `_end_of_day` は毎ターン計算され、日締めのターンだけ `tree_map` + `where` で採用される（分岐を持たない代償）。
- 例外処理はゼロ。不正操作はすべてマスクで潰れるため、バグは低スコアとしてしか現れない。
