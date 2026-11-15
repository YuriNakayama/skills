# JAX 環境 (`simulate.jaxenv`) 解説

対象コード: `backend/src/simulate/jaxenv/` (state.py / env.py / town.py / benchmark.py)
関連: `backend/tests/e2e/src/simulate/test_jaxenv_equivalence.py`, `docs/plans/simulator/jax-gpu.md`

---

## 0. これは何か / なぜ存在するか

Kaggriculture の公式エンジン (`kaggle-environments`) は **1 エピソード 720 turn を Python の辞書ツリーで回す**。`simulate/fast.py` の冒頭にプロファイル結果があり、実行時間の内訳はこうなっている。

| 内訳 | 割合 |
|---|---|
| `structify` | 30.5% |
| stdlib その他 | 27.5% |
| `deepcopy` | 25.7% |
| `jsonschema` 検証 | 11.9% |
| フレームワーク中核 | 2.6% |
| **ゲームロジック本体** | **1.7%** |

つまり公式経路の遅さはルール計算ではなくフレームワークのオーバーヘッド。そこで本リポジトリには **3 段階のシミュレータ**が存在する。

| 経路 | 実装方針 | 速度 (env-steps/s) | ルール乖離 |
|---|---|---|---|
| `official` (`env.run`) | 公式そのまま | 850 | ゼロ (本番と同一) |
| `fast` (`simulate/fast.py`) | 公式 `interpreter` を素のループで直叩き。フレームワークだけ剥がす | 13,337 | ゼロ (構造的に同一) |
| **`jaxenv`** | **ルールを JAX で再実装し、B 環境をバッチ並列** | CPU 276k / **CUDA 36.5M** | **あり (再実装なので実測で担保)** |

`jaxenv` だけが「再実装」であり、ここが最大の設計上の緊張点。速度と引き換えに**乖離リスク**を背負うので、等価性テストがこのモジュールを使用可能にしている唯一の根拠、と `state.py` の docstring 自身が明言している。

---

## 1. 依存関係 — `jax` は pyproject に書かれていない

意図的な設計。

- `backend/pyproject.toml` の `dependencies` に `jax` は**無い**
- しかし `kaggle-environments` が `jax` を直接 requires している (実測: `Requires: flask, ..., jax, ...`)
- したがって **エンジンがある環境には必ず jax がある** (現在 venv 内は jax 0.11.0)

テスト側の `pytest.importorskip("jax")` は将来 `kaggle-environments` が依存を落とした場合の保険で、現状は発火しない。

### `jax-metal` は入れてはいけない

`state.py` の docstring に赤字級の警告がある。

> installing `jax-metal` into the project venv is actively harmful — it takes over `jax.devices()` for every test, and it runs this workload roughly 100x *slower* than CPU

理由は 2 つ:

1. `jax.devices()` が METAL を返すようになり、**既存テスト全部がその上で走る**
2. Metal バックエンドはこのワークロードで CPU の約 1/118

さらに `jax-metal` 0.1.1 は JAX 0.11 と非互換 (`StableHLO_v1.14.0` の `unknown attribute code: 22`)。検証時は `/tmp/metalenv` に別 venv を切って JAX 0.4.34 固定で動かしている。

### CUDA 側の配線 (現状は未完成)

`backend/src/gpu/runpod/execution/onstart_lib/40_uv_and_dvc_pull.sh` に `uv sync --group cuda` を打つ分岐がある。

```sh
case "<CASE>" in
  bench_*_gpu | reinforce_*)
    # reinforce family: JAX-on-GPU. cuda group install しないと jaxlib が CPU
    # fallback して iter ごと 13-15 min (期待 70s) になり…
```

**ただし `pyproject.toml` に `cuda` グループは現時点で存在しない**し、`backend/pipeline/reinforce/` も `__init__.py` だけの空ディレクトリ。この分岐は将来の RL 学習を見越した先回りで、今は発火しない。CUDA 検証自体は RunPod に手動で一時 pod を立てて (`tar` で `jaxenv` だけ送る) 実施されている。

