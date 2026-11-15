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
| `src/` | ハブのツール（Python）。入口は `src/hub.py`（サブコマンドは `uv run src/hub.py --help`）。中身は `common.py`（共通）、`transfer.py`（配布・取り込み・check-repo・claude-hook）、`register.py`（register・install-hook・uninstall-hook）、`path_check.py`（パスの検査）、`duplicated_skill.py`（重複の検査） |
| `pyproject.toml`、`.python-version`、`uv.lock` | Python の環境（uv で管理） |

## 使い方

Python は uv で管理する（`.python-version` で 3.13 に固定。`src/` のツールは標準ライブラリだけを使う）。ハブで `uv run` を使って実行する（初回は `.venv` が作られる）。

```bash
cd ~/project/98_skills
uv run src/hub.py diff                            # 状態を表示（ずれがあれば exit 1）
uv run src/hub.py export                          # 配布する（各リポジトリの worktree すべて。リポジトリ側で変更されたスキルは上書きせずスキップ）
uv run src/hub.py export --repo research          # 1 リポジトリだけ（その worktree すべて）
uv run src/hub.py export --here                   # 今いる作業ツリーだけ
uv run src/hub.py import research                 # research 側の変更と未管理スキルをすべて取り込む（未管理は own になるので、unmanaged があるときは名前を指定する）
uv run src/hub.py import research pr              # 指定したスキルだけ取り込む（今の分類のまま。shared なら skills/shared/pr へ）
uv run src/hub.py import research pr --to shared  # 共通化（skills/shared/pr へ。使っている全リポジトリに配布される）
uv run src/hub.py import research pr --here       # 今いる作業ツリー（worktree・別のブランチ）から取り込む（--path D でも指定できる）
uv run src/hub.py import research pr --ref main   # ブランチ main にコミットされている中身から取り込む（checkout していなくてよい）
uv run src/hub.py register foo ../01_kaggle/foo   # リポジトリを管理下に入れる（登録とフックの設置。--shared a,b で配るスキルを指定）
uv run src/hub.py check-repo --here               # 今いるリポジトリに、ハブへ取り込まれていない変更が無いか（pre-commit から使う）
uv run src/hub.py check-paths                     # 切れたパスと、配布できない絶対パスの検査
uv run src/hub.py check-duplicates                # スキルの重複（層をまたいだ同名、内容が同一、改変版の分岐、空のスキル）の検査
```

配布先の各作業ツリーの `.claude/skills/.hub-manifest` に、前回配布した時点の各スキルのハッシュが記録される。ハブ、リポジトリ、このハッシュを比べて、どちらが変わったかを判定する。
`.hub-manifest` はブランチごとにコミットされる。マージでぶつからないように、`export` は `.claude/skills/.gitattributes`（`.hub-manifest merge=union`）も配る。
マージで 1 つのスキルに複数の記録が残ったときは、どれかと一致すれば「変わっていない」とみなし、次の `export` で 1 つに戻す。

| 状態 | 意味 | 配布 | 取り込み |
|---|---|---|---|
| `new` | リポジトリにまだ無い | 配布する | 対象外 |
| `hub` | ハブだけ変わった | 上書きする | 拒否（配布すればよい） |
| `repo` | リポジトリだけ変わった | スキップ | 取り込む |
| `both` | 両方変わった | スキップ | `--force` が必要 |
| `unknown` | 差分があり、記録がない | スキップ | `--force` が必要 |
| `unmanaged` | リポジトリにだけあり、ハブで未管理 | 対象外（`diff` は exit 1 のまま） | own として取り込む。同名の `skills/shared/` に `--to shared` で入れるのは拒否（`--force` で上書き） |

`--force` を付けた配布は、リポジトリ側の変更を上書きする。

## リポジトリを管理下に入れる

手順は skill-register スキルにまとめてある（配る shared スキルの選定、既存のフックの仕組みへの組み込みなど、判断が要る部分を含む）。

1. `uv run src/hub.py register <名前> <path> [--shared a,b]` を実行する。
   - `skills/repos.json` に登録する（リポジトリに既にあり、`skills/shared` と同一のスキルは自動で shared に入る）。
   - フックを 2 つ設置する（worktree を含め、そのリポジトリのすべての作業ツリーで効く。ハブや uv が無い環境では何もしない）。
     - pre-commit: `.claude/skills` の変更をコミットしようとしたとき、ハブに取り込まれていない変更や未管理のスキルを知らせる。
       止めるのは既定のブランチ（main など）でだけ。ほかのブランチと、マージのコミットでは知らせるだけで、開発中のスキルをコミットし、そのまま既定のブランチにマージできる（`git commit --no-verify` でも飛ばせる）。
     - post-checkout: ブランチを切り替えたとき、worktree を作ったときに、その作業ツリーのスキルがハブと違えば知らせ、配るコマンド（`export --path <作業ツリー>`）を示す。
       自動では書かない（書くと未コミットの変更が残り、次の checkout が止まるため）。
     既存のフックのファイルには追記する。husky（`core.hooksPath`）や `.pre-commit-config.yaml` があるときは
     触らず、追記する行を表示するので、そのフックの仕組みに自分で足す。
2. 表示された既存スキルの振り分けを、skill-transfer（取り込み）と skill-share（統合・共通化）で済ませる。
3. `uv run src/hub.py export --repo <名前>` で配布し、リポジトリ側で `.claude/skills` と `.hub-manifest` をコミットする。

