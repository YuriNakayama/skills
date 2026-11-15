---
name: skill-share
description: Decide and carry out how a skill in the skills hub (~/project/98_skills) is classified — shared across repos (skills/shared/), repo-specific (skills/repos/<repo>/), or no longer distributed — and make skills portable enough to be distributed: merging diverged per-repo variants into one shared version, splitting a skill whose behavior must differ into a separately named skill, and removing absolute paths and other machine- or repo-specific values. Use when the user says "このスキルを共通化して", "shared にまとめて", "改変版を統合して", "このリポジトリだけ別の版にしたい", "共通化を解除", "shared から外して", "このスキルを配布しないで", "スキルの絶対パスを直して", "どこでも動くようにして", when uv run src/hub.py check-paths reports `abs` errors, or when uv run src/hub.py check-duplicates reports duplicated skills. For plain distribute/import that keeps the classification, use skill-transfer instead.
---

# skill-share: 共通化・別名への分割と移植性

ハブから配布されるスキルは、クローン先・worktree・クラウドセッション・フォルダ再編後でもそのまま動かなければならない。
このスキルは「どう書けばどこでも動くか」と「どのリポジトリに同じ版を配るか」を判断する。
配布そのものは skill-transfer に渡す。

- 移植性のルールは `references/portability.md`（`skills/shared/` と `skills/repos/` の両方に適用。`own` もコピーで配布されるため）。
- 改変版の統合の判断基準は `references/merge-variants.md`。

## 規則（例外なし）

| 規則 | 守らせる仕組み | 違反したときの直し方 |
|---|---|---|
| 配布するスキル（`skills/shared/`・`skills/repos/`）に絶対パスを書かない | `uv run src/hub.py check-paths` | `references/portability.md` のとおり、実行時に求める形にする |
| 1 つの名前には 1 つの中身。層をまたいだ同名も、同名の別内容も作らない | `uv run src/hub.py check-duplicates` | 環境ごとの値の違いは外に出して統合する。振る舞いの違いは別の名前に分ける（下の「別の名前に分ける」） |

許可リストで例外を残すことはしない。直せない・分けられないときは、そのスキルを配布しない（「配布をやめる」）。
`uv run src/hub.py export` は配布の前に 2 つの検査を実行し、どちらかが失敗したら配布しない。
`<スキル名>-workspace/`（skill-creator の評価の記録）はスキルではないので、配布も検査もしない（例外ではなく、規則の対象外）。

状態（`same` / `hub` / `repo` / `both` / `unknown`）は `uv run src/hub.py diff --repo <repo>` で見る。表示されないスキルは `same`。

## 共通化（own の改変版 → shared の 1 つ）

1. **前提を揃える。** 対象スキルを持つ全リポジトリで、そのスキルが `same`（表示されない）か `hub` であること。`repo` / `both` / `unknown` があれば先に skill-transfer で解消する（解消しないとリポジトリ側の変更が失われる）。
2. **改変版を集める。**
   ```bash
   cd ~/project/98_skills
   { find skills/shared -mindepth 1 -maxdepth 1 -type d -name '<name>'; find skills/repos -mindepth 2 -maxdepth 2 -type d -name '<name>'; }   # グロブは使わない（zsh では一致が無いとコマンドごと止まる）
   jq -r --arg n <name> '.repos | to_entries[] | select((.value.shared + .value.own) | index($n)) | "\(.key)\t\(if (.value.shared | index($n)) then "shared" else "own" end)"' skills/repos.json
   ```
   リポジトリにだけある未管理の版（skill-transfer から `unmanaged` で渡されたもの）は `<repo>/.claude/skills/<name>` を直接比較の対象に加える。扱いは手順 3 で決める（下の「未管理の版の扱い」）。
   版どうしを `diff -r` で比べる。同一の版はまとめて扱う。
