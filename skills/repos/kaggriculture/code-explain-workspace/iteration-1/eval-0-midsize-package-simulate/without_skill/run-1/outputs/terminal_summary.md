`backend/src/simulate` を読み解きました。詳細は `simulate-walkthrough.md` にまとめています。

## 設計の出発点

`kaggle-environments` は**エージェントの故障を隠す**（クラッシュもタイムアウトも `status=DONE`、不正アクションは silent no-op）。だから「壊れた」と「弱い」が区別できない。このパッケージは検出チャネルを 3 本に分けてこれを解いています。

| チャネル | 手段 | 実装 |
|---|---|---|
| crash | `debug=True` で `env.run` の再送出例外を捕捉 | `episode.py:_execute` |
| timeout | `env.logs[step][player]["duration"]` を直読 | `episode.py:_turn_costs` |
| invalid action | エンジンに渡す前にアクションを検査 | `validate.py` |

## レイヤ構成

```
__main__.py   typer CLI (python -m simulate)
report.py     MatrixReport / HealthReport / ExitCode(0/1/2)
matrix.py     SimConfig → _Job[] → 逐次 or ProcessPool
episode.py    official: env.run 経由（replay 可）
fast.py       fast:     interpreter 直叩き（約30x、replay 不可）
config.py     MatchSpec / SimConfig / Engine / ReplayMode
agents.py     spec → builtin名 or main.py 絶対パス
validate.py   ActionValidator
jaxenv/       JAX バッチ再実装（別系統・スコープ限定の実験）
```

## エピソード実行の流れ

```
SimConfig.iter_specs()   opponents × episodes × 席(swap_sides)
  → MatchSpec[] → build_jobs() → _Job[]
  → workers>1 なら ProcessPool（返すのは EpisodeOutcome のみ。env は 5MB で pickle 代が実行代を超える）
  → engine 分岐
      official: resolve_agent×2 → Validator.wrap(case側) → make(debug=True) → env.run
                → _harvest / _turn_costs / _collect_stderr → 条件付き replay 書き出し
      fast:     手動ループで interpreter(state, env) を steps-1 回
  → EpisodeOutcome[]（常に case 視点）→ build_report → render / JSON / exit_code
```

## 特に効いている設計判断

- **`EpisodeOutcome.failed`** = crash or timeout or bad_status。「失敗＝壊れたエージェント、負けたエージェントではない」を型で表現。health ブロックは verbose 裏でなく常に勝率の隣に出る。
- **`resolve_agent` を事前実行**（CLI `_validate_specs`）。case 名の typo をエンジンは黙って no-op に差し替えるので、放置すると全体が「正当な敗北」に見える。
- **fast エンジンの正体**。プロファイル上ゲームロジックは実行時間の 1.7%、残りは `structify`/`deepcopy`/`jsonschema` などのフレームワーク機構。なのでルールは再実装せず公式 interpreter を直接呼ぶ = 乖離リスクが構造的にない。ただし `state[0].observation.step = n+1` はフレームワーク側の責務の肩代わりで、**これを消すと day/hour が凍結して end-of-day 処理が全部止まるのに、それらしいスコアで完走する**（e2e の equivalence テストが番人）。
- **replay は fast で原理的に不可**（step 履歴を持たないのが速さの理由）。`SimConfig.__post_init__` と CLI の二重で弾く。
- **`swap_sides`** は公平性のため。player 0 が先に共通マーケットへ注文を出すので席順が結果に効く。
- **`ExitCode` が 3 値**（OK / FAILED / INVALID_ACTIONS）。CI が勝率以外でゲートできる。
- **`jaxenv/` は位置づけが違う**。`fast` はラッパーだが jaxenv は再実装なので乖離リスクを負う。スコープも farmer 1体・NW のみ・動物/肥料/町なしに絞った「GPU バッチが割に合うか」の測定用。