既に登録済みのリポジトリにフックを入れる（入れ直す）ときは `uv run src/hub.py install-hook <名前>`（全部なら `--all`）。
管理から外したリポジトリでは `uv run src/hub.py uninstall-hook --path <場所>` で取り除く（登録中なら名前でも指定できる）。
pre-commit が止めるのは、既定のブランチで取り込まれていない変更が見つかったときだけ。ハブのツールや uv が無い、確かめられなかったときは警告してコミットを続ける。

Claude Code のユーザー設定（`~/.claude/settings.json`）の `PostToolUse` フックからも `uv run src/hub.py claude-hook` を呼んでいる（`src/hub.py` と uv が無ければ何もしない）。
Claude が管理下のリポジトリの `.claude/skills` を書くと、ハブへ取り込まれていない変更や未管理のスキルをその場で Claude に伝える
（コミットを待たずに気づくため。止めはしない）。

## worktree やブランチでスキルを開発する

スキルはどの worktree・ブランチで作ってもよい。取り込み方は 2 通り。

| 流れ | 手順 |
|---|---|
| マージしてから取り込む | 1. worktree の `.claude/skills/<name>/` で開発し、そのブランチでコミットする（既定のブランチではないので pre-commit は知らせるだけ）<br>2. 既定のブランチにマージする<br>3. `uv run src/hub.py import <repo> <name> --ref main`（どこで何を checkout していても、main にコミットされた中身を取り込む）<br>4. `uv run src/hub.py export --repo <repo>` で全部の worktree に配り、main で `.hub-manifest` などをコミットする |
| マージの前に直接取り込む | 1. worktree で開発する<br>2. その worktree で `uv run --project ~/project/98_skills ~/project/98_skills/src/hub.py import <repo> <name> --here`（checkout していないブランチからなら `--ref <branch>`）<br>3. `export --repo <repo>` で配り、そのブランチでコミットする。直し続けるなら 2〜3 を繰り返す |

ハブを更新したら `export`（`--repo <repo>`）で、そのリポジトリの今ある worktree すべてに届く。
ほかのブランチに切り替えたとき、新しく worktree を作ったときは、post-checkout がハブとの差を知らせるので、その作業ツリーで `export --here` を実行する（届いたスキルは未コミットの変更として現れるので、そのブランチでコミットする）。
取り込んだスキルは、元のブランチをマージしなくてもハブに残り、どのブランチにも配られる。
2 つのブランチに違う版が配られてマージでスキルのファイルがぶつかったら、どちらかを採ってから `export` を実行すれば、ハブの版にそろう。

## 運用ルール

- スキルはハブで作っても、リポジトリ（どの worktree・ブランチでも）で作ってもよい。全プロジェクト用は `skills/global/` に置く。
- リポジトリ側で編集・作成したスキルは `uv run src/hub.py import <repo>`（`unmanaged` があるときはスキル名を指定する。worktree やブランチからは `--here`・`--path`・`--ref`）でハブに取り込み、`git diff` で確認してからコミットする。取り込みは今の分類を保つ（shared のスキルを取り込むと、使っている全リポジトリに配布される）。
- **1 つの名前には 1 つの中身。** 層をまたいだ同名も、同名の別内容も作らない（`check-duplicates`）。環境ごとの値の違いは外に出して統合し、振る舞いの違いは別の名前に分ける（例: `experiment*` と `rl-experiment*`）。同じ名前のまま 1 つのリポジトリだけ別の版にする取り込みは `transfer.py` が拒否する。改変版の統合は `skills/shared/` に直接書いて `repos.json` を移す（手順は skill-share）。
- **配布するスキルに絶対パスを書かない。** `skills/shared/` と `skills/repos/` のスキルには `~/project/...` などの絶対パスを書かない（コピー先のクローン・worktree・クラウドで壊れるため）。`skills/global/` は例外。書き方は `skills/global/skill-share/references/portability.md`。
- **例外は設けない。** 許可リストは無い。`uv run src/hub.py export` は配布の前に `check-paths` と `check-duplicates` を実行し、規則の違反（配布するスキルの絶対パス、重複）か `repos.json` とハブの食い違いがあれば何も配布しない（`--repo X` では、絶対パスは X に配布するスキルの分だけを見る）。登録したリポジトリが無い、切れたリンクなどは警告だけで配布は続ける。直せない違反のあるスキルは、直すまで配布しない。
- `<スキル名>-workspace/`（skill-creator の評価の記録）はスキルではない。ハブに置いてよいが、配布・取り込み・検査の対象にしない（`repos.json` に載せない。リポジトリ側にできたものも未管理のスキルとして扱わない）。
- 配布後は各リポジトリで `.claude/skills` の変更をコミットする。
- `~/.claude/skills/synced` と `learned` は Claude アプリが管理するので触らない。

手順は 2 つのグローバルスキルにまとめてある。

| スキル | 役割 |
|---|---|
| `skill-transfer` | 取り込みと配布（分類は変えない） |
| `skill-share` | 共通化・別名への分割・配布の停止、改変版の統合、移植性（絶対パスなど）の修正 |
| `skill-register` | リポジトリを管理下に入れる（shared の選定、登録、pre-commit、振り分けのまとめ、コミット） |
