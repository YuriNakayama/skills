# rulebase/case7 エージェントの 1 ターン処理フロー

対象コード: `/Users/user/project/01_kaggle/kaggriculture/backend/pipeline/rulebase/case7/`
（`main.py` / `observe.py` / `tasks.py` / `market.py` / `config.py`）

エンジンは 1 シーズン 720 ターン（24 ターン/日 × 30 日）のあいだ、毎ターン `agent(obs)` を 1 回だけ呼ぶ。case7 はそのたびに **「観測をパース → 今やるべき仕事を全部列挙 → ユニットに 1 件ずつ割り当て → 市場注文を優先度順に組む」** という同じ 4 段を回している。状態はターンをまたいで持たない（完全にステートレス、`obs` だけが入力）。

---

## 0. 全体像

```
agent(obs)                      main.py
  └─ try:
       _decide(obs)
         ├─ parse(obs)                 observe.py   ① 観測 → Snapshot
         ├─ build_tasks(snap)          tasks.py     ② タスク列挙（優先度付き）
         ├─ assign(snap, tasks)        tasks.py     ③ ユニットへ貪欲割当
         └─ build_market(snap)         market.py    ④ 市場注文を優先度順に構築
     except Exception:
       _fallback(n_hands)              main.py      ⑤ 合法な no-op に退避
```

返り値の形は常にこれ:

```py
{"farmer": [op, *args], "hands": [[op, *args], ...], "market": [[op, *args], ...]}
```

`hands` は雇った日雇いの人数とちょうど同じ長さでなければならないので、`_decide` は `unit_actions[1:1+len(snap.hands)]` を切り出したあと足りない分を `["PASS"]` で埋める（`main.py:47-49`）。`market` は `MAX_MARKET_ORDERS`（10）で切り詰める。

例外は絶対に外へ出さない。`agent()` は全体を `try/except` で包み、失敗しても `farmer=PASS` + 手数分の `PASS` を返す（`main.py:58-69`）。さらに fallback 自体も二重に守られている。

---

## ① 観測のパース — `observe.py: parse()`

`obs`（dict もしくは Struct）から `Snapshot` データクラスを作る。全アクセスが `.get()` 経由の防御的パースで、キーが欠けても既定値になるだけで例外にならない。

Snapshot が持つもの:

| フィールド | 中身 |
|---|---|
| `step` / `day` / `hour` | 時刻。`step` が無ければ `day*24 + hour` で復元 |
| `money` | 自分の所持金 |
| `tiles` | 自farm の 10×10 `Tile` グリッド |
| `farmer` / `hands` | 農夫と各日雇いの座標 |
| `unlocked_quadrants` | 解放済み区画（NW から始まる） |
| `hires_today` | 今日すでに雇った人数（雇用コストは fib(n)） |
| `shed` / `seeds` | 倉庫在庫と種在庫 |
| `inventories` | ユニットごとの手持ち（index 0 = 農夫） |
| `prices` / `market_inventory` | 市場価格と在庫 |
| `unlocked_shops` | 解放済みの町の店 |
| `opponent_tiles` / `opponent_money` | 相手 farm（farm は公開情報） |

`Tile` は種類ごとに正規化される（`LOCKED` / `EMPTY` / `WEED` / `PLANT` / `COOP` / `PASTURE` / `ANIMAL`）。締切判定に効くフィールドが重要:

- 作物: `watered_today`, `consecutive_unwatered`, `yield_units`, `planted_day`
- 家畜: `fed_today`, `cared_today`, `consecutive_unfed`, `yield_units`, `fertilizer_available`

case7 で追加されたのが `Snapshot.opponent_crop_tiles(crop)`（`observe.py:87-98`）。相手が何タイルその作物を育てているかを数える。相手がまもなく市場に流す供給量を読む唯一の手段だが、後述のとおり現状は使われていない。

---

## ② タスク列挙 — `tasks.py: build_tasks()`

盤面を走査して「今ターン価値のある仕事」を全部 `Task` として吐き出す。この時点ではまだ誰がやるかは決めない。

`Task` = `(priority, target, op, needs_item, at_shed, zone_free)`。**priority は小さいほど緊急**。

### 優先度テーブル（`tasks.py:58-68`）

