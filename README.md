# Skills hub

`~/project` 配下で使う Claude Code スキルの正本。各リポジトリや `~/.claude/skills` にあるものはここから配布したコピー（またはリンク）で、直接編集しない。

## 構成

| ディレクトリ | 内容 | 配布先 | 方式 |
|---|---|---|---|
| `global/` | どのプロジェクトでも使うスキル | `~/.claude/skills/<name>` | シンボリックリンク |
| `shared/` | 開発リポジトリ共通のスキル | `<repo>/.claude/skills` | コピー（`repos.json` の `shared` に列挙したものだけ） |
| `repos/<repo>/` | リポジトリ固有、またはそのリポジトリ向けに改変したスキル | `<repo>/.claude/skills` | コピー（`repos.json` の `own`） |

リポジトリへはリンクではなくコピーで配る。リポジトリ外を指すリンクはクローン先やクラウドセッションで壊れるため。

## 使い方

```bash
bin/sync.py --check                    # 状態を表示（ずれがあれば exit 1）
bin/sync.py                            # 配布する（リポジトリ側で変更されたスキルは上書きせずスキップ）
bin/sync.py --repo research            # 1 リポジトリだけ
bin/sync.py import research            # research 側の変更と未管理スキルをすべて取り込む（未管理は own になるので、unmanaged があるときは名前を指定する）
bin/sync.py import research pr         # 指定したスキルだけ取り込む（今の分類のまま。shared なら shared/pr へ）
bin/sync.py import research pr --to shared   # 共通化（shared/pr へ。使っている全リポジトリに配布される）
bin/sync.py import research pr --to own      # 共通化の解除（research にある今の内容を repos/research/pr へ）
dev/path-check                         # 切れたパスと、配布できない絶対パスの検査
```

配布先の各 `.claude/skills/.hub-manifest` に、前回配布した時点の各スキルのハッシュが記録される。ハブ、リポジトリ、このハッシュを比べて、どちらが変わったかを判定する。

| 状態 | 意味 | 配布 | 取り込み |
|---|---|---|---|
| `new` | リポジトリにまだ無い | 配布する | 対象外 |
| `hub` | ハブだけ変わった | 上書きする | 拒否（配布すればよい）。`--to own` での共通化の解除だけ可（旧版のまま own になる） |
| `repo` | リポジトリだけ変わった | スキップ | 取り込む |
| `both` | 両方変わった | スキップ | `--force` が必要 |
| `unknown` | 差分があり、記録がない | スキップ | `--force` が必要 |
| `unmanaged` | リポジトリにだけあり、ハブで未管理 | 対象外（`--check` は exit 1 のまま） | own として取り込む。同名の `shared/` に `--to shared` で入れるのは拒否（`--force` で上書き） |

`--force` を付けた配布は、リポジトリ側の変更を上書きする。

## 運用ルール

- 新しいスキルは原則ここで作る。全プロジェクト用なら `global/`、特定リポジトリ用なら `repos/<repo>/` に置き、`repos.json` に追記して `bin/sync.py`。
- リポジトリ側で編集・作成したスキルは `bin/sync.py import <repo>`（`unmanaged` があるときはスキル名を指定する）でハブに取り込み、`git diff` で確認してからコミットする。取り込みは今の分類を保つ（shared のスキルを取り込むと、使っている全リポジトリに配布される）。
- 共通化は `import <repo> <name> --to shared`、解除は `import <repo> <name> --to own`。改変版の統合は `shared/` に直接書いて `repos.json` を移す。
- `shared/` と `repos/` のスキルには `~/project/...` などの絶対パスを書かない（コピー先のクローン・worktree・クラウドで壊れるため）。`global/` は例外。書き方は `global/skill-share/references/portability.md`。
- 配布前に `dev/path-check` を通す。修正待ちの既知の違反は `dev/path-check` 先頭の `ALLOW` に件数と理由を添えて載せ、直したら消す（件数が合わなければエラー）。
- 配布後は各リポジトリで `.claude/skills` の変更をコミットする。
- `~/.claude/skills/synced` と `learned` は Claude アプリが管理するので触らない。

手順は 2 つのグローバルスキルにまとめてある。

| スキル | 役割 |
|---|---|
| `skill-sync` | 取り込みと配布（分類は変えない） |
| `skill-share` | 共通化・非共通化・配布の停止、改変版の統合、移植性（絶対パスなど）の修正 |

## 未整理の課題

移行時点の各リポジトリの中身をそのまま取り込んだため、同じスキルの改変版が `repos/` に残っている。統合する場合は差分を見て `shared/` を更新し、`own` から外す。

- research 系（clustering / gather / retrieval）: research 版（7 月改訂）が最新。realtime も独自版。
- experiment 系・dvc: reinforce・kaggriculture・ptcg（carrier と同一）の 3 系統に分岐。reinforce が最新。
- `repos/realtime/research-gather` は SKILL.md が無く evals だけ。移行前から壊れている。
- carrier は ptcg の丸コピーで git 管理外。`repos/carrier` の dvc・experiment-analysis は ptcg（`01_kaggle/ptcg`）を指したままで、`03_carrier` 自身には `.dvc` も `backend/` も無い。