なお同スクリプトには「`uv sync --group cuda` は宣言的なので dvc pull の**後**に走らせる」という重要な順序制約がコメントされている。先に走らせると `dvc[s3]` の推移依存 `s3fs` が pruning され、以降の dvc 操作が壊れる (実際に pod 20260520-110209 で踏んでいる)。

---

## 2. `state.py` — 状態を「配列の構造体」に潰す

### 2.1 中心的な発想: タイルはオブジェクトではなく平面

公式エンジンは 10×10 の各タイルを Python の `dict` で持つ。これはアクセラレータに載らない。そこで **struct-of-arrays** に置き換える。

```
公式:  farm["tiles"][y][x] = {"kind": ..., "crop": ..., "watered_today": ...}
jaxenv: kind          (B, 2, H, W)
        crop          (B, 2, H, W)
        watered_today (B, 2, H, W)
        ...           それぞれ独立した平面
```

軸の意味は先頭から `B` (環境バッチ) → `2` (プレイヤー) → `H` → `W`。

`EnvState` は `NamedTuple` なので、そのまま **JAX の pytree** として扱える。これが効くのは `env.step` 末尾の `jax.tree_util.tree_map` で「日が変わる環境だけ end-of-day 結果を採用する」を全リーフ一括でやる箇所 (後述)。

```python
class EnvState(NamedTuple):
    step: jnp.ndarray                    # (B,)     int32
    money: jnp.ndarray                   # (B, 2)   float32
    kind / crop / planted_day / watered_today /
    consecutive_unwatered / yield_units /
    max_lifespan_step: jnp.ndarray       # (B, 2, H, W) int32
    farmer_x / farmer_y: jnp.ndarray     # (B, 2)   int32
    shed / carried: jnp.ndarray          # (B, 2, N_PRODUCTS) int32
    seeds: jnp.ndarray                   # (B, 2, 5) int32
    market_inv: jnp.ndarray              # (B, N_PRODUCTS) int32  ← 市場は両者共有
```

`day` / `hour` は保持せず `step // 24` / `step % 24` のプロパティで導出。冗長な状態を持たないことで不整合が起きない。

dtype 方針は「カウントと日数は int32、金額だけ float32」。これはエンジンが価格を整数丸めするのに合わせた選択。

### 2.2 制約: トレース値に Python 制御フローを書かない

これがモジュール全体を貫く規律。

> **No Python control flow on traced values.** Every rule is a masked update, so the same instruction stream runs for all environments regardless of what any individual board contains.

`if tile.kind == PLANT:` は書けない。代わりに全部 `jnp.where(mask, 新値, 旧値)` になる。結果として **どの環境がどんな盤面でも同一の命令列**が走り、これが GPU 並列の前提になる。

### 2.3 市場価格モデル — 一番トリッキーな部分

競技の核心は市場なので、価格式の忠実な移植が最重要。

エンジンの価格は在庫 `inv` と均衡在庫 `I0 = 10,000` の差分に、**上下で別々の形状関数**を適用する。形状関数は `linear` / `sq` / `sqrt` / `log` / `log10` の 5 種で、商品ごとに違う。

```python
_RAW_MARKET = (
    # base,   T,  below_func, below_target, above_func, above_target
    (25, 400, "sqrt", 0.80, "log",    0.20),  # WHEAT
    ...
    (250, 300, "log", 0.20, "sq",     3.60),  # MELON  ← above が sq × 3.6
)
```

MELON の `above=sq, target=3.60` が「プレミアム品は少し供給過剰にしただけで $1 床に落ちる」の正体。

#### `_shape_fn` — 分岐せずに関数を選ぶ

```python
def _shape_fn(code, x):
    x = jnp.maximum(x, 0.0)
    safe = jnp.maximum(x, 1e-12)          # ← ポイント
    options = jnp.stack([x, x*x, jnp.sqrt(safe), jnp.log1p(x), jnp.log10(1.0 + x)])
    return jnp.take_along_axis(options, code[None, ...], axis=0)[0]
```

**5 種類を全部計算してから選ぶ**。分岐できないので当然だが、これには落とし穴があり、`sqrt(0)` や `log(0)` が選ばれない枝でも実行される。NaN/inf が発生すると `where`/`take` で選ばなくても勾配計算などで伝播しうるため、`safe = max(x, 1e-12)` で**選ばれない枝の入力も先に潰している**。コメント "Guard the inputs of sqrt/log so no branch produces NaN/inf before select" がそれ。

