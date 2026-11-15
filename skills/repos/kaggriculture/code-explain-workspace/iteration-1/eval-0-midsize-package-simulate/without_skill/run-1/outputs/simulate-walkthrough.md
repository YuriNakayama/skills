# `backend/src/simulate` 構造とエピソード実行の流れ

対象: `/Users/user/project/01_kaggle/kaggriculture/backend/src/simulate/`（10 モジュール + `jaxenv/` サブパッケージ、約 3,000 行）

---

## 0. このパッケージが解こうとしている問題

まず「なぜこの設計なのか」を押さえると、以降の構造がすべて説明できる。

`kaggle-environments` のエンジンは **エージェントの故障を隠す**。`episode.py` の docstring が 1.32.6 で実測した表を持っている:

| エージェントの挙動 | `debug=False` | `debug=True` |
|---|---|---|
| 例外を送出 | `status=DONE` | `env.run` が re-raise |
| `actTimeout` 超過 | `status=DONE` | `status=DONE` |

つまり **`status` だけ見ると「壊れたエージェント」が「単に弱いエージェント」に見える**。さらに不正アクション（op 名の typo、盤外座標、11 個目の market order）は silent no-op で、これも低スコアとしてしか現れない。

そこで本パッケージは検出チャネルを 3 本に分けている:

1. **crash** — `debug=True` で走らせて `env.run` の再送出例外を捕まえる
2. **timeout** — `env.logs[step][player]["duration"]` を直接読む（status には出ない唯一の証拠）
3. **invalid action** — エンジンに渡す前にエージェント出力を検査する（`validate.py`）

この 3 つが `EpisodeOutcome` → `HealthReport` を通って、勝率の隣に必ず表示される。「health ブロックを verbose フラグの裏に隠さない」のは意図的な設計判断。

---

## 1. モジュール構成（レイヤ順）

```
CLI          __main__.py       typer CLI (python -m simulate)
                 │
集計          report.py         MatrixReport / HealthReport / render / ExitCode
                 ↑
オーケストレーション matrix.py    SimConfig → _Job 群 → 逐次 or ProcessPool
                 │
実行エンジン   episode.py        official: env.run 経由（正式パス、replay 可）
              fast.py           fast:     interpreter 直叩き（約 30x、replay 不可）
                 │
支援          config.py         MatchSpec / SimConfig / Engine / ReplayMode
              agents.py         agent spec → builtin 名 or main.py 絶対パス
              validate.py       ActionValidator: silent no-op 検出
                 │
互換 façade   runner.py         旧 run_episode / run_match API
              __init__.py       公開 API 再エクスポート

別系統        jaxenv/           JAX バッチ環境（再実装、スコープ限定・実験用）
```

---

## 2. データモデル: `config.py`

評価対象を宣言的に記述する 2 つの dataclass（どちらも frozen）。

### `MatchSpec` — 評価マトリクスの 1 セル

```
case: str          評価対象（"rulebase/case1" など）
opponent: str      対戦相手
seed: int
steps: int = 720   FULL_SEASON_STEPS
swap_sides: bool   True なら case が player 1 側に座る
```

- `case_player` / `opponent_player` — `swap_sides` から席インデックスを導出
- `agent_order()` — `env.run` が期待する順に 2 つの spec を並べ替える
- **席順が結果に効く**（player 0 が先に共通マーケットへ注文を出す）ので、公平な評価には両席プレイが必要 — これが `swap_sides` の存在理由

### `SimConfig` — 実行全体のノブ

`case` / `opponents`（複数）/ `episodes` / `seed_base` / `swap_sides` / `workers` / `engine` / `replay_mode` / `output_dir` / `validate_actions` / `strict` / `act_timeout`。

