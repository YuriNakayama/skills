# 配布できるスキルの書き方

`shared/` と `repos/` のスキルはリポジトリにコピーされ、そのリポジトリのクローン先・worktree・クラウドセッションで実行される。
ハブのあるマシンの配置（`~/project/...`）も、リポジトリ名も前提にできない。

`global/` は例外。`~/.claude/skills` からシンボリックリンクで参照され、このマシンでしか使わないので絶対パスを書いてよい。

## パス

### リポジトリのルート

```bash
ROOT=$(git rev-parse --show-toplevel) || { echo "git リポジトリの中で実行する" >&2; exit 1; }   # 今いる作業ツリー（worktree）
common=$(git rev-parse --path-format=absolute --git-common-dir) || exit 1
[ "$(basename "$common")" = .git ] || { echo "メインリポジトリを特定できない: $common" >&2; exit 1; }
MAIN=$(dirname "$common")                                                                        # メインリポジトリ（worktree から実行しても同じ）
[ "$(git -C "$MAIN" rev-parse --is-inside-work-tree 2>/dev/null)" = true ] || { echo "メインリポジトリに作業ツリーが無い: $MAIN" >&2; exit 1; }
```

- `MAIN` の式が成り立つのは、通常のリポジトリとその linked worktree（サブディレクトリから実行しても同じ）。
- 成り立たないもの: サブモジュールの中（`.git/modules/...` を返す）、bare リポジトリ + worktree（bare の親を返す）、git 管理外のディレクトリ（git がエラー）。これらは上の確認で止まる。bare リポジトリを `.git` という名前で置く配置（`git clone --bare <url> repo/.git` + `repo/<worktree>`）は `basename` の確認を通るが、最後の作業ツリーの確認で止まる。確認していない配置もあり得るので、止まったときはユーザーに配置を聞く。
- `--path-format` は git 2.31 以降。
- worktree を使わないスキルなら `ROOT` だけでよい。

### 同梱ファイル

`.claude/skills/<name>/` がリポジトリでコミットされていれば、どの worktree にもある。`.gitignore` で除外されている（`*-workspace/` など）とメインリポジトリにしか無い。どちらでも動くように探し、見つからなければ止める:

```bash
SKILL_DIR=
for d in "$ROOT" "$MAIN"; do [ -d "$d/.claude/skills/<name>" ] && SKILL_DIR=$d/.claude/skills/<name> && break; done
[ -n "$SKILL_DIR" ] || { echo "スキルのファイルが見つからない: .claude/skills/<name>" >&2; exit 1; }
```

Python スクリプトの中では `Path(__file__).resolve().parent` を基準にする。

### 何をどう指すか

| 指したいもの | 書き方 |
|---|---|
| 作業ツリーのファイル | `$ROOT/...`（またはルートで実行する前提の相対パス） |
| worktree 間で共有するもの（DVC キャッシュ、大きなデータ） | `$MAIN/...`。共有の設定自体はリポジトリ側（例: `.dvc/config.local` の `cache.dir`）にあり、スキルはそれを読む |
| スキル自身に同梱したファイル | 上の「同梱ファイル」の `$SKILL_DIR` |
| worktree の置き場 | 書かない。必要なら `git worktree list` で調べる |
| ホーム以下のツール設定（`~/.aws`、`~/.claude/agents` など） | `~/...` で書いてよい（どのマシンにもある前提のもの） |

単純な相対パス（`.dvc/cache`）は、worktree から実行すると worktree 自身を指すので、共有物には使えない。`$MAIN` を使う。
スクリプトに絶対パスを渡す必要があるときは、スキルの手順の中で `$MAIN` や `$ROOT` から組み立てる:

```bash
python3 "$SKILL_DIR/scripts/pick.py" --replays-dir "$MAIN/data/lake/replays"
```

### 書いてはいけないもの

`dev/path-check` が `shared/` と `repos/` でエラーにするもの:
- プロジェクト置き場のパス: `~/project/...`、`$HOME/project/...`、`${HOME}/project/...`、`/Users/<name>/project/...`
- `/Users/<name>/...`、`/home/<name>/...` で始まるパス
- 上の後ろに例示が続くもの（`~/project/<repo>/...`）も、手前が具体的なのでエラー

`dev/path-check` が検出しないが、書いてはいけないもの:
- `../<別のリポジトリ>` のような、リポジトリの外を指す相対パス
- 特定のリポジトリ名を前提にした説明（下の「リポジトリごとに違う値」）

## リポジトリごとに違う値

AWS プロファイル、S3 バケット、プロジェクト名、ディレクトリ構成など。

1. **リポジトリ側の設定から読む。** `.dvc/config`、`pyproject.toml`、`package.json`、`CLAUDE.md` など、そのリポジトリにすでにある場所。
   例: DVC のリモートは `dvc remote list`、プロファイルは `dvc config --show-origin remote.<name>.profile`。
2. **無ければ実行時に調べる / ユーザーに聞く。** 「`backend/.venv/bin/dvc` があればそれを使う」のように、存在確認で分岐する。
3. **スキルに値を書かない。** 書いた時点で、そのスキルは 1 リポジトリ専用（own）になる。

説明文（description や見出し）にも特定のリポジトリ名を書かない（「PTCG repo」ではなく「this repo」）。

## 例外

- `*-workspace/` スキル（eval の記録: `iteration-*/` の出力や `benchmark.json`）は過去の実行結果なので書き換えなくてよく、`dev/path-check` も対象外にしている。ただし workspace に置いた実行用スクリプト（`grade.py` など）も検査されないので、書くときはこのルールに従う。
- 例示用の書き方（`<branch>`、`...`、`{repo}`、`$VAR`、`*`）は、配布物以外（`global/` など）では存在チェックの対象外（例示の手前のディレクトリまでは確かめる）。

## 検査

```bash
~/project/98_skills/dev/path-check
```

`abs` の行がこのルール違反。修正待ちの既知の違反は `dev/path-check` 先頭の `ALLOW` に件数と理由を添えて載せると除外される（ユーザーの同意を得てから）。件数が合わなくなると `allow` エラーになる。