| P | 名前 | 内容 | zone_free |
|---|---|---|---|
| 0 | `P_FEED` | 家畜に給餌 | ✅ |
| 1 | `P_FETCH_FEED` | 倉庫から小麦を取り出す | (at_shed) |
| 2 | `P_RESCUE_WATER` | 枯れ寸前の作物に水やり | ✅ |
| 3 | `P_HARVEST` | 収穫 | 家畜のみ ✅ |
| 4 | `P_FETCH_ANIMAL` | 倉庫から家畜を取り出す | (at_shed) |
| 5 | `P_PLACE_ANIMAL` | 牧場に家畜を配置 | |
| 6 | `P_BUILD_PASTURE` | 牧場を建てる | |
| 7 | `P_WATER` | 通常の水やり | |
| 8 | `P_CARE` | 世話（次回生産に +1 上乗せ） | ✅ |
| 9 | `P_PLANT` | 植え付け | |
| 10 | `P_DIG` | 雑草除去 | |
| 11 | `P_COLLECT_FERT` | 肥料回収 | |

この順序はエンジンが日末に課す 2 つのハード締切を表している:

- `consecutive_unwatered >= 2` → 作物が雑草化する
- `consecutive_unfed >= 2` → 家畜が逃げる（$400–500 が消える）

だから FEED と救出 WATER が、農場を成長させるだけの仕事より必ず上に来る。

### タスク生成の内訳

**タイル走査**（`tasks.py:266-301`）— `workable_tiles()`（LOCKED と倉庫アクセス 4 マスを除いた全タイル）を回る。

- `ANIMAL`:
  - 未給餌なら `hungry` をカウント。**誰かが小麦を持っているときだけ** FEED タスクを出す（持っていなければ後述の FETCH_FEED が立つ）
  - `yield_units > 0` → HARVEST
  - 未世話 → CARE
  - 肥料あり → COLLECT_FERTILIZER
- `PLANT`:
  - 未水やり → `consecutive_unwatered >= 1` なら救出扱い（P_RESCUE_WATER, zone_free）、そうでなければ通常 WATER
  - `yield_units > 0` かつ `day - planted_day >= first_yield_day` → HARVEST
- `WEED`: DIG

**餌の補給**（`tasks.py:306-310`）— 空腹の家畜数が手持ち小麦を上回り、倉庫に小麦があれば `PICKUP WHEAT` タスクを立てる。これは「暇なユニットのついで作業」ではなく独立したタスク。誰も小麦を持っていない状態では FEED タスクがそもそも生成されず、2 日続けば家畜が逃げるため。

**牧場と家畜**（`tasks.py:313-358`）—
1. `herd_target(snap) - 既存の PASTURE/ANIMAL 数` だけ、倉庫 (4,4) に近い空きタイルから BUILD_PASTURE
2. COW/SHEEP を手に持っているユニットがいれば空き牧場へ PLACE
3. 空き牧場があり、倉庫に家畜がいて誰も運んでいないなら `PICKUP <species>`（買った家畜は倉庫に届くだけで、誰かが運ばないと永久に配置されない）

**植え付け**（`tasks.py:361-371`）— `_planting_plan()` が「作物ごとの目標タイル数 − 現在の植付数」を計算。BUILD_PASTURE に予約済みのタイルを避け、倉庫に近い順に空きタイルを埋める。種の在庫数が上限。

### 群れと作付けの目標値

`herd_target()`（`tasks.py:210-229`）は日数で段階的に増える:

| 日 | 目標頭数 |
|---|---|
| ~5 | `CORE_HERD` = 2 |
| 6–11 | `MID_HERD` = 8 |
| 12~ | `TARGET_HERD` = 14 |

ただし `ANIMAL_SLOTS_PER_QUADRANT (5) × 解放区画数` が上限。段階的にするのは、$400 の牛が初産 8 日目なのに買った瞬間から毎日小麦を食うため。初期資金 $3,000 で 4 頭を day 0 に買うと 20 日間手元が $0 になり、雇用も給餌も止まる（README に実測記録あり）。

購入種別は `next_animal()` が `HERD_SEQUENCE = (COW, COW, COW, SHEEP)` を所有頭数で循環させて決める。MILK と WOOL を別々の価格カーブに乗せ、片方の暴落がもう片方を巻き込まないようにする狙い。

作付けは `crop_targets()`（`tasks.py:178-187`）が**区画あたり**で定義し、解放区画数を掛ける。MELON 10 / WHEAT 8（`STRAWBERRY` はフラグ OFF）。`plantable()` が `day + first_yield_day <= LAST_DAY(29)` を満たさない作物を除外するので、終盤は自動的に植え付けが止まる。

---

## ③ 割り当て — `tasks.py: assign()`

ユニット順（農夫 → 各日雇い）に、貪欲に 1 タスクずつ取る。

```
key = (priority + (0 if own_zone else 100), manhattan距離, target)
```

の最小を選ぶ。