- `iter_specs()` が **opponent × episode × (席)** の直積を展開して `MatchSpec` を yield する。seed は `seed_base + i` なので、サマリに記録された 2 つの数字だけで再現できる。`swap_sides` 時は同一 seed を両席で 2 回。
- `__post_init__` で **`engine=FAST` + `replay_mode != NONE` を即エラー**にする。fast エンジンは step 履歴を持たない（それが速さの理由）ため replay を作れず、黙って何も書かないより落とす方が良い、という判断。

定数: `FULL_SEASON_STEPS = 720`、`ACT_TIMEOUT_SEC = 1.0`、`SLOW_TURN_FRACTION = 0.5`（timeout の半分を超えたターンは「slow」として警告扱い、失敗ではない）。

---

## 3. エージェント解決: `agents.py`

`resolve_agent(spec)` が 3 形式をこの順で試す:

1. builtin 名 — `"pass"` / `"random"` / `"starter"`
2. ファイルパス（`main.py` を直接指す）→ 絶対パス化
3. `backend/pipeline/<family>/<case>/main.py` → 絶対パス

どれにも当たらなければ `AgentResolutionError`。

**先に解決することが本質的に重要**: case 名を typo するとエンジンは文句を言わず no-op エージェントに差し替えてしまい、実行全体が「正当な敗北」に見えてしまう。だから CLI は `_validate_specs()` で走らせる前に全 spec を解決する。

---

## 4. official パスの 1 エピソード: `episode.py`

中核は `run_episode(spec, ...) -> EpisodeOutcome`。順を追うと:

```
1. slow_threshold 決定       未指定なら act_timeout * SLOW_TURN_FRACTION
2. spec.agent_order()        case/opponent を席順に並べる
3. resolve_agent() x2        builtin 名 or main.py パスへ
4. ActionValidator.wrap()    validate_actions=True なら case 側だけ包む
5. _execute(...)             configuration を組んで env.run
6. _turn_costs(logs)         timeouts / slow_turns / max_duration を抽出
7. rewards を case 視点へ    case_money / opponent_money に振り分け
8. _collect_stderr(logs)     case 側の stderr を全 step 連結
9. EpisodeOutcome を構築
10. replay 書き出し（条件付き）
```

### `_execute()` の要点

```python
buffer = io.StringIO()
env = make(ENV_NAME, configuration=configuration, debug=True)
try:
    with contextlib.redirect_stderr(buffer):
        env.run(agents)
except Exception:
    artifacts = _RunArtifacts(crash_repr=traceback.format_exc())
    artifacts.logs  = list(getattr(env, "logs", None) or [])
    artifacts.steps = len(getattr(env, "steps", None) or [])
    return artifacts, buffer.getvalue()
return _harvest(env), buffer.getvalue()
```

- **`debug=True` が silent DONE を例外に変える唯一のスイッチ**。ただし同時にエンジンがトレースバックを stderr に吐くので、`redirect_stderr` で進捗表示を汚さないようバッファに捕獲する。
- クラッシュしても **例外を投げ返さない**。クラッシュは「呼び出し側が処理すべきエラー」ではなく「case についてのデータ」なので、部分的な `logs` / `steps` を拾って `_RunArtifacts` に詰めて返す。`run_episode` が raise するのは agent spec が解決不能なときだけ。

### `_harvest()` — 完走した env からの回収

`env.steps[-1]` から `reward` 2 つ、`status` 2 つ、step 数、`env.logs`、そして `env.toJSON()`（replay）を取る。

### `_turn_costs()` — timeout 検出

`env.logs` は `[step][player]` で添字され、各エントリが `duration` / `stdout` / `stderr` を持つ。**ここが制限時間違反を観測できる唯一の場所**。各 duration について:

- `> act_timeout` → `timeouts` に `TurnCost(step, player, duration)`
- `> slow_threshold` → `slow_turns`
- 常に `max_duration` を更新

### `EpisodeOutcome` — 常に「case 視点」