3. **差分を分類する**（`references/merge-variants.md`）。(a) 環境依存の値、(b) 振る舞いの本当の違い、(c) 単に古いだけ。分類結果を表にしてユーザーに見せ、(b) をどう扱うか（統合版に条件として入れる / 別の名前に分ける）を決めてもらう。同じ名前のまま own に残すことはしない（規則に反する）。

   **未管理の版の扱い**（`repos.json` に載っていないので、manifest にも記録が無い）:

   | 決めたこと | 手順 |
   |---|---|
   | 統合版に反映し、そのリポジトリも shared にする | 手順 5 で shared に加える（own から外す操作は不要）。状態は `hub` ではなく `unknown` になる（手順 7） |
   | 振る舞いが違うので別にする | 「別の名前に分ける」の手順で、新しい名前の own（または shared）にする。同じ名前のまま取り込まない（transfer.py が拒否する） |
   | 採用しない | `<repo>/.claude/skills/<name>` を消すかユーザーに確認する（リポジトリ側のファイル削除）。残すと `unmanaged` のまま `diff` に出続ける |
4. **統合版を書く。** ハブの `skills/shared/<name>` に直接書く（新規なら作る）。(a) は `references/portability.md` の書き方で置き換え、(c) は新しい方に揃える。
   1 つの版をそのまま共通化するだけなら `uv run src/hub.py import <repo> <name> --to shared` でもよい。ただしそのスキルが `same` のときだけ（`hub` だと transfer.py が拒否するので、先に skill-transfer で配布する）。統合には使わない。既に別の内容の `skills/shared/<name>` があると transfer.py は拒否する（`--force` で上書きできるが、それは統合を飛ばすことになる）。
5. **分類を移す。** 共通化するリポジトリごとに:
   ```bash
   jq -e --arg r <repo> --arg n <name> '.repos[$r] as $e | if $e == null then error("unknown repo") else . end | .repos[$r].own -= [$n] | .repos[$r].shared = ((.repos[$r].shared + [$n]) | unique)' skills/repos.json > skills/repos.json.tmp \
     && mv skills/repos.json.tmp skills/repos.json \
     && { [ ! -d skills/repos/<repo>/<name> ] || rm -r skills/repos/<repo>/<name>; } \
     || { rm -f skills/repos.json.tmp; echo "分類を移せなかった" >&2; }
   ```
6. **検査する。** 分類を移した後に `uv run src/hub.py check-paths` と `uv run src/hub.py check-duplicates` を実行し、どちらも exit 0 であること（`skills/repos/<repo>/<name>` の消し忘れ、`repos.json` の不整合、残った改変版もここで出る）。終了コードは出力の最後の行ではなく、コマンドの終了コードそのもので確かめる。
7. **影響を示して配布を渡す。** `uv run src/hub.py diff` で、上書きされるリポジトリとファイル数を見せる。own から移したリポジトリは `hub` になる。未管理の版から shared に加えたリポジトリは `unknown` になり、通常の配布ではスキップされる。統合版で上書きしてよいことは手順 3 でユーザーが決めているので、skill-transfer には「`unknown` はハブ版を残す（`--repo <repo> --force`）」と伝えて渡す。このとき `import` は使わない（統合版がそのリポジトリの旧版で上書きされ、全リポジトリに配られる）。

## 別の名前に分ける（1 つの名前に、振る舞いの違う版が要るとき）

同じ名前のまま 1 つのリポジトリだけ別の版にする（旧来の「非共通化」）ことはしない。`check-duplicates` の規則に反し、`transfer.py` も拒否する。
例: git flow と GitHub flow で手順が違うなら、それぞれ別の名前にする。ゲーム AI と強化学習で実験の進め方が違うので `experiment*` と `rl-experiment*` に分けた、など。

