`docs/develop/code_explanation/20260811_rulebase_case7.md` に書き出しました。

**対象**: `backend/pipeline/rulebase/case7/` — 5 ファイル / 1,544 行（全ファイル精読）
**入口**: `main.py:agent(obs)` ただ 1 つ。ハーネスが 720 回呼ぶ

### 毎ターンの 4 段パイプライン

| # | 処理 | 場所 |
|---|---|---|
| 1 | `parse(obs)` → `Snapshot`（全アクセス防御的） | observe.py:175 |
| 2 | `build_tasks(snap)` → やる価値のある仕事を全列挙 | tasks.py:257 |
| 3 | `assign(snap, tasks)` → 優先度 × 距離で貪欲割り当て | tasks.py:389 |
| 4 | `build_market(snap)` → 注文を優先度順に積んで先頭 10 件 | market.py:266 |

依存は `config ← observe ← tasks ← market ← main` の一方向。外部ライブラリはゼロ（numpy すら不使用）。

### 冷えた目で読むと驚くところ 5 つ

1. **`zone_free` が case7 最大の稼ぎ頭（+14,714）** — 移植機構ではなく case2 のバグ修正。ゾーン制約で家畜が餓死していた（季節 30 頭ロス → 5 頭）
2. **OFF のフラグ 2 つは「未完成」ではなく測定済みの失敗** — strawberry −1,919、opponent-aware melon ±0（発火する相手がラダーにいない）
3. **`market.py` は市場以外もやる** — `HIRE` と `BUY_LAND` もここ。エンジンの market チャンネル仕様のため
4. **step 700 で挙動が丸ごと切り替わる** — 全量売却モード、購入は全停止。実行される最終 step は 718
5. **`tasks.py` / `market.py` に防御がない** — `CROPS[...]` 等が KeyError を投げうる。受け止めるのは `agent` の except だけで、その場合そのターンは丸ごと PASS

### ついでに見つけたもの
- `unlocked_shops` / `opponent_money` はパース済みだが**誰も読んでいない**（町の店は価格を支える唯一のシンクなのに未活用）
- `animal_product()` / `animal_cost()` は呼び出し元なし
- `main.py` の docstring が「rulebase/case2」と名乗ったまま