`case_money` / `opponent_money` という名前で持ち、player 0/1 の生インデックスは外に出さない（`swap_sides` があるので）。派生プロパティ:

- `margin` = case − opponent、`winner_is_case`、`is_tie`
- `bad_status` — DONE 以外が 1 つでもあるか
- `invalid_actions` — `len(issues)`
- **`failed`** — `crashed or timeouts or bad_status`。docstring どおり「**失敗とは壊れたエージェントのことであって、負けたエージェントのことではない**」

### replay の書き出し

`replay_path` が与えられ、かつ `keep_replay(outcome)` が真（未指定なら常に真）のときだけ JSON を書く。frozen dataclass なので `EpisodeOutcome(**{**vars(outcome), "replay_path": replay_path})` で作り直している。1 エピソード約 5 MB なので保存は既定オフ。

---

## 5. fast パスの 1 エピソード: `fast.py`

### なぜ存在するか

フルシーズンをプロファイルすると **ゲームルールは実行時間の 1.7%** しかない:

| コンポーネント | 時間 | 割合 |
|---|---|---|
| `structify` | 1.00s | 30.5% |
| その他 stdlib | 0.90s | 27.5% |
| `deepcopy` | 0.84s | 25.7% |
| `jsonschema` 検証 | 0.39s | 11.9% |
| コアフレームワーク | 0.08s | 2.6% |
| **ゲームロジック** | 0.06s | **1.7%** |

残りはすべて step ごとのフレームワーク機構。そこで **ルールは一切再実装せず、フレームワークだけ剥がす**: `kaggriculture.interpreter` を素の Python ループから直接呼ぶ。実測 **約 30x 高速**、最終所持金はビット一致（`tests/e2e/src/simulate/test_fast_equivalence.py` で担保）。

### ループ本体

```python
for n in range(spec.steps - 1):          # env.state が既に 1 step 分
    for player, slot in enumerate(slots):
        action, duration = slot.take_turn(state[player].observation)
        state[player].action = action
        # duration を act_timeout / slow_threshold と比較して記録
    engine.interpreter(state, env)
    state[0].observation.step = n + 1    # ★ フレームワークの仕事を肩代わり
```

最終行のコメントが最重要。**`observation.step` の前進はインタプリタではなくフレームワーク（`core.py:626`）の責務**で、これを忘れると `day` / `hour` が凍結し、一日の終わりの処理（水やり判定・雑草発生・家畜生産・町の需要）が一切走らない。それでもエピソードは完走してもっともらしいスコアを出す — まさに equivalence テストが存在する理由。

その他フレームワーク肩代わり項目:
- `DONE` status は `step >= episodeSteps - 1` で立つ（`core.py:295`）→ ここでは `("DONE", "DONE")` を固定で返し、`bad_status` の意味を両エンジンで揃える
- エージェント例外はフレームワークが飲み込む → `_AgentSlot.take_turn` が `PASS_TURN`（`{"farmer": ["PASS"], "hands": [], "market": []}`）にフォールバックし、初回のトレースバックだけ `crash_repr` に記録
- step 履歴は**意図的に保持しない** → replay 不可

戻り値は official と同じ `EpisodeOutcome` なので、**マトリクスランナーから見て 2 つのエンジンは差し替え可能**。

---

## 6. silent no-op の検出: `validate.py`

評価時のみエージェントとエンジンの間に挟まるラッパー。「エージェントが要求したこと」と「エンジンが実際に適用すること」の差分を記録する。提出物には決して入らない（`backend/src/**` は tarball 外）。

### 仕組み

```python
def wrapped(obs):
    action = inner(obs)          # 先にエージェントを呼ぶ
    try:
        self.validate(obs, action)
    except Exception as exc:     # バリデータが実行を壊してはいけない
        self._record("validator_error", repr(exc))
    self._step += 1
    return action                # アクションは無改変で通す
```

