---
name: skill-transfer
description: Move skills between the skills hub (~/project/98_skills) and each repo's .claude/skills (any worktree or branch) — export (distribute) hub changes to repos with `uv run src/hub.py export`, check differences with `diff`, and import skills that were edited or created inside a repo back into the hub, keeping each skill's shared/own classification. Use when the user says "スキルを配布して", "スキルをリポジトリに配って", "スキルを取り込んで", "リポジトリで直したスキルをハブに戻して", "ハブと同期", "sync skills", after editing a skill in the hub, or after a skill under some repo's .claude/skills was edited or created directly. Does NOT change whether a skill is shared across repos or repo-specific, does not merge variants, and does not rewrite skill contents for portability — hand those to the skill-share skill.
---

# skill-transfer: ハブとリポジトリの間の配布（export）と取り込み（import）

ハブ `~/project/98_skills` がスキルの正本で、各リポジトリの `.claude/skills` はそのコピー。
このスキルは「どちらが新しいか」を判定して運ぶだけで、スキルの中身や分類については判断しない。

| やること | やらないこと（skill-share に渡す） |
|---|---|
| ハブの変更をリポジトリへ配布 | shared ⇄ own の分類変更（共通化・別名への分割）、配布の停止 |
| リポジトリでの変更・新規スキルを、今の分類のままハブへ取り込み | 改変版どうしの統合 |
| 衝突（both / unknown）を見せてユーザーに選ばせる | 絶対パスなど移植性の問題の修正、重複（`check-duplicates`）の解消 |

## 構成（前提知識）

| ハブ | 配布先 | 方式 | 対象 |
|---|---|---|---|
| `skills/global/<name>` | `~/.claude/skills/<name>` | シンボリックリンク | 全部 |
| `skills/shared/<name>` | `<repo>/.claude/skills/<name>` | コピー | `repos.json` の `shared` に書いたもの |
| `skills/repos/<repo>/<name>` | `<repo>/.claude/skills/<name>` | コピー | `repos.json` の `own` に書いたもの |

- 設定は `skills/repos.json`。`path` はファイルの場所（`skills/`）からではなく、ハブのルートからの相対パス（`~` は使えない）。
- 各リポジトリの `.claude/skills/.hub-manifest` に前回配布時の各スキルのハッシュがあり、ハブ・リポジトリ・ハッシュの 3 者比較で状態を決める。
- `src/transfer.py` は `repos.json` から外したスキルを配布先から消さない。
- `~/.claude/skills/synced` と `learned` は Claude アプリの管理なので触らない。

## 手順

### 1. 状態を見る

```bash
cd ~/project/98_skills
uv run src/hub.py diff          # 1 リポジトリだけなら --repo <repo>
uv run src/hub.py check-paths
```

`diff` は差のあるスキルだけを表示する（表示されないスキルは `same`）。

`uv run src/hub.py check-paths` と `uv run src/hub.py check-duplicates` のどちらかが exit 1 なら配布しない（`export` も配布の前に自分で 2 つを実行し、失敗したら配布しない）。終了コードは出力の最後の行ではなく、コマンドの終了コードそのもので確かめる。
- `repos` / `symlink` / `link` の行: 指摘どおり直す（`repos.json`、切れたリンクなど）。直し方が分類の変更になるなら skill-share に渡す。
- `abs` の行（配布するスキルに絶対パスがある）: skill-share の `references/portability.md` に沿って直す必要がある。ユーザーに伝えて skill-share に渡す。
- `check-duplicates` の行（同名の別内容、層をまたいだ同名など）: 統合するか別の名前に分ける必要がある。skill-share に渡す。
- 例外（許可リスト）は無い。違反が残っている間は配布しない。

exit 2 はチェック自体の失敗（jq が無い、一時ディレクトリを作れないなど）。原因を直して再実行する。

### 2. 状態ごとに処理する

| 状態 | 意味 | 処理 |
|---|---|---|
| `new` | リポジトリにまだ無い | 配布する |
| `hub` | ハブだけ変わった | 配布する |
| `repo` | リポジトリだけ変わった | 取り込む |
| `both` | 両方変わった | ハブ版とリポジトリ版の `diff -r` を見せ、どちらを残すかユーザーに選んでもらう。勝手にマージしない |
| `unknown` | 差分があり記録が無い | `both` と同じ |
| `unmanaged` | リポジトリにだけある | 下の「unmanaged」を見る |

**取り込み**は今の分類を保つ（`--to` を省く）。名前を省いた一括取り込み（`import <repo>`）は `unmanaged` も全部 own として取り込むので、`unmanaged` があるときは使わず、スキル名を指定する。

```bash
uv run src/hub.py import <repo> <name>     # shared のスキルは skills/shared/ へ、own のスキルは skills/repos/<repo>/ へ
```

取り込み元は、省くと登録した場所の作業ツリー。worktree やブランチで開発したスキルは、次のどれかで取り込む:

| 場所 | オプション |
|---|---|
| 今いる worktree・作業ツリー | `--here`（`uv run --project ~/project/98_skills ~/project/98_skills/src/hub.py import <repo> <name> --here`） |
| ほかの作業ツリー | `--path <作業ツリー>`（pre-commit やフックの知らせにはこの形で出る） |
| マージ済みのブランチ、checkout していないブランチ | `--ref <branch>`（コミットされた中身を読む。git が無視するファイルは入らない） |

