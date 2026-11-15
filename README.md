# Skills hub

`~/project` 配下で使う Claude Code スキルの正本。各リポジトリや `~/.claude/skills` にあるものはここから配布したコピー（またはリンク）で、直接編集しない。

## 構成

| ディレクトリ | 内容 | 配布先 | 方式 |
|---|---|---|---|
| `skills/global/` | どのプロジェクトでも使うスキル | `~/.claude/skills/<name>` | シンボリックリンク |
| `skills/shared/` | 開発リポジトリ共通のスキル | `<repo>/.claude/skills` | コピー（`repos.json` の `shared` に列挙したものだけ） |
| `skills/repos/<repo>/` | リポジトリ固有、またはそのリポジトリ向けに改変したスキル | `<repo>/.claude/skills` | コピー（`repos.json` の `own`） |

リポジトリへはリンクではなくコピーで配る。リポジトリ外を指すリンクはクローン先やクラウドセッションで壊れるため。

その他:

| パス | 内容 |
|---|---|
| `skills/repos.json` | 配布先のリポジトリと、それぞれに配るスキルの一覧。`path` はハブのルートからの相対パス（`skills/` からではない） |
| `src/` | ハブのツール（Python）。入口は `src/hub.py`（サブコマンド `sync`・`import`・`check-paths`・`check-duplicates`）。中身は `common.py`（共通）、`sync.py`（配布と取り込み）、`path_check.py`（パスの検査）、`duplicated_skill.py`（重複の検査） |
| `pyproject.toml`、`.python-version`、`uv.lock` | Python の環境（uv で管理） |

## 使い方

Python は uv で管理する（`.python-version` で 3.13 に固定。`src/` のツールは標準ライブラリだけを使う）。ハブで `uv run` を使って実行する（初回は `.venv` が作られる）。

```bash
cd ~/project/98_skills
uv run src/hub.py sync --check                    # 状態を表示（ずれがあれば exit 1）
uv run src/hub.py sync                            # 配布する（リポジトリ側で変更されたスキルは上書きせずスキップ）
uv run src/hub.py sync --repo research            # 1 リポジトリだけ
uv run src/hub.py import research                 # research 側の変更と未管理スキルをすべて取り込む（未管理は own になるので、unmanaged があるときは名前を指定する）
uv run src/hub.py import research pr              # 指定したスキルだけ取り込む（今の分類のまま。shared なら skills/shared/pr へ）
uv run src/hub.py import research pr --to shared  # 共通化（skills/shared/pr へ。使っている全リポジトリに配布される）
uv run src/hub.py import research pr --to own     # 共通化の解除（research にある今の内容を skills/repos/research/pr へ）
uv run src/hub.py register foo ../01_kaggle/foo   # リポジトリを管理下に入れる（登録と pre-commit の設置。--shared a,b で配るスキルを指定）
uv run src/hub.py check-repo --here               # 今いるリポジトリに、ハブへ取り込まれていない変更が無いか（pre-commit から使う）
uv run src/hub.py check-paths                     # 切れたパスと、配布できない絶対パスの検査
uv run src/hub.py check-duplicates                # スキルの重複（層をまたいだ同名、内容が同一、改変版の分岐、空のスキル）の検査
```

配布先の各 `.claude/skills/.hub-manifest` に、前回配布した時点の各スキルのハッシュが記録される。ハブ、リポジトリ、このハッシュを比べて、どちらが変わったかを判定する。

| 状態 | 意味 | 配布 | 取り込み |
|---|---|---|---|
| `new` | リポジトリにまだ無い | 配布する | 対象外 |
| `hub` | ハブだけ変わった | 上書きする | 拒否（配布すればよい）。`--to own` での共通化の解除だけ可（旧版のまま own になる） |
| `repo` | リポジトリだけ変わった | スキップ | 取り込む |
| `both` | 両方変わった | スキップ | `--force` が必要 |
| `unknown` | 差分があり、記録がない | スキップ | `--force` が必要 |
| `unmanaged` | リポジトリにだけあり、ハブで未管理 | 対象外（`--check` は exit 1 のまま） | own として取り込む。同名の `skills/shared/` に `--to shared` で入れるのは拒否（`--force` で上書き） |

`--force` を付けた配布は、リポジトリ側の変更を上書きする。

## リポジトリを管理下に入れる

手順は skill-register スキルにまとめてある（配る shared スキルの選定、既存のフックの仕組みへの組み込みなど、判断が要る部分を含む）。