- `as_callable()` がパス文字列をエンジン自身の `build_agent` でロードする。**`Agent` クラス経由にしない**のは、`env.run` が既に掛けている計時/捕獲レイヤの内側にもう一段入って duration が二重計上されるため。ロード後は `__code__.co_argcount` で引数個数を見て `built(obs)` か `built(obs, configuration)` かを決める（`TypeError` を catch すると agent 内部の本物の `TypeError` まで飲んでしまう）。
- `max_issues = 200` で上限。系統的に壊れたエージェントが 720 ターン分の同一 issue でレポートを埋めるのを防ぐ。

### 検査項目（各々がエンジンの特定挙動に対応）

**ユニット系** (`_check_units` / `_check_unit`)
- `action` が dict でない → エンジンは PASS を適用
- `farmer` キー欠落、`hands` が list でない
- **hand 数の不一致** — 雇った hand 数とアクション数が違う
- 未知の unit op（`MOVE_OPS` / `SHED_OPS` / `TILE_OPS` / `PASS` 以外）
- `PLANT` の作物引数欠落・未知作物
- **盤外への移動** — エンジンは移動前に境界チェックするので no-op
- **shed 非隣接での shed op** — `PICKUP`/`PLACE`/`DROP` は中央 4 タイルからのみ。ただし `PLACE <animal>` は例外で、エンジンが shed-drop より前に「空きの対応構造物への配置」を解決するため盤上どこからでも合法（`_is_animal_placement` がこの分岐を再現）
- **ロック済みクアドラントでの tile op**

**PLANT 予算** (`_check_plant_budget`)
- エンジンは種の在庫を超える要求があると **その作物の PLANT を全部落とす**（作物単位でアトミック）。1 つ requesting しすぎると、その作物を頼んだ全ユニットのターンが無駄になる — 高くつく silent failure なので専用チェックがある。

**マーケット系** (`_check_market` / `_check_order` / `_check_order_item`)
- `maxMarketOrdersPerTurn`（既定 10）超過 → 超えた分は破棄
- order の形式不正、`[op, item, n]` の n 欠落・非正
- op 別の item 妥当性: `BUY_SEED`→作物、`BUY_ANIMAL`→動物、`BUY_PRODUCT`→**WHEAT と FERTILIZER のみ**（専用ヒント付き）、`SELL`→全 product

すべて `ValidationIssue(step, kind, detail)` として蓄積され、`EpisodeOutcome.issues` に載る。

---

## 7. マトリクス実行: `matrix.py`

### `_Job` — ワーカーが単独で走らせるのに必要なもの一式

`spec` + `act_timeout` + `slow_threshold` + `validate_actions` + `replay_mode` + `replay_path` + `engine`。`run()` が engine で分岐:

```python
if self.engine is Engine.FAST:
    return run_fast_episode(...)
keep = (lambda o: o.failed) if self.replay_mode is ReplayMode.FAILED else None
return run_episode(..., replay_path=self.replay_path, keep_replay=keep)
```

`ReplayMode.FAILED` はここで `keep_replay` コールバックに落ちる — 失敗したエピソードだけ 5 MB を払う。

### 並列化

- `build_jobs(config)` が `config.specs()` を `_Job` 列に変換（replay パスは `_replay_path_for` が `ep0000_starter_seed0_p0.json` 形式で採番）
- `workers <= 1` → `_run_sequential`（in-process なのでトレースバックとデバッガが使える）
- それ以外 → `ProcessPoolExecutor` + `as_completed`。`_run_job` がモジュールレベル関数なのは **spawn で picklable にするため**
- `default_workers()` = `cpu_count() - 1`（`_WORKER_HEADROOM`）— 長時間のマトリクスで対話シェルを固めないため

**ワーカーは `EpisodeOutcome`（小さな dataclass）だけを返し、`env` は決して返さない**。env は約 5 MB にシリアライズされるので、エピソードごとに送り返すと pickle 代がエピソード実行代を上回る。