#### 丸めの互換性 — 銀行家丸めの罠

```python
# The engine rounds half away from zero via Python's round-then-int on a
# positive value; jnp.round is banker's rounding, so add the tie offset.
rounded = jnp.floor(price + 0.5)
return jnp.maximum(PRICE_FLOOR, rounded).astype(jnp.int32)
```

`jnp.round(2.5)` は 2 (偶数丸め)、Python の `int(round(2.5))` は 2 だが `int(round(0.5+x))` 系の挙動差が出る。ここでは `floor(x + 0.5)` にすることで**半数切り上げ**に固定している。この 1 行を間違えると全商品の価格が特定在庫でだけ 1 ずれる、という発見しにくいバグになる。等価性テストが 9 商品 × 9 在庫点を総当たりしているのはこのため。

### 2.4 初期状態

```python
locked = (xs >= half) | (ys >= half)   # NW 象限だけ unlocked
```

NW 5×5 のみ開放、農夫は `(4, 4)` にスポーン、市場は全商品 `I0 = 10,000` で均衡、所持金 3000。

---

## 3. `env.py` — jit 済み 1 step

### 3.1 アクション表現

意図的に狭い。

- 移動系: `PASS / NORTH / SOUTH / EAST / WEST`
- タイル系: `PLANT / WATER / HARVEST / DIG`
- 市場: `MARKET_NONE / SELL / BUY_SEED` を **1 turn 1 オーダー**

「小麦ループが実際に使う op だけ」という割り切りで、目的は *GPU バッチが割に合うかを測ること* であって完全な移植ではない、と冒頭 docstring が宣言している。

**未実装 (過大に読まないための明記)**: 雇用 hand、家畜、肥料、`BUY_LAND`、町ショップの device 側適用、雑草の自然発生 (`weedSpawnChance` 0.005 はタイル毎 RNG が要る)。

### 3.2 gather / scatter ヘルパ

「農夫のいるタイルだけ読み書きする」を全 (b, p) について一括でやる。

```python
def _gather_tile(plane, x, y):        # (B,2,H,W) -> (B,2)
    bi = jnp.arange(b)[:, None]; pi = jnp.arange(p)[None, :]
    return plane[bi, pi, y, x]

def _scatter_tile(plane, x, y, value):
    return plane.at[bi, pi, y, x].set(value)
```

**この `.at[].set` が性能上の急所**。後述するが Metal で遅い原因はここに集中する。

### 3.3 各アクションの実装パターン

全部同じ形をしている: 「条件マスク `ok` を作る → `jnp.where(ok, 新値, 旧値)` を scatter で書き戻す」。

#### PLANT

```python
ok = (op == OP_PLANT) & (kind_here == KIND_EMPTY) & (seed_held > 0)
```

種消費は `one_hot` を引くことで表現する。注目すべきコメント:

```python
# consecutive_unwatered starts at 1: the planting day already counts as
# unwatered, so a new plant must be watered the same day or it weeds over.
```

植えた日は既に「水やり無し 1 日目」としてカウントされる。つまり**植えたその日に水をやらないと雑草化する**。これは仕様の non-obvious な部分で、初期値を 0 にすると 1 日ぶんずれる。

`max_lifespan_step` は継続産出型 (`ongoing`) なら `-1` (寿命なし)、それ以外は `(day + max_yield_day + 1) * 24`。

#### WATER

```python
window_start = (max_yield_day + 1) // 2
in_window = (age >= window_start) & (age <= max_yield_day)
gains = ok & in_window & (CROP_ONGOING[crop_idx] == 0)
```

収量ボーナスは「生育期間の後半 (`max_yield_day` の半分〜満期)」に水やりした時だけ入る。継続産出型 (TOMATO / STRAWBERRY) は水やりでは増えない。

#### HARVEST

成熟判定 `(day - planted) >= CROP_FIRST_YIELD_DAY` かつ `yields > 0`。継続産出型は収穫してもタイルが残る (`clears = ok & ~ongoing`)。収穫物は `shed` ではなく `carried` (持ち歩き) に入り、日末に shed へ搬入される。

