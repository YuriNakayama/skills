---
name: skill-register
description: Bring a repository under the skills hub (~/project/98_skills) so it receives hub skills and its .claude/skills changes are caught at commit time — pick which shared skills fit the repo, run `uv run src/hub.py register`, triage the skills it already has, wire the pre-commit check into an existing hook framework (husky, pre-commit), distribute, and commit on the repo side. Use when the user says "このリポジトリをハブの管理下に入れて", "ハブに登録して", "このリポジトリにもスキルを配りたい", "register this repo", or when a repo is missing from skills/repos.json but should get hub skills. For distributing to or importing from an already registered repo, use skill-transfer; for merging or sharing variants found during triage, use skill-share.
---

# skill-register: リポジトリを管理下に入れる

`uv run src/hub.py register` が機械的な部分（`skills/repos.json` への登録、shared と同一の既存スキルの自動追加、
`.git/hooks/pre-commit` と `post-checkout` の設置）を行う。このスキルは、その前後の判断を受け持つ。

| このスキルがやること | 渡す先 |
|---|---|
| 配る shared スキルを選ぶ | — |
| `register` を実行する | — |
| 既存スキルの振り分けをまとめる | 取り込みは skill-transfer、統合・共通化・移植性の修正は skill-share |
| 既存のフックの仕組みに pre-commit と post-checkout を組み込む | — |
| 配布とリポジトリ側のコミット | 配布は skill-transfer の手順 3 と同じ |

登録してよいリポジトリか（開発が続いているか、別のリポジトリのコピーでないか）はユーザーが決めている前提で進める。

## 手順

### 1. リポジトリを調べる

```bash
cd <repo>
git rev-parse --show-toplevel; git branch --show-current; git status --short | head
ls -a .claude/skills 2>/dev/null
ls pyproject.toml package.json dvc.yaml Cargo.toml go.mod 2>/dev/null
ls -a .husky .pre-commit-config.yaml 2>/dev/null; git config --get core.hooksPath
```

- 名前は `skills/repos.json` の既存の名前と重ならない短い名前にする（ディレクトリ名から番号の接頭辞を外したものなど）。ユーザーに確認する。
- git 管理外ならフックは設置されない。そのことをユーザーに伝えて進める。

### 2. 配る shared スキルを選ぶ

`skills/shared/*/SKILL.md` の description と、リポジトリの言語・構成を照らし合わせて候補を作る。

```bash
cd ~/project/98_skills
for d in skills/shared/*/; do n=$(basename "$d"); printf '%s\t%s\n' "$n" "$(sed -n 's/^description: *//p' "$d/SKILL.md" | head -1 | cut -c1-120)"; done
jq -r '.repos | to_entries[] | "\(.key)\t\(.value.shared | join(","))"' skills/repos.json   # 似たリポジトリの選び方を参考にする
```

- 言語や道具が合わないもの（Python だけのリポジトリに `typescript-lint`、`vercel-react-best-practices` など）は外す。
- 迷うものは外して候補として示す（あとから `skills/repos.json` に足せる）。
- 候補を「配る / 外す / 迷う」の表にしてユーザーに見せ、決めてもらう。リポジトリに既にある同名のスキルは手順 3 で扱うので、ここで決めなくてよい。

### 3. 登録する

```bash
cd ~/project/98_skills
uv run src/hub.py register <名前> <path> --shared <カンマ区切り>
```

出力の 3 つの節を読む:
- **登録**: 自動で shared に入ったスキル（リポジトリに既にあり、ハブと同一のもの）。
- **フック（pre-commit、post-checkout）**: 2 つとも「作った」「追記した」「書き換えた」なら完了。追記したときに「exec か exit があり〜」と出たら、既存のフックを読み、追記した部分が実行されるか確かめる。「設置しない。〜次を追記する」と出たら手順 5。
- **既存スキルの振り分け**: 手順 4。

失敗（exit 2）なら原因（二重登録、`skills/shared` に無い名前など）を直して再実行する。

### 4. 既存スキルを振り分ける

`register` が表示した一覧を、1 つずつ処理する。

| 表示 | 処理 |
|---|---|
| `skills/shared/<n> と中身が違う` | skill-share に渡す（統合して shared にするか、別の名前に分ける。同じ名前のまま own にはできない） |
| `skills/... と同名`（global やほかのリポジトリの own） | skill-share に渡す（統合・共通化するか、別の名前に分ける） |
| `ハブに無い` | own にするかユーザーに確認し、`uv run src/hub.py import <名前> <n>`。取り込む前後に `uv run src/hub.py check-paths` で絶対パスが無いか確かめ、あれば skill-share の portability.md に沿って直す |

採用しないスキルは、リポジトリから消すか残すかユーザーに確認する（残すと `unmanaged` のまま `diff` と pre-commit に出続ける）。

### 5. 既存のフックの仕組みに組み込む（設置しないと表示されたとき）

`register` が表示した `# >>> skills-hub >>>` から `# <<< skills-hub <<<` までを、そのリポジトリの仕組みに足す。

| 仕組み | 足す場所 |
|---|---|
| husky（`core.hooksPath` が `.husky` を指す） | `.husky/pre-commit` と `.husky/post-checkout` の末尾（それぞれに表示された方を足す） |
| pre-commit（`.pre-commit-config.yaml`） | `repos:` に `repo: local` のフックを足し、`entry` に表示された `if` 文を `bash -c` で実行させる。`files: ^\.claude/skills/`、`pass_filenames: false`、`always_run: false`。post-checkout は `stages: [post-checkout]`、`always_run: true` で同じように足し、`pre-commit install --hook-type post-checkout` も実行する（post-checkout の引数は `$PRE_COMMIT_CHECKOUT_TYPE` などで渡るので、表示された `"$3"` を合わせて直す） |
| その他 | 表示された行を、その仕組みの pre-commit・post-checkout から実行されるところに足す |

これらはリポジトリで管理されているファイルで、他の人のコミットにも影響する（ハブや uv が無い環境では何もしない作りだが、ハブのパスがファイルに入る）。
足す前に、差分を見せてユーザーに確認する。チームのリポジトリで入れたくないと言われたら、`.git/hooks/pre-commit`（自分の環境だけ）に置く方法を提案する（そのときは仕組みが `.git/hooks` を使っているかを確かめる）。

### 6. 配布してコミットする

```bash
cd ~/project/98_skills
uv run src/hub.py check-paths
uv run src/hub.py export --repo <名前>
uv run src/hub.py diff --repo <名前>        # drift: 0
uv run src/hub.py check-repo <名前> --path <path>   # exit 0
```

リポジトリ側では `.claude/skills`、`.hub-manifest`、手順 5 で変えたフックの設定をコミットする。
どのブランチにコミットするかはユーザーに確認する（既定のブランチなら新しいブランチを切る。関係の無い作業ブランチに混ぜない）。
ハブ側の変更（`skills/repos.json`、取り込んだスキル）も、コミットはユーザーに言われたときだけ。

## 報告すること

- 登録した名前・path・配る shared スキル（自動で入ったものを含む）。
- pre-commit をどこに設置したか（または設置しなかった理由）。
- 既存スキルの振り分けの結果（取り込んだもの、skill-share に渡したもの、残したもの）。
- `diff` と `check-repo` の結果、コミットしたブランチ（またはしていないこと）。