1. `uv run src/hub.py register <名前> <path> [--shared a,b]` を実行する。
   - `skills/repos.json` に登録する（リポジトリに既にあり、`skills/shared` と同一のスキルは自動で shared に入る）。
   - pre-commit を設置する。`.claude/skills` の変更をコミットしようとしたとき、ハブに取り込まれていない変更や
     未管理のスキルがあると止める（`git commit --no-verify` で飛ばせる。ハブや uv が無い環境では何もしない）。
     既存の `.git/hooks/pre-commit` には追記する。husky（`core.hooksPath`）や `.pre-commit-config.yaml` があるときは
     触らず、追記する行を表示するので、そのフックの仕組みに自分で足す。
2. 表示された既存スキルの振り分けを、skill-sync（取り込み）と skill-share（統合・共通化）で済ませる。
3. `uv run src/hub.py sync --repo <名前>` で配布し、リポジトリ側で `.claude/skills` と `.hub-manifest` をコミットする。

既に登録済みのリポジトリに pre-commit を入れる（入れ直す）ときは `uv run src/hub.py install-hook <名前>`（全部なら `--all`）。

Claude Code のユーザー設定（`~/.claude/settings.json`）の `PostToolUse` フックからも `uv run src/hub.py claude-hook` を呼んでいる。
Claude が管理下のリポジトリの `.claude/skills` を書くと、ハブへ取り込まれていない変更や未管理のスキルをその場で Claude に伝える
（コミットを待たずに気づくため。止めはしない）。

worktree の中でコミットが止まったときは、取り込み（`import`）がメインの作業ツリーの `.claude/skills` から読む点に注意する
（worktree にしか無い変更は、メインの作業ツリーに持ってくるか、マージしてから取り込む）。

## 運用ルール

- 新しいスキルは原則ここで作る。全プロジェクト用なら `skills/global/`、特定リポジトリ用なら `skills/repos/<repo>/` に置き、`repos.json` に追記して `uv run src/hub.py sync`。
- リポジトリ側で編集・作成したスキルは `uv run src/hub.py import <repo>`（`unmanaged` があるときはスキル名を指定する）でハブに取り込み、`git diff` で確認してからコミットする。取り込みは今の分類を保つ（shared のスキルを取り込むと、使っている全リポジトリに配布される）。
- 共通化は `import <repo> <name> --to shared`、解除は `import <repo> <name> --to own`。改変版の統合は `skills/shared/` に直接書いて `repos.json` を移す。
- `skills/shared/` と `skills/repos/` のスキルには `~/project/...` などの絶対パスを書かない（コピー先のクローン・worktree・クラウドで壊れるため）。`skills/global/` は例外。書き方は `skills/global/skill-share/references/portability.md`。
- 配布前に `uv run src/hub.py check-paths` を通す。修正待ちの既知の違反は `src/path_check.py` 先頭の `ALLOW` に件数と理由を添えて載せ、直したら消す（件数が合わなければエラー）。
- 配布後は各リポジトリで `.claude/skills` の変更をコミットする。
- `~/.claude/skills/synced` と `learned` は Claude アプリが管理するので触らない。

手順は 2 つのグローバルスキルにまとめてある。

| スキル | 役割 |
|---|---|
| `skill-sync` | 取り込みと配布（分類は変えない） |
| `skill-share` | 共通化・非共通化・配布の停止、改変版の統合、移植性（絶対パスなど）の修正 |
| `skill-register` | リポジトリを管理下に入れる（shared の選定、登録、pre-commit、振り分けのまとめ、コミット） |

## 未整理の課題

移行時点の各リポジトリの中身をそのまま取り込んだため、同じスキルの改変版が `skills/repos/` に残っている。統合する場合は差分を見て `skills/shared/` を更新し、`own` から外す。

- research 系（clustering / gather / retrieval）: research 版（7 月改訂）が最新。realtime も独自版。
- experiment 系・dvc: reinforce・kaggriculture・ptcg（carrier と同一）の 3 系統に分岐。reinforce が最新。
- `skills/repos/realtime/research-gather` は SKILL.md が無く evals だけ。移行前から壊れている。
- carrier は ptcg の丸コピーで git 管理外。`skills/repos/carrier` の dvc・experiment-analysis は ptcg（`01_kaggle/ptcg`）を指したままで、`03_carrier` 自身には `.dvc` も `backend/` も無い。
