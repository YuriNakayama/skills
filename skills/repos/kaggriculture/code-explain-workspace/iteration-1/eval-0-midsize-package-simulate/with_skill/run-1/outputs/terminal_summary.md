`backend/src/simulate` の実装解説を書きました。

**出力**: `docs/develop/code_explanation/20260811_simulate.md`
**規模**: 15 ファイル / 2,962 行（`simulate/` 直下 10 ファイルは全文精読、`jaxenv/` 5 ファイルは概観）
**コミット**: `133e83b`

### 入口

| 入口 | 実体 |
|---|---|
| `dev/simulate` | `python -m simulate`（typer CLI） |
| `simulate.run_matrix(config)` | `matrix.py:108` — 主 API |
| `simulate.run_episode(agents, ...)` | `runner.py:133` — **旧** 互換 API |
| `python -m simulate.jaxenv.benchmark` | JAX ポートの計測 |

層構造は `config ← {agents, episode/fast, validate} ← matrix ← report ← __main__` の一方向。

### 冷たく読むと驚くところ

1. **`from simulate import run_episode` は旧 API**（`agents: list` を取る）。`MatchSpec` を取る新しい方は `run_single_episode` という別名で公開されている。
2. **`debug=True` は常時オン**。デバッグ用フラグではなく、クラッシュを「弱いだけのエージェント」と区別する唯一の手段。`runner.run_episode(debug=False)` は無視される（`del debug`）。
3. **fast パスは `state[0].observation.step = n + 1` を手で進めている**（`fast.py:137`）。これはフレームワーク側の仕事で、消しても例外は出ずスコアもそれらしく出るが `day`/`hour` が凍って end-of-day 処理が全部死ぬ。等価性テストだけが頼り。ちなみに fast が 30 倍速いのは、フルシーズンのうちゲームロジックが **1.7%** しかなく残りが `structify`/`deepcopy`/`jsonschema` だから。
4. **`PLANT` の種不足はそのターン・その作物の `PLANT` を全部巻き添えにする**（エンジン側の挙動）。validator が専用 issue を立てているのはそのため。
5. **`_run_parallel` は完了順に返る**。seed 順を仮定して添字で拾うと静かに取り違える。

### ついでに見つけた点

`SimConfig.extra_config` は定義されているものの `matrix.build_jobs` が `_Job` に転送していないため、**`run_matrix` 経由では無視されます**（`episode.run_episode` を直接呼んだときだけ効く）。意図的な線引きか漏れかはコードからは判断できないので、文書には「未確認事項」として残しました。

深掘りしたい章があれば、その部分を再度読んで同じファイルに追記します。
