# スコープ解決の経緯

ユーザーの指示は「JAX の環境まわりのコード」— 具体的なパス指定なし。以下の手順で確定した。

## 1. リポジトリ全体で JAX 言及を検索

```bash
grep -ril "jax" --include="*.py" --include="*.toml" --include="*.md" .
```

`.venv` / `node_modules` / `.claude/skills` を除外した結果、ヒットは 6 箇所のみ:

| パス | 種別 |
|---|---|
| `backend/src/simulate/jaxenv/env.py` | 実装 |
| `backend/src/simulate/jaxenv/state.py` | 実装 |
| `backend/src/simulate/jaxenv/town.py` | 実装 |
| `backend/src/simulate/jaxenv/benchmark.py` | 実装 |
| `backend/tests/e2e/src/simulate/test_jaxenv_equivalence.py` | テスト |
| `docs/plans/simulator/jax-gpu.md` | 設計・計測記録 |

`backend/.venv/**` と `.claude/worktrees/**` のヒットは依存ライブラリ本体 / ワークツリーの複製なので除外。

## 2. 「環境まわり」の解釈

「環境」はこの文脈で二重に一致する:

- **JAX 用語**としての強化学習環境 (environment)
- **パッケージ名**が文字通り `jaxenv`（= JAX environment）

`backend/src/simulate/jaxenv/` がそのものずばりであり、他に競合候補がない。「環境構築 (venv / 依存関係)」の意味に読む余地もあるが、リポジトリに JAX 専用の環境構築コードは存在せず（`pyproject.toml` に `jax` の記載すら無い — `kaggle-environments` の推移的依存で入る）、そちらの解釈では解説すべきコードがほぼ無い。よって RL 環境の実装と解釈した。

## 3. 確定スコープ

**主対象**: `backend/src/simulate/jaxenv/` — 5 ファイル / 1,016 行

1,016 行は全ファイル精読が可能な規模なので、深度を下げる判断は不要だった。

**参考として読んだもの**（文書の対象そのものではないが、理解と裏取りに必要）:

- `backend/tests/e2e/src/simulate/test_jaxenv_equivalence.py` (197 行) — 「何が公式エンジンと一致することを保証されているか」の実体。再実装である以上ここが仕様書に相当する
- `docs/plans/simulator/jax-gpu.md` (255 行) — なぜこの設計なのか、計測結果はどうだったか。コードだけでは分からない「なぜ」の一次情報
- `backend/src/simulate/fast.py`（冒頭 30 行）・`backend/src/simulate/__init__.py` — 対になる別実装との棲み分け、および jaxenv が公開 API に含まれていない事実の確認

## 4. ユーザー確認について

skill は「曖昧なら具体パスに解決して確認してから精読せよ」と指示している。今回は非対話実行のため確認ステップは省略したが、候補が実質 1 つに絞られており（`jaxenv` という名前が指示語とほぼ一致）、誤読のリスクは低いと判断した。文書ヘッダに対象パスを明記してあるので、想定と違えば読み手がすぐ気付ける。
