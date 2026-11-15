# Skills hub

`~/project` 配下で使う Claude Code スキルの正本。各リポジトリや `~/.claude/skills` にあるものはここから配布したコピー（またはリンク）で、直接編集しない。

## 構成

| ディレクトリ | 内容 | 配布先 | 方式 |
|---|---|---|---|
| `global/` | どのプロジェクトでも使うスキル | `~/.claude/skills/<name>` | シンボリックリンク |
| `shared/` | 開発リポジトリ共通のスキル | `<repo>/.claude/skills` | コピー（`repos.json` の `shared` に列挙したものだけ） |
| `repos/<repo>/` | リポジトリ固有、またはそのリポジトリ向けに改変したスキル | `<repo>/.claude/skills` | コピー（`repos.json` の `own`） |
| `codex/` | Codex 向け（`.agents/skills`）版 | `<repo>/.agents/skills` | コピー（`repos.json` の `codex: true`） |

リポジトリへはリンクではなくコピーで配る。リポジトリ外を指すリンクはクローン先やクラウドセッションで壊れるため。

## 使い方

```bash
bin/sync.py --check   # 配布先と正本のずれを表示（ずれがあれば exit 1）
bin/sync.py           # 配布する
bin/sync.py --repo research
```

配布先の各 `skills/.hub-manifest` に、ハブが管理しているスキル名が書かれる。

## 運用ルール

- 新しいスキルはここにだけ作る。全プロジェクト用なら `global/`、特定リポジトリ用なら `repos/<repo>/` に置き、`repos.json` に追記して `bin/sync.py`。
- リポジトリ側で改良したら、その内容をここへ戻してから `bin/sync.py`。
- 共通スキルをリポジトリ向けに改変する場合は、`repos/<repo>/<name>` に置いて `repos.json` の `shared` から `own` へ移す。
- `~/.claude/skills/synced` と `learned` は Claude アプリが管理するので触らない。

## 未整理の課題

移行時点の各リポジトリの中身をそのまま取り込んだため、同じスキルの改変版が `repos/` に残っている。統合する場合は差分を見て `shared/` を更新し、`own` から外す。

- research 系（clustering / gather / retrieval）: research 版（7 月改訂）が最新。realtime も独自版。
- experiment 系・dvc: reinforce・kaggriculture・ptcg（carrier と同一）の 3 系統に分岐。reinforce が最新。
- `repos/realtime/research-gather` は SKILL.md が無く evals だけ。移行前から壊れている。
- carrier は ptcg の丸コピーで git 管理外。