`run_matrix(config, on_result=...)` は完了順に結果を集めて list で返す（順序が要るなら呼び出し側でソート）。`on_result` は進捗表示用のフック。

---

## 8. 集計と出力: `report.py`

```
outcomes ──┬─ build_health()  → HealthReport
           └─ opponent 別グルーピング → OpponentReport[]
                        ↓
                   MatrixReport ──┬─ render()      人間向けテキスト
                                  ├─ as_dict()     JSON
                                  └─ exit_code     プロセス終了コード
```

- **`OpponentReport`** — 対戦相手ごとの episodes / wins / losses / ties / win_rate / mean_money / mean_margin / **worst_margin**（最悪ケースが平均に埋もれないように）
- **`HealthReport`** — crashes / timeouts / slow_turns / bad_statuses / invalid_actions / max_duration、加えて `crash_samples`（先頭 3 件のトレースバック）と `issue_kinds`（種類別カウント、`Counter.most_common()`）。`clean` プロパティは crash/timeout/bad_status がゼロかどうか（invalid_actions は含まない）
- **`ExitCode`** — `OK=0` / `FAILED=1` / `INVALID_ACTIONS=2`。`exit_code` は「health が clean でなければ FAILED、`strict` かつ invalid_actions ありなら INVALID_ACTIONS、それ以外 OK」。**CI が勝率以外でゲートできる**ようにするための 3 値
- `build_report` は `config.opponents` の順序を保った dict で初期化してからグルーピングするので、**出力順は設定順に一致**する
- `_header` は engine が OFFICIAL でないときだけ `engine=fast` を表示する — fast 実行の数字が検証済みの数字と取り違えられないように

---

## 9. CLI: `__main__.py`

```
uv run python -m simulate --case rulebase/case1 --opponent starter,random
```

処理順:

1. `_parse_opponents` — カンマ区切り分解（空なら `BadParameter`）
2. **`_validate_specs`** — 全 agent を事前解決（typo が「正当な敗北」に化けるのを防ぐ）
3. `--engine fast` + `--replay` の組み合わせを弾く（`SimConfig.__post_init__` と二重の防御）
4. `SimConfig` 構築 — `--workers` 未指定なら `default_workers()`
5. `run_matrix(config)` を計時
6. `build_report` → `render` を stdout（`--quiet` で抑制）
7. `--json` 指定時はサマリ JSON を書く
8. replay 有効時は出力先パスを表示
9. **`sys.exit(report.exit_code)`**

主なオプション: `--episodes` / `--steps` / `--seed`（`--seed i` で episode i は `seed+i`）/ `--swap-sides` / `--engine {official,fast}` / `--replay {none,failed,all}` / `--output-dir` / `--no-validate` / `--strict` / `--act-timeout`。

replay 出力先は既定で `data/output/simulate/<UTCタイムスタンプ>/replays/`。

---

## 10. 後方互換 façade: `runner.py`

マトリクスランナー以前の `run_episode(agents: list) / run_match(...)` API を維持するための層。新規コードは `episode` / `matrix` を使うべき（この形は crash / timeout / invalid-action の詳細を表現できない）。

- `EpisodeResult` — **player インデックス順**の `rewards` / `statuses` / `steps` / `crashed` / `timeouts`。`ok` プロパティは「status が全部 DONE かつ crash も timeout もなし」
- `MatchSummary` — episodes のリストに対する wins / losses / ties / errors / win_rate / mean_money / mean_margin
- `_to_result()` が case 視点の `EpisodeOutcome` を player 順に **戻し**ている（`episode.py` の座標系変換の逆）
- `debug` 引数は受け取るが **無視される**（`del debug`）— エピソードは常に debug モードで走る。クラッシュと敗北を区別する唯一の方法だから
- `run_match(seed=s)` はエピソード i に `s + i` を使う

---

## 11. `jaxenv/` — 別系統の実験

