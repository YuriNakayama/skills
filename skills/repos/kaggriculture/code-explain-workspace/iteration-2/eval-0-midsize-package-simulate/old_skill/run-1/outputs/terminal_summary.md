`backend/src/simulate/` の実装解説を書きました。

**出力**: `docs/develop/code_explanation/20260811_simulate.md`
**規模**: 15 ファイル / 2,962 行（`simulate/*.py` 10 ファイルは精読、`jaxenv/` 5 ファイルは概観）
**コミット**: `133e83b`

## 入口

| 入口 | 用途 |
|---|---|
| `python -m simulate --case ... --opponent ...` | CLI（主経路） |
| `simulate.run_matrix(SimConfig)` | ライブラリ主経路 |
| `simulate.run_single_episode(MatchSpec)` | 単一エピソード |
| `python -m simulate.jaxenv.benchmark` | 別系統のベンチマーク |

依存は一方向: `__main__ → matrix → {episode, fast} → {agents, validate} → config`

## 冷たく読むと驚くところ 5 つ

1. **このパッケージの存在理由は「エンジンが故障を隠す」こと。** crash も timeout も `status=DONE` で終わり、不正アクションは黙って no-op。だから crash / timeout / invalid-action を独立 3 系統で検出している。
2. **`from simulate import run_episode` は旧 API を掴む。** 新 API は `run_single_episode`。`runner.py` は後方互換ファサードで、`debug` 引数は受け取って捨てられる。
3. **fast エンジンが 30x 速いのはルール再実装のせいではない。** ゲームロジックは実行時間の 1.7% で、残りは `structify`/`deepcopy`/`jsonschema`。ルールは公式のまま、機構だけ剥がしている。
4. **fast は `observation.step` を手で進める必要がある。** 忘れると day/hour が凍り、日次処理が全部消えるのにスコアはそれらしく出る。
5. **agent 名の typo だけは即例外。** エンジンは未知の case を黙って no-op エージェントに差し替えるため、放置すると評価全体が「正当な負け」に見える。

おまけ: PLANT の種不足はアトミックに全滅（その作物の PLANT が全ユニット分捨てられる）。`jaxenv/` は本流ではなく、作物・市場のコアのみの実験的 GPU 移植。

## 気づいた点

`SimConfig.extra_config` は `_Job` に渡されておらず、`run_matrix` 経路では効きません（`episode.run_episode` 直呼び時のみ有効）。意図的か漏れかは未確認です。