取り込んだら `uv run src/hub.py export --repo <repo>` で、そのリポジトリの worktree すべてに配る。

shared のスキルを取り込むと、それを使う全リポジトリに次回配布される。取り込む前に影響するリポジトリを示す:

```bash
jq -r --arg n <name> '.repos | to_entries[] | select(.value.shared | index($n)) | .key' skills/repos.json
```

「このリポジトリだけの変更にしたい」と言われたら、それは非共通化なので skill-share に渡す。`--to` は付けない（分類を変えるのは skill-share）。

**both / unknown** でユーザーが選んだら:
- リポジトリ版を残す: `uv run src/hub.py import <repo> <name> --force`。
- ハブ版を残す: `--force` 付きの配布で上書きする。これは配布なので手順 3 で行う（取り込みを先に済ませ、`uv run src/hub.py check-paths` を通してから）。`--force` はそのリポジトリの `repo` / `both` / `unknown` のスキルを全部上書きするので、他に該当があれば先に取り込むか、ハブ版でよいかユーザーに確認しておく。

skill-share から「`unknown` はハブ版を残す」と渡された場合（未管理の版を共通化したリポジトリ）は、ユーザーの判断は済んでいるのでハブ版を残す。`import` はしない。

**unmanaged** は、上から順に確かめる。

```bash
cd ~/project/98_skills
{ find skills/shared -mindepth 1 -maxdepth 1 -type d -name '<name>'; find skills/repos -mindepth 2 -maxdepth 2 -type d -name '<name>'; }   # ハブの同名（グロブは zsh で止まるので使わない）
git log --oneline -- 'skills/shared/<name>/*' 'skills/repos/*/<name>/*' 'shared/<name>/*' 'repos/*/<name>/*' | head -3   # ハブでの履歴（後ろの 2 つは skills/ に移す前の配置。クォートして git に渡す）
```

1. **配布をやめたスキルの残骸**: ハブの同名のどれかと `diff -r` で同一、または同名は無いがハブに履歴がある。取り込まずに skill-share の「配布をやめる」（コピーを消すか残すか）に渡す。
2. **既存スキルの改変版**: ハブに同名があり、内容が違う。skill-share に渡す（`own` として取り込むと改変版が 1 つ増える）。
3. **新しいスキル**: ハブに同名も履歴も無い。取り込むかユーザーに確認し、取り込むなら `uv run src/hub.py import <repo> <name>`（そのリポジトリの own になる）。

取り込んだら `git -C ~/project/98_skills diff` を見せる。

### 3. 配布する

取り込みでハブが変わったかもしれないので、どの配布（`--force` 付きを含む）の直前にも `uv run src/hub.py check-paths` を実行し、exit 0 を確認する（取り込んだスキルに絶対パスが入っていれば、ここで止めて skill-share に渡す）。

```bash
uv run src/hub.py check-paths
uv run src/hub.py export                         # または --repo <repo>
uv run src/hub.py export --repo <repo> --force   # both / unknown でハブ版を残すと決めたリポジトリだけ
uv run src/hub.py diff                 # drift: 0 を確認
```

drift が残るのが、ユーザーが残すと決めた `unmanaged`（配布をやめたスキルのコピーなど）だけなら、それを報告して終える。

### 4. 報告する

- 配布・取り込みしたスキルと、各リポジトリの `git -C <repo> status --short -- .claude/skills`。
- `.hub-manifest` が未追跡なら、そのリポジトリでコミットするか決めてもらう。
- git 管理外のリポジトリ（`.git` が無いもの）は差分で確認・復元できないことを伝える。
- `.gitignore` で除外されている配布物は git に出ないことを伝える（`*-workspace/` は配布しない）。

コミットは、ハブも各リポジトリもユーザーに言われたときだけする。

## リポジトリを管理下に入れる・コミットが止められた

- 新しいリポジトリにスキルを配りたい（`skills/repos.json` に無い）と言われたら、skill-register に渡す。
- pre-commit が止めるのは既定のブランチ（main など）でだけ。ほかのブランチでは知らせるだけなので、そのまま開発を続け、マージの前に `--here` か、マージの後に `--ref main` で取り込む。
- 登録済みのリポジトリで `.claude/skills` のコミットが pre-commit に止められたと言われたら、または Claude Code のフックから
  「skills hub: このリポジトリの .claude/skills に、ハブへ取り込まれていない変更がある」と伝えられたら、手順 1 から処理する
  （`uv run src/hub.py check-repo <名前> --path <作業ツリー>` で同じ一覧が出る）。

## してはいけないこと

- リポジトリ側の `.claude/skills` を直接編集する（直すのはハブ。リポジトリで直してしまったら取り込む）。
- どちらを残すかユーザーが決める前に `--force` を使う。
- `import` に `--to` を付ける、`repos.json` の `shared` / `own` を書き換える（分類の変更は skill-share）。
- `src/` の検査を書き換えて検査を通す。
