`rulebase/case7` の毎ターン処理を追ってドキュメント化しました。

**出力**: `.claude/skills/code-explain-workspace/iteration-1/eval-2-single-agent-case7/without_skill/outputs/case7_turn_flow.md`

## 1 ターンの流れ（完全ステートレス、入力は `obs` のみ）

| 段 | 関数 | やること |
|---|---|---|
| ① | `observe.parse()` | `obs` → `Snapshot`。全アクセス `.get()` の防御的パース。自farm 10×10 + 相手farm + 市場 + 倉庫/種/各ユニット手持ち |
| ② | `tasks.build_tasks()` | 盤面走査して「今やる価値のある仕事」を全列挙。優先度 0–11 付き |
| ③ | `tasks.assign()` | 農夫→日雇いの順に `(優先度, 距離)` で貪欲に 1 件ずつ確保。取れなければ倉庫へ退避行動 |
| ④ | `market.build_market()` | SELL → HIRE → 餌 → 種 → 家畜 → 土地 の順で組んで 10 件に切る |
| ⑤ | `main.agent()` | 全体を `try/except` で包み、失敗時は手数分の `PASS` |

## 優先度設計の核

エンジンの 2 つのハード締切（未水やり 2 日で雑草化 / 未給餌 2 日で家畜が逃走）が順序を決めている。
`FEED(0) → FETCH_FEED(1) → RESCUE_WATER(2) → HARVEST(3) → …WATER(7) → CARE(8) → PLANT(9) → DIG(10)`

## 割り当ての肝: ゾーン制と `zone_free`

盤面を列方向に「ユニット数」本の帯へ分け、自ゾーン外の仕事は +100 ペナルティ。**ただし FEED / 救出WATER / 家畜HARVEST / CARE は `zone_free` で全農場から取れる**。これが case7 最大の変更点で、case2 では家畜が数列に固まるせいで 8 頭中 4 頭しか給餌できず年間 30 頭を餓死させていた（→ 5 頭に改善、アブレーション **+14,714**）。

## 市場の組み立て

- SELL が常に先頭（同ターン内で後続購入を賄える）／注文は末尾から黙って捨てられるので順序＝優先度
- 売却順は `売上 ÷ (1+自分で起こす価格下落)` でランク付け
- 雇用は `hour==0` のみ、人数は `ceil(仕事量/7)` を 6–12 でクランプ（費用が fib(n)）
- 家畜購入は day≤18・空き牧場数まで・現金留保 `400 + 120×頭数` を残す範囲
- `step ≥ 700` で清算モード → SELL のみ、バッチ上限解除

## フラグの実測結果（config.py に記録済み）

| フラグ | 状態 | 効果 |
|---|---|---|
| `ENABLE_HERD_EXPANSION` | ON | +3,507 |
| `ENABLE_OPPONENT_AWARE_MELON` | OFF | ±0（相手が閾値に届かず一度も発火しない＝休眠コード） |
| `ENABLE_STRAWBERRY` | OFF | −1,919 |

補足: builtin 相手には case2 比 +28% ですが、case2 との直接対戦は 7/16 で負けます。両者が同じ MELON/MILK を投げて価格が共倒れするため（day29 に MELON $4）、大きい群れの餌代だけ case7 が損をする構造です。