- **ゾーン制**: `_zone_of()` が盤面を列方向に `n_units` 本の帯へ分割し、unit *i* は zone *i* の仕事を優先する。他ゾーンの仕事は +100 のペナルティで事実上フォールバック扱い。移動距離を抑え、2 ユニットが同じタイルを狙わないようにするため。
- **`zone_free` の例外（case7 の目玉）**: FEED / 救出 WATER / 家畜 HARVEST / CARE はゾーン制を免除され、農場全体から取れる。倉庫作業（`at_shed`）も同様に免除。
- **アイテム条件**: `needs_item` があるタスクは、そのアイテムを実際に持っているユニットにしか割り当たらない。
- **重複防止**: 取ったタスクの `target` を `claimed` に入れ、後続ユニットは同じタイルを選べない。
- **実行 or 移動**: 目標タイルに立っていればその op を返し、立っていなければ `first_step_towards()`（BFS、NORTH→SOUTH→EAST→WEST の決定的タイブレーク）で 1 歩だけ進む。移動は LOCKED タイルも通れるので、盤面は連結グラフとして扱われる。

倉庫タスクは 4 マスのどれからでも実行できるので、`nearest_shed_tile(pos)` で各ユニットに最も近いマスへ再ターゲットされる。

**タスクが 1 つも取れなかったユニット** は `_idle_action()`（`tasks.py:445-474`）へ:
1. 倉庫マスにいる → 小麦以外の手持ちを PLACE（SELL は倉庫在庫から引くので、持ったままだと売れない）→ 次に必要量まで小麦を PICKUP → それも無ければ PASS
2. 倉庫マスにいない → 何か持っているか給餌が必要なら倉庫へ 1 歩 → それ以外は PASS

### zone_free が入った理由（README の記録）

case2 は全タスクをゾーン拘束していた。家畜 2 頭なら 1 ゾーンに収まるので問題にならないが、頭数が 10 を超えると家畜は数列に固まるため、**8 頭が 8 ゾーン中 4 ゾーンに散っている状況では 4 ユニットしか給餌できない**。残りは自分のゾーンへ歩き、その横で家畜が餓死していた。実測で 1 シーズン 30 頭喪失・最終ステップで空牧場 12。締切系タスクを `zone_free` にしたことで喪失は 30 → 5 に減り、これがアブレーションで **+14,714** と、case7 の 3 機構すべてを合わせたより大きい寄与になっている。

---

## ④ 市場注文 — `market.py: build_market()`

注文リストは 10 件で切られ、**超過分は末尾から黙って捨てられる**。したがって並び順そのものが優先度になる。

```
1. SELL          （常に先頭。同一ターン内で後続の購入を賄える）
2. HIRE          （hour == 0 のときだけ）
3. BUY_PRODUCT WHEAT   （餌の不足分）
4. BUY_SEED
5. BUY_ANIMAL
6. BUY_LAND
```

`step >= LIQUIDATION_START_STEP (700)` になると **SELL だけ** になる。売れ残り在庫は 0 点なので、シーズン末は生産問題ではなく換金問題になる。エンジンは step 718 の後に DONE を打つため、それまでに売り切る必要がある。

### SELL の組み立て（`_sell_orders`）

- 家畜そのもの（COW/SHEEP）は売らない
- WHEAT は `feed_needed()`（頭数 × `FEED_RESERVE_PER_ANIMAL` = 4）を差し引いた分だけ売る。清算中は全量
- 1 注文あたりの数量は `SELL_BATCH`（MELON 12 / MILK 6 / WOOL 6 ...）で上限。カーブを一気に下らないため
- 並び順は `_impact_score = 売上 / (1 + 価格下落幅)`。「稼ぎに対して自分の価格を壊さない」バッチほど先に出る

`price_at()` / `sale_proceeds()` はエンジンの価格カーブをローカルに再現している。`I0 = 10,000` を境に上下で違う shape 関数（`sqrt` / `log` / `linear` / `sq`）を使い、1 単位ずつ在庫を積み上げて価格を引き直す。フロア価格 $1 に達した単位は在庫を増やさない挙動まで写している。

### 雇用（`_hire_orders` / `_target_hands`）

日雇いは日末に消え `hires_today` がリセットされるので、`hour == 0` の 1 回だけ発注する。人数は仕事量から逆算:

```
workload = 作物数 + 2×家畜数 + 雑草数 + min(空きタイル数, SEED_BATCH)
wanted   = ceil(workload / JOBS_PER_HAND(7))
結果      = clamp(wanted, MIN_HANDS(6), MAX_HANDS(12))
```

n 人目の雇用費が fib(n) なので限界コストが急上昇する（6 人で計 20/日、12 人で 376/日）。固定人数ではなく仕事量に合わせることで、大きい農場には労働力を、小さい農場には節約を与える。