### 3.4 `_process_market` — 唯一の逐次処理

ここだけベクトル化できない。

> The engine quotes both players against the same pre-commit inventory and then commits both, one unit at a time. That serial dependence is real, so this runs a fixed-length `fori_loop` over units rather than trying to vectorise the sequence away.

エンジンは **1 個ずつ**約定し、その都度在庫が動いて次の 1 個の価格が変わる。5 個売るなら 5 つの異なる価格になる。この逐次依存は本物なので、`jax.lax.fori_loop` で **固定長 32 回**回す。

```python
max_units = 32   # トレース形状を静的に保つための上限
remaining0 = jnp.where(market_op == MARKET_NONE, 0, market_qty)
```

固定長にするのは jit のトレース形状を静的に保つため。実際の注文数が 5 でも 32 回ループし、`remaining > 0` の `active` マスクで空回りさせる。無駄だが形状が変わらないので再コンパイルが起きない。

ループ内の 2 つの非自明な挙動:

```python
# Sell: 市場在庫は $1 床で売れた時は増えない
above_floor = item_price > 1
inv_delta = jnp.where(can_sell & above_floor, 1, 0)[..., None] * sell_hot
market_inv = market_inv + inv_delta.sum(axis=1)   # ← axis=1 でプレイヤー合算
```

```python
# Buy seed: 種は市場の板から引かれない。「発行」される
money = money - jnp.where(can_buy, seed_cost, 0)
seeds = seeds + jnp.where(can_buy, 1, 0)[..., None] * seed_hot
# market_inv には一切触れない
```

`BUY_SEED` が市場在庫を減らさないのはエンジン実装を読んで初めて分かる事実で、`docs/plans/simulator/jax-gpu.md` §5 に「発見」として記録されている。

`market_inv` への書き戻しで `.sum(axis=1)` しているのは、**両プレイヤーが同じ板に売る**から。ここが競技の本質 (共有市場) を表現している部分。

### 3.5 `_decay_plants` / `_end_of_day`

```python
expired = (mls >= 0) & (step_b >= mls) & (((step_b - mls) % 2) == 0)
```

寿命超過後は **2 step に 1 回** 収量が 1 減り、0 になると雑草化。

日末処理 (`_end_of_day`) は 4 つを一度にやる:

1. **水やり判定** — `unwatered >= 2` (2 日連続で乾かす) で雑草化
2. **継続産出** — `since_first % interval == 0` かつ `count <= max_yield` で +1
3. **shed 搬入** — ここが面白い

```python
room = jnp.maximum(0, SHED_CAPACITY - state.shed.sum(-1, keepdims=True))
cumulative = jnp.cumsum(state.carried, axis=-1)
prior = cumulative - state.carried
deposit = jnp.clip(scale - prior, 0, state.carried)
```

shed 容量 100 を超えた分は**破棄**される。「商品順に入れていき、容量が尽きたらそこで打ち切り」を、ループ無しで `cumsum` を使って表現している。`prior` は「自分より前の商品が既に使った容量」、`scale - prior` が「自分に残された枠」。ループを cumsum に置き換える典型パターン。

4. **農夫を初期位置に戻す** — 日末に `(4,4)` へリセット

### 3.6 `step` — 全体の合成

```python
@jax.jit
def step(state, op, crop_arg, market_op, market_item, market_qty):
    day = state.step // TURNS_PER_DAY

    # ロックされたタイルではタイル操作は無効だが、移動は可能
    owned = _gather_tile(state.kind, state.farmer_x, state.farmer_y) != KIND_LOCKED
    tile_op = jnp.where(owned, op, OP_PASS)

    state = _apply_moves(state, op)          # ← 移動は素の op
    state = _apply_plant(state, tile_op, crop_arg, day)
    state = _apply_water(state, tile_op, day)
    state = _apply_harvest(state, tile_op, day)
    state = _apply_dig(state, tile_op)

    state = _process_market(state, market_op, market_item, market_qty)
    state = _town_consume(state, state.step)
    state = _decay_plants(state, state.step)

    closes_day = ((state.step + 1) % TURNS_PER_DAY) == 0
    eod = _end_of_day(state, day)
    state = jax.tree_util.tree_map(
        lambda new, old: jnp.where(
            closes_day.reshape((-1,) + (1,) * (new.ndim - 1)), new, old),
        eod, state)

    return state._replace(step=state.step + 1)
```