1. **理由を確認する。** 振る舞いが本当に違うときだけ行う。環境ごとの値（コマンド名、パス、プロジェクト名）が違うだけなら、分けずに `portability.md` の方法で値を外に出して統合する。分岐の条件をリポジトリの中身（ファイルの有無など）で書けるなら、1 つの版に条件として入れるほうがよい。
2. **新しい名前を決める。** ハブのどこにも無い名前にする（`find skills -mindepth 2 -maxdepth 3 -type d -name '<new>'` が空）。ユーザーが呼ぶコマンド名が変わるので、名前はユーザーに確認する。
3. **新しいスキルを作る。** 1 つのリポジトリだけが使うなら `skills/repos/<repo>/<new>`、複数なら `skills/shared/<new>` に、分ける版を置く。中で自分の名前を参照している箇所（frontmatter の `name:`、`/<name>` のコマンド、`.claude/skills/<name>/...` のパス、evals の `skill_name`、関連スキルの名前）を新しい名前に揃える。スキル名ではない同じ綴り（ディレクトリ名や普通の名詞）は変えない。
4. **使い分けを書く。** 両方の description に、どちらを使うかを書く（もう一方が残る場合）。
5. **分類を移す。** そのリポジトリの `skills/repos.json` で、元の名前を新しい名前に置き換える。元の版を使うリポジトリが無くなったら、元の版を消すか、残った版を元の名前に戻す（版が 1 つなら名前で区別する必要は無い）。
6. **検査する。** `check-paths` と `check-duplicates` がどちらも exit 0 であること。
7. **配布を渡す。** 配布すると、リポジトリ側に元の名前のコピーが `unmanaged` として残る。ハブで配っていた版と同一であること（リポジトリ側で書き換えられていないこと）を確かめてから消すよう、skill-transfer に伝える。

## 配布をやめる

1. 対象のリポジトリで、そのスキルが `same` か `hub` であること（`repo` / `both` / `unknown` ならリポジトリ側の変更を取り込むか捨てるかユーザーに確認する）。
2. `repos.json` の `shared` / `own` から外す。own なら `skills/repos/<repo>/<name>` を消す。誰も使わなくなった `skills/shared/<name>` は消すかユーザーに確認する。
3. `src/transfer.py` は配布先のコピーを消さないので、`<repo>/.claude/skills/<name>` を消してよいかユーザーに確認してから消す（リポジトリ側のファイル削除になる）。次の配布で `.hub-manifest` からも外れる。消すことを勧める。コピーを残すと:
   - 以後 `unmanaged` と表示され、`uv run src/hub.py diff` が常に exit 1 になる（drift が 0 にならない）。
   - 名前を省いた `uv run src/hub.py import <repo>` で own として取り込まれてしまう。
   残すならこの 2 点をユーザーに伝え、そのリポジトリでは一括取り込みを使わない。
4. `uv run src/hub.py check-paths` を実行する。
5. リポジトリそのものを管理から外す（`skills/repos.json` から消す）ときは、先に `uv run src/hub.py uninstall-hook <名前>` で pre-commit を取り除く（消した後なら `--path <場所>`）。

## 移植性の修正だけを行うとき

`uv run src/hub.py check-paths` の `abs` エラーや、ユーザーが「どこでも動くように」と頼んだとき。分類は変えずに、`references/portability.md` に沿ってハブの該当スキルを書き換える。版が複数あれば全部に同じ修正をする（統合のよい機会なので共通化を提案する）。書き換えたら `uv run src/hub.py check-paths` を通し、配布は skill-transfer に渡す。

例外は設けない。すぐに直せない違反は、許可して配布し続けるのではなく、直すまでそのスキルを配布しない（「配布をやめる」）。検査を通すために `src/` の検査を書き換えない。

## 報告すること

- 版の一覧と分類（a/b/c）の表、ユーザーが決めた扱い。
- `repos.json` の変更（どのリポジトリが shared / own になったか、どこで配布をやめたか）。
- 次の配布で上書きされるリポジトリ。
- コミットはユーザーに言われたときだけ。