パッケージ本体（`__init__.py` から re-export されない）とは独立した、**GPU バッチ実行が割に合うかを測るための再実装**。

- `state.py` — 公式エンジンのネスト dict 状態を struct-of-arrays に再表現。タイルは「オブジェクト」ではなく `(B, H, W)` の**プレーン**（kind / crop / planted_day / watered_today / ... が各々別配列）。per-tile の分岐は `jnp.where` に。traced 値上に Python 制御フローを置かない
- `env.py` — `jax.jit` 済みバッチ step。**スコープを意図的に絞っている**: farmer 1 体のみ（hand なし）、NW クアドラントのみ（`BUY_LAND` なし）、動物・肥料・町なし、雑草発生なし。op も PASS/移動/PLANT/WATER/HARVEST/DIG と SELL/BUY_SEED だけ
- `town.py`, `benchmark.py` — ベンチは official / fast / jax（複数バッチサイズ）を同一ワークロードで env-steps/sec 比較。コンパイル時間はウォームアップ 1 step で除外して別途報告

**重要な位置づけの違い**: `fast.py` は公式インタプリタを呼ぶ**ラッパー**なので乖離リスクが構造的にない。`jaxenv` は**再実装**なので乖離リスクを負っており、テストの equivalence assertion だけがこれを使用可能にしている。docstring も「スコープ限定を踏まえて数字を読め、完全な移植の下限として楽観的に見積もれ」と明記している。

なお `jax` は `pyproject.toml` に載っていない（`kaggle-environments` が直接要求するので必ず存在する）。`jax-metal` の venv 導入は有害 — 全テストの `jax.devices()` を奪い、CPU より約 100x 遅い。

---

## 12. 全体フロー（1 枚図）

```
CLI / SimConfig
      │  iter_specs(): opponents × episodes × seats
      ▼
  MatchSpec[]
      │  build_jobs()
      ▼
   _Job[] ──── workers>1 ? ProcessPoolExecutor : 逐次
      │
      ├── engine=official ──► run_episode()
      │        resolve_agent ×2 → ActionValidator.wrap(case)
      │        → make(debug=True) → env.run() [stderr捕獲, 例外捕捉]
      │        → _harvest / _turn_costs / _collect_stderr
      │        → (条件付き) replay JSON 書き出し
      │
      └── engine=fast ─────► run_fast_episode()
               resolve_agent ×2 → 手動ループ
               → interpreter(state, env) × (steps-1)
               → observation.step を手で前進
               → 例外は PASS フォールバック + crash_repr 記録
      │
      ▼
 EpisodeOutcome[]   ← 常に case 視点、env は返さない（pickle コスト回避）
      │  build_report()
      ▼
 MatrixReport { OpponentReport[], HealthReport }
      │
      ├── render()   → 勝率表 + health ブロック（常時表示）
      ├── as_dict()  → JSON
      └── exit_code  → 0 / 1 (broken) / 2 (strict + invalid actions)
```

---

## 13. 読むときに効く着眼点

| 疑問 | 見る場所 |
|---|---|
| なぜ `debug=True` 固定なのか | `episode.py` 冒頭の表、`runner.py:147` の `del debug` |
| なぜ席を入れ替えるのか | `config.py` `MatchSpec` docstring（player 0 が先に市場へ注文） |
| timeout はどこで分かるのか | `episode.py` `_turn_costs`（`env.logs` だけが証拠） |
| fast エンジンが壊れるとしたら | `fast.py` の `state[0].observation.step = n + 1` を消したとき |
| 不正アクションの一覧 | `validate.py` の `_check_unit` / `_check_order` の各 `_record` |
| CI のゲート条件 | `report.py` `ExitCode` と `MatrixReport.exit_code` |
| replay が出ない | `SimConfig.__post_init__`（fast では原理的に不可）、`ReplayMode`、`output_dir` |