読みどころ 3 つ:

1. **`owned` マスクの適用範囲**。移動には素の `op` を渡し、タイル操作にだけ `tile_op` を渡す。「ロックされたタイルには入れるが耕せない」を 2 変数で表現。
2. **順序がエンジンと一致していること**。ユニット行動 → 市場 → 町中心 → 枯死 → (日が閉じるなら) 日末。順序を変えると同じ turn 内で値が変わる。
3. **`tree_map` による条件付き日末処理**。「日が閉じる環境だけ `eod` を採用」を、`EnvState` の全リーフに対して一括適用する。`reshape((-1,) + (1,) * (ndim-1))` は `(B,)` のブールを各リーフの次元数に合わせてブロードキャストするため。`EnvState` が pytree であることが効いている箇所。

なお `_end_of_day` は **日が閉じない環境でも常に計算される** (計算してから捨てる)。分岐できないので当然のコストだが、「無駄な計算をしてでも命令列を揃える」という GPU 向け設計の典型例。

### 3.7 町中心の需要 — abstract との食い違い

```python
#: ``townCenterSellInterval`` default. Read from the engine, not the abstract:
#: the centre consumes exactly one unit and this engine version applies no
#: day-based multiplier, despite what docs/competition/abstract.md summarises.
_TOWN_CENTER_STEP_INTERVAL = 24
```

`docs/competition/abstract.md` は「11 日目以降 2 倍、21 日目以降 4 倍」と書いているが、**このエンジン版のコードには倍率が無い**。ドキュメントではなく実装を読んで確認した、という注記。競技コードでは重要な種類の発見。

---

## 4. `town.py` — device に載せられなかったもの

ショップ解放だけは JAX 化を諦めて **host 側で事前テーブル化**している。理由が丁寧に書かれている。

### 4.1 なぜ device に載らないか

解放は `random.Random((seed * 1_000_003) ^ day)` から引く。Mersenne Twister + `_randbelow` のデータ依存な棄却ループなので、アクセラレータ上での再現は現実的でない。

### 4.2 さらに厄介な事実 — 抽選が盤面依存

```python
# Advance the stream exactly as _spawn_weeds does before the draw.
for _ in range(n_players * empty_tiles_per_day):
    rng.random()
```

`_spawn_weeds` が**同じ RNG を先に消費**し、その回数は **空きタイル数**に等しい。実測で 1 日目 50 回 (2 プレイヤー × 25 タイル) → 雑草が 1 つ出ると 49 → 48 と減っていく。

つまり **ショップ解放スケジュールは seed だけでは決まらない**。盤面の履歴に依存する。消費回数を 1 つ間違えると `rng.choice` が違うショップを引き、しかも**何のエラーも出ずに**別の需要になる。

この設計上の帰結として、`unlocked_shops_by_day` は空きタイル数を定数と仮定せず **引数 `empty_tiles_per_day` として受け取る**。docstring が正直に限界を述べている。

> the shop schedule can only be pre-tabulated when the per-day empty-tile counts are known in advance. For the scripted policies used in the benchmark that holds; for arbitrary play it does not, and the honest options are to run the schedule host-side in lockstep with the batch or to disable shops in both engines when comparing.

デフォルト 25 は「作物を夜またぎさせないポリシー」でのみ正確。土地購入・雑草放置・夜またぎ栽培のどれかをやると崩れる。

### 4.3 需要テーブル

`shop_demand_table` は `(days, N_PRODUCTS)` の int32 を返す。単品ショップ (PET_CAFE / YARN_STORE) は 1 tick あたり 2 消費、複数品ショップは各 1 消費。

**ただしこのテーブルは現状 `env.py` から使われていない**。`_town_consume` は町中心のみを扱う。ショップ需要の device 側適用は未実装 (`jax-gpu.md` §3 の「実装していない」に明記)。`town.py` は等価性検証の方針を記録するドキュメントとしての役割も担っている。