### 種（`_seed_orders`）

作物ごとに `目標 − 植付済み` を出し、`min(不足, SEED_BATCH(6), 空きタイル数) − 手持ち種` を購入。所持金を予算として順に減らしていくので、買い過ぎない。`plantable()` が false の作物はスキップ。

### 餌（`_feed_orders`）

`feed_needed()` に対して倉庫 + 全ユニット手持ちが不足していれば、その差分を `BUY_PRODUCT WHEAT` で即座に買う。自家生産の小麦を待たない。

### 家畜（`_animal_orders`）

- `day > ANIMAL_PURCHASE_LAST_DAY (18)` は購入しない（元が取れない）
- `所有 + 倉庫/手持ちの未配置` が `herd_target` に届いていること
- **空き牧場の数** が上限（家に入れられない家畜は買わない）
- 現金留保 `CASH_RESERVE(400) + CASH_RESERVE_PER_ANIMAL(120) × 所有頭数` を残した額でのみ購入。頭数に比例して留保が増えるのは、餓死で $400 を丸ごと失うより 1 頭我慢するほうが常に安いから

### 土地（`_land_orders`）

`LAND_BUY_DAYS = (5, 9)` の日程で NE($1000) → SW($2000) を購入。SE($4000) は上位リプレイでほぼ買われないため意図的にスキップ。`money >= cost + 500` のバッファ条件付き。

---

## ⑤ フィーチャーフラグの現状（`config.py:218-252`）

case7 は case3 から 3 つの機構を移植したが、それぞれをフラグ化して寄与を実測した。

| フラグ | 状態 | 実測 (30 エピソード) |
|---|---|---|
| `ENABLE_HERD_EXPANSION` | **ON** | +3,507 |
| `ENABLE_OPPONENT_AWARE_MELON` | OFF | ちょうど ±0（発火しない） |
| `ENABLE_STRAWBERRY` | OFF | −1,919 |
| （`zone_free` 締切タスク） | ON | **+14,714** |

- `ENABLE_HERD_EXPANSION` が OFF だと、`herd_target` は `TARGET_COWS = 2` 固定、`next_animal` は常に COW、`_target_hands` は `TARGET_HANDS = 6` 固定に戻る（= case2 の挙動）。
- `ENABLE_OPPONENT_AWARE_MELON` が ON なら `melon_tiles_per_quadrant()` がメロン価格と相手のメロンタイル数で作付けを 8–12 の範囲で増減させる。OFF なので現状は常に 10。相手が閾値（12 タイル）に届かないため一度も発火せず、`opponent_crop_tiles()` は実質的に休眠コード。
- `ENABLE_STRAWBERRY` が ON なら `crop_targets` に区画あたり 4 タイルが加わる。初収穫 10 日・以降 2 日間隔で、シーズン内の総収量が 24 単位しかなく、同じ土地のメロンに負けるため OFF。

---

## 補足: 毎ターンの典型的な挙動

| 局面 | エージェントがしていること |
|---|---|
| Day 0, hour 0 | HIRE ×6、メロン/小麦の種を購入、空きタイルへ植え付けタスクを撒く |
| 序盤 (day 1–5) | 水やり中心。牧場 2 つを建て、牛 2 頭を購入 → 倉庫から運搬 → 配置 |
| Day 5 / 9 hour 0 | 資金が足りていれば BUY_LAND。区画が増えると `crop_targets` と `herd_target` の上限も自動で増える |
| 中盤 (day 6–18) | 群れが 8 → 14 へ。人数は仕事量に応じて 6→12 へ。毎朝 FEED/CARE が最優先で消化され、収穫物は倉庫へ運ばれて `_impact_score` 順に売却 |
| 終盤 (day 19–28) | 家畜購入停止。`plantable` が false になった作物から順に植え付けが止まる |
| step ≥ 700 | 清算モード。市場注文は SELL のみ、バッチ上限を外して倉庫を空にする |
| いつでも例外時 | `farmer=PASS` + 手数分の `PASS`、market 空 |

---

## 既知の限界（README より）

case7 は builtin 相手に case2 比 +28%（44,977 vs 33,779）だが、**case2 との直接対戦では 7/16 で負ける**。両者が同じ MELON / MILK を市場に投げるため価格が共倒れし（day 29 に MELON $4 / MILK $26）、販売数量はほぼ同じなのに case7 だけが大きい群れの餌代と購入費を払う形になる。生産能力は売り先がなければ無価値、というのがこの競技の中核的な難しさで、次の改善は増産ではなく **差別化か販売タイミング** にある。
