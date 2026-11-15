# ターミナルサマリ

`rulebase/case7` の実装解説を書きました。

**出力**: `docs/develop/code_explanation/20260811_rulebase_case7.md`
(本評価では `outputs/20260811_rulebase_case7.md` に配置)

| 項目 | 値 |
|---|---|
| 対象 | `backend/pipeline/rulebase/case7/` |
| 規模 | 5 ファイル / 1,434 行 |
| 読み込み深度 | 全ファイル精読 |
| コミット | `133e83b` |

## 入口

`main.py:agent(obs)` のみ。内部状態を持たない **毎ターン全再計算型** で、
`parse → build_tasks → assign → build_market` の 4 段を 720 回繰り返します。
ハーネスが「最後に定義された callable」を拾うため `agent` はファイル末尾固定、
`__file__` 無しで `exec` されるため相対 import ではなく裸名 import。

## 毎ターンの流れ (要約)

1. `observe.parse` — 生 obs を `Snapshot` へ防御的にパース (10×10 に正規化)
2. `tasks.build_tasks` — 盤面全体から Task を全列挙 (優先度 0〜11)
3. `tasks.assign` — 農夫→ハンドの順に `(優先度, ゾーン, 距離)` で貪欲割当。
   目的地に居れば op 実行、居なければ BFS で 1 歩
4. `market.build_market` — SELL 先頭 → 雇用 → 飼料 → 種 → 家畜 → 土地、10 件で打ち切り

## 冷めた目で読むと驚くところ 5 つ

1. **`zone_free` がこの case の本体**。ゾーン外作業に +100 のペナルティを課す
   case2 の仕組みが、家畜が数列に固まると「担当ゾーンのユニットしか給餌できない」
   という餓死バグになっていた。締切系 (FEED/救出WATER/HARVEST/CARE) だけ全域可に
   した修正が、移植した 3 機構の合計より大きい **+14,714**。

2. **`melon_tiles_per_quadrant()` は実質デッドコード**。フラグ OFF なので 1 行目で
   定数 10 を返す。残り 10 行は一度も実行されない (実測 ±0 = 一度も発火しない)。

3. **収穫物の倉庫搬入がタスクではなく idle 行動**。`_idle_action` にしかないので、
   ユニットが暇にならない限り produce は倉庫に入らない = 売れない。

4. **静かに失敗する経路が複数**。`_parse_grid` は欠損行を `LOCKED` で埋めるので、
   obs の形が変われば「土地が無い」と解釈して沈黙する。未知の `kind` は `EMPTY`
   になり上書き作付けの対象になる。いずれも例外にならない。

5. **case7 は builtin に +28% で勝つが case2 との直接対戦で 7/16 と負け越す**。
   両者が同じ MELON/MILK を同じ板に投げて価格が共倒れ (day29 で MELON 4、MILK 26)。
   群れを増やしても売上は増えず、飼料と購入費だけ増える。

## その他の指摘

- `_sell_batch_size` は引数 `inventory` を受け取るが本体で未使用
- `Snapshot.unlocked_shops` / `opponent_money` / `Tile.consecutive_unfed` はパース済みだが未使用
- `config.SHOPS` / `PRODUCTS` はどこからも import されていない
- `main.py` と `config.py` の docstring がコピー元の「case2」のまま
- `MARKET_PARAMS` はエンジン 1.32.6 の手動ミラーで、エンジン更新時に黙ってずれる