---

## 5. 等価性の担保 — このモジュールの生命線

`fast.py` はエンジンの interpreter を再利用するので構造的に等価。`jaxenv` は再実装なので**実測でしか担保できない**。

`backend/tests/e2e/src/simulate/test_jaxenv_equivalence.py` (e2e 分類 — 実エピソードを回すため) が 4 種のテストを持つ。

| テスト | 内容 |
|---|---|
| `test_wheat_loop_matches_official_engine` | 3 / 8 / 15 日の小麦ループを両エンジンで回し、全 step の `(money, seeds, shed, market_inv)` を突き合わせ |
| `test_market_price_matches_official_across_inventory_range` | 9 商品 × 9 在庫点 (`I0` 境界 9,999 / 10,000 / 10,001 を含む) を総当たり |
| `test_batched_environments_are_independent` | バッチ内の環境が互いに干渉しないこと |
| `test_batching_does_not_change_dynamics` | batch 1 と batch 16 で同一結果 |

### 比較条件を揃えるための細工

```python
NO_SHOPS = 10**6
configuration={"weedSpawnChance": 0.0, "townShopUnlockInterval": NO_SHOPS}
```

雑草自然発生とショップを**両側で無効化**し、決定論的コア (作物・水やり・収穫・価格・町中心・日末処理) だけを比較する。§4 の RNG 盤面依存があるため、これ以外に公平な比較方法がない。

### テストが踏んでいる罠

```python
engine.interpreter(state, env)
# The framework owns observation.step; the interpreter only reads it.
state[0].observation.step = n + 1
```

`observation.step` を進めるのは**フレームワークの責務**で、interpreter は読むだけ。これを忘れると `day`/`hour` が凍り、日末処理が一度も走らないまま「それらしいスコア」でエピソードが完走する。`fast.py` の docstring にも同じ罠が記録されており (`core.py:626`)、まさに等価性テストが存在する理由として挙げられている典型的なサイレント乖離。

---

## 6. `benchmark.py` — 何を測っているか

`official` / `fast` / `jax` (複数 batch) を同一ワークロードで比較し、**env-steps/s** を出す。

```bash
cd backend/src && PYTHONPATH=. python -m simulate.jaxenv.benchmark \
    --steps 720 --batches 1 64 1024 4096 8192 --skip-cpu
```

### 計測設計の要点

**エピソード全体を 1 つの `lax.fori_loop` に畳む**。

```python
out = jax.lax.fori_loop(0, n_steps, body, state)
```

これをしないと per-step の Python ディスパッチが支配的になり、「device 側環境」の意味が消える。ポリシーも device 上で計算する (`hour` から op を決める `jnp.where` の入れ子)。

**`n_steps` をトレース値のまま渡す**。

```python
# n_steps is traced, so one compilation serves any episode length. Baking it
# in as a Python int instead makes XLA specialise per length, which on the
# Metal backend turned a 0.3s compile into minutes.
compiled = jax.jit(rollout)
n = jnp.int32(steps)
```

Python int で渡すと XLA が長さごとに特殊化し、Metal ではコンパイルが 0.3 秒から数分に膨れた。

**コンパイル時間を分離**する。ウォームアップで 1 回回して `compile_sec` として別計上し、2 回目を `wall_sec` にする。形状ごとに 1 回だけ払うコストなので、スループットに混ぜるのは不当。

`jax.block_until_ready` を挟むのは JAX の非同期ディスパッチ対策。これが無いと「投げただけ」の時間を測ってしまう。

### 数字の読み方についての注意

docstring が自ら釘を刺している。

> It is a lower bound on how much work a full port would have to do per step, so treat the throughput as optimistic for a complete environment.

hand / 家畜 / 土地 / 肥料が未実装なので、完全移植したらこの数字より遅くなる。

---

## 7. 計測結果と結論 (`docs/plans/simulator/jax-gpu.md`)

| 実行環境 | batch | env-steps/s | official 比 |
|---|---|---|---|
| official | 1 | 850 | 1x |
| fast | 1 | 13,337 | 16x |
| JAX / CPU (M2 Max) | 1 | 50,973 | 60x |
| JAX / CPU (M2 Max) | 8192 | 276,042 | 325x |
| **JAX / Metal GPU** | 1 | 219 | **0.26x (official より遅い)** |
| JAX / Metal GPU | 64 | 922 | 1.1x |
| JAX / CUDA (4090) | 64 | 226,014 | 266x |
| **JAX / CUDA (4090)** | **65536** | **36,489,836** | **42,929x** |
| JAX / CUDA (4090) | 262144 | 31,956,572 | 37,596x (飽和後) |

### 「GPU なら速い」は誤り — 原因は scatter

同一コードのマイクロベンチ (B=64, ×50):

| 操作 | CPU | Metal | CUDA |
|---|---|---|---|
| 要素演算 `(B,2,10,10)` | 1.5 ms | 24.6 ms | 6.0 ms |
| **`.at[].set` scatter** | **1.0 ms** | **222.7 ms** | **5.7 ms** |
| scatter / 要素演算 比 | 0.7x | **9.1x** | 0.95x |

CUDA では scatter が要素演算と同コスト (比 0.95) なのに対し、Metal は 9.1 倍。`jax-metal` に効率的な scatter 実装が無いのが原因。

**タイルベース環境は本質的に「特定タイルだけ書き換える」操作の集合**なので (§3.2 の `_scatter_tile` が 1 step で 15 回程度呼ばれる)、scatter 性能がそのまま環境性能になる。しかも Metal のこのレイテンシは batch を増やしても減らないため、スケールしない。

行列積では Metal も CPU の 3.5x 出る (5,903 vs 1,668 GFLOP/s) ので、GPU 自体は正常。**ワークロードとの相性の問題**。

一般化できる教訓として文書はこう書いている:

> **タイルベース環境を GPU に載せる際は scatter 性能を先に測る**

### 数値の一致は CUDA 上でも確認済み

速度だけ出ても値が違えば無意味なので、RTX 4090 で同じ 15 日エピソードを再実行し、CPU で公式エンジンと一致した値と突き合わせている。float32 の丸めが絡む市場価格を含めて `(3057.0, 10, 2, 10001)` で一致。

### 使い分け

| 用途 | 推奨 | 根拠 |
|---|---|---|
| 提出前検証・リプレイ | `official` | 本番と同一経路 |
| ローカル大量対戦評価 | `fast` | 13k steps/s、乖離ゼロ |
| パラメータ探索 (Mac) | JAX / CPU | 276k steps/s。**Metal は使わない** |
| RL 学習・大規模自己対戦 | JAX / CUDA | 36.5M steps/s |

---

## 8. 現状のギャップ — 次に手を入れるならどこか

文書自身の結論が明快で、**速度はもう足りている。次の投資先は忠実度**。

| ギャップ | 現状 | 影響 |
|---|---|---|
| 雇用 hand / 家畜 / 肥料 / `BUY_LAND` | 未実装 | 小麦ループ相当しか表現できない。RL の行動空間が本番と違う |
| ショップ需要の device 側適用 | `town.py` にテーブル生成はあるが `env.py` から未使用 | 市場ダイナミクスが本番より単純 |
| 雑草の自然発生 | 未実装 (タイル毎 RNG が必要) | 等価性比較で両側 0 にしている |
| ショップ RNG の盤面依存 | 原理的に事前テーブル化不能 | 完全等価性には host 側 lockstep が必要 |
| `pyproject.toml` の `cuda` グループ | 存在しない (onstart スクリプトは参照している) | CI/RunPod 経路で CUDA jaxlib が入らない。手動 pod 運用のまま |
| `backend/pipeline/reinforce/` | 空 (`__init__.py` のみ) | 36.5M steps/s の消費先がまだ無い |

最後の 2 つが示すとおり、インフラ側 (`40_uv_and_dvc_pull.sh` の `reinforce_*` 分岐) は JAX-on-GPU の RL 学習を見越して先に配線されているが、pyproject の依存グループと pipeline 実装が追いついていない状態。

### batch サイズの選び方

RTX 4090 では **65536 付近が飽和点**。262144 に上げると逆に低下する (36.5M → 32.0M)。闇雲に大きくしない。
