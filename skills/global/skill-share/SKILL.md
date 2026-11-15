---
name: skill-share
description: Decide and carry out how a skill in the skills hub (~/project/98_skills) is classified — shared across repos (skills/shared/), repo-specific (skills/repos/<repo>/), or no longer distributed — and make skills portable enough to be distributed: merging diverged per-repo variants into one shared version, splitting a shared skill off for one repo, and removing absolute paths and other machine- or repo-specific values. Use when the user says "このスキルを共通化して", "shared にまとめて", "改変版を統合して", "このリポジトリだけ別の版にしたい", "共通化を解除", "shared から外して", "このスキルを配布しないで", "スキルの絶対パスを直して", "どこでも動くようにして", when uv run src/hub.py check-paths reports `abs` errors, or when working through the hub README's 未整理の課題. For plain distribute/import that keeps the classification, use skill-sync instead.
---

# skill-share: 共通化・非共通化と移植性

ハブから配布されるスキルは、クローン先・worktree・クラウドセッション・フォルダ再編後でもそのまま動かなければならない。
このスキルは「どう書けばどこでも動くか」と「どのリポジトリに同じ版を配るか」を判断する。
配布そのものは skill-sync に渡す。

- 移植性のルールは `references/portability.md`（`skills/shared/` と `skills/repos/` の両方に適用。`own` もコピーで配布されるため）。
- 改変版の統合の判断基準は `references/merge-variants.md`。

状態（`same` / `hub` / `repo` / `both` / `unknown`）は `uv run src/hub.py sync --check --repo <repo>` で見る。表示されないスキルは `same`。

## 共通化（own の改変版 → shared の 1 つ）

1. **前提を揃える。** 対象スキルを持つ全リポジトリで、そのスキルが `same`（表示されない）か `hub` であること。`repo` / `both` / `unknown` があれば先に skill-sync で解消する（解消しないとリポジトリ側の変更が失われる）。
2. **改変版を集める。**
   ```bash
   cd ~/project/98_skills
   { find skills/shared -mindepth 1 -maxdepth 1 -type d -name '<name>'; find skills/repos -mindepth 2 -maxdepth 2 -type d -name '<name>'; }   # グロブは使わない（zsh では一致が無いとコマンドごと止まる）
   jq -r --arg n <name> '.repos | to_entries[] | select((.value.shared + .value.own) | index($n)) | "\(.key)\t\(if (.value.shared | index($n)) then "shared" else "own" end)"' skills/repos.json
   ```
   リポジトリにだけある未管理の版（skill-sync から `unmanaged` で渡されたもの）は `<repo>/.claude/skills/<name>` を直接比較の対象に加える。扱いは手順 3 で決める（下の「未管理の版の扱い」）。
   版どうしを `diff -r` で比べる。同一の版はまとめて扱う。
3. **差分を分類する**（`references/merge-variants.md`）。(a) 環境依存の値、(b) 振る舞いの本当の違い、(c) 単に古いだけ。分類結果を表にしてユーザーに見せ、(b) をどう扱うか（統合版に条件として入れる / そのリポジトリは own に残す）を決めてもらう。

   **未管理の版の扱い**（`repos.json` に載っていないので、manifest にも記録が無い）:

   | 決めたこと | 手順 |
   |---|---|
   | 統合版に反映し、そのリポジトリも shared にする | 手順 5 で shared に加える（own から外す操作は不要）。状態は `hub` ではなく `unknown` になる（手順 7） |
   | そのリポジトリだけ own に残す | `uv run src/hub.py import <repo> <name>`（own として取り込まれる）。以後は own の版として `portability.md` を適用する |
   | 採用しない | `<repo>/.claude/skills/<name>` を消すかユーザーに確認する（リポジトリ側のファイル削除）。残すと `unmanaged` のまま `--check` に出続ける |
4. **統合版を書く。** ハブの `skills/shared/<name>` に直接書く（新規なら作る）。(a) は `references/portability.md` の書き方で置き換え、(c) は新しい方に揃える。
   1 つの版をそのまま共通化するだけなら `uv run src/hub.py import <repo> <name> --to shared` でもよい。ただしそのスキルが `same` のときだけ（`hub` だと sync.py が拒否するので、先に skill-sync で配布する）。統合には使わない。既に別の内容の `skills/shared/<name>` があると sync.py は拒否する（`--force` で上書きできるが、それは統合を飛ばすことになる）。
5. **分類を移す。** 共通化するリポジトリごとに:
   ```bash
   jq -e --arg r <repo> --arg n <name> '.repos[$r] as $e | if $e == null then error("unknown repo") else . end | .repos[$r].own -= [$n] | .repos[$r].shared = ((.repos[$r].shared + [$n]) | unique)' skills/repos.json > skills/repos.json.tmp \
     && mv skills/repos.json.tmp skills/repos.json \
     && { [ ! -d skills/repos/<repo>/<name> ] || rm -r skills/repos/<repo>/<name>; } \
     || { rm -f skills/repos.json.tmp; echo "分類を移せなかった" >&2; }
   ```
6. **検査する。** 分類を移した後に `uv run src/hub.py check-paths` を実行し、exit 0 であること（`skills/repos/<repo>/<name>` の消し忘れや `repos.json` の不整合もここで出る）。統合で既知の違反が解消・減少したら `src/path_check.py` 先頭の `ALLOW` の項目を消すか件数を更新する（合わないと `allow` エラーになる）。
7. **影響を示して配布を渡す。** `uv run src/hub.py sync --check` で、上書きされるリポジトリとファイル数を見せる。own から移したリポジトリは `hub` になる。未管理の版から shared に加えたリポジトリは `unknown` になり、通常の配布ではスキップされる。統合版で上書きしてよいことは手順 3 でユーザーが決めているので、skill-sync には「`unknown` はハブ版を残す（`--repo <repo> --force`）」と伝えて渡す。このとき `import` は使わない（統合版がそのリポジトリの旧版で上書きされ、全リポジトリに配られる）。

## 非共通化（shared → 1 リポジトリだけ own）

1. **理由を確認する。** そのリポジトリだけ振る舞いを変える必要があるときだけ行う。単に環境依存の値が違うだけなら、共通化したまま `portability.md` の方法で値を外に出すほうがよい。
2. **どの版を own にするか決める。** 状態で決まる。

   | 状態 | `import --to own` で own になる版 | 別の版にしたいとき |
   |---|---|---|
   | `same` | 今の shared 版（= リポジトリ版） | — |
   | `hub` | リポジトリにある旧版（ハブの変更を受け取らない） | ハブの新しい版にしたいなら、先に skill-sync で配布してから `import --to own` |
   | `repo` | リポジトリで変更した版 | ハブ版にしたいなら、先に skill-sync でハブ版を残す処理をしてから |
   | `both` / `unknown` | `--force` を付けるとリポジトリ版 | diff を見せてユーザーに選んでもらう |

3. ```bash
   uv run src/hub.py import <repo> <name> --to own     # both / unknown でリポジトリ版を選んだら --force も
   ```
   `skills/repos/<repo>/<name>` ができ、`repos.json` で `shared` から `own` に移る。他のリポジトリは shared 版のまま。
4. `uv run src/hub.py check-paths` を実行する。誰も使わなくなった `skills/shared/<name>` はエラーになるので、消すかユーザーに確認する。
5. 以後、そのリポジトリの版は `skills/repos/<repo>/<name>` で編集する。移植性のルールは own にも適用される。

## 配布をやめる

1. 対象のリポジトリで、そのスキルが `same` か `hub` であること（`repo` / `both` / `unknown` ならリポジトリ側の変更を取り込むか捨てるかユーザーに確認する）。
2. `repos.json` の `shared` / `own` から外す。own なら `skills/repos/<repo>/<name>` を消す。誰も使わなくなった `skills/shared/<name>` は消すかユーザーに確認する。
3. `src/sync.py` は配布先のコピーを消さないので、`<repo>/.claude/skills/<name>` を消してよいかユーザーに確認してから消す（リポジトリ側のファイル削除になる）。次の配布で `.hub-manifest` からも外れる。消すことを勧める。コピーを残すと:
   - 以後 `unmanaged` と表示され、`uv run src/hub.py sync --check` が常に exit 1 になる（drift が 0 にならない）。
   - 名前を省いた `uv run src/hub.py import <repo>` で own として取り込まれてしまう。
   残すならこの 2 点をユーザーに伝え、そのリポジトリでは一括取り込みを使わない。
4. `uv run src/hub.py check-paths` を実行する。
5. リポジトリそのものを管理から外す（`skills/repos.json` から消す）ときは、先に `uv run src/hub.py uninstall-hook <名前>` で pre-commit を取り除く（消した後なら `--path <場所>`）。

## 移植性の修正だけを行うとき

`uv run src/hub.py check-paths` の `abs` エラーや、ユーザーが「どこでも動くように」と頼んだとき。分類は変えずに、`references/portability.md` に沿ってハブの該当スキルを書き換える。版が複数あれば全部に同じ修正をする（統合のよい機会なので共通化を提案する）。書き換えたら `uv run src/hub.py check-paths` を通し、`src/path_check.py` 先頭の `ALLOW` の該当項目を消すか件数を更新して、配布は skill-sync に渡す。

すぐに直せない違反を当面配布し続ける必要があるときだけ、ユーザーの同意を得て `src/path_check.py` 先頭の `ALLOW` に、ファイルのパターン・今の違反の件数・理由を書く（`skills/repos/*/dvc/SKILL.md  12  # skill-share で $MAIN 化するまで` のように）。件数はパターンに当てはまる違反の合計なので、件数が変われば検査で止まる。ただし 1 件直して別の 1 件を足すような入れ替えや、同じ行に同じパスを重ねて書いたもの（1 件に数える）は検出できない。`ALLOW` に載せたファイルを編集したら、違反の中身を `uv run src/hub.py check-paths` の出力ではなく diff で確かめる。`ALLOW` 以外を書き換えて検査を通さない。

## 報告すること

- 版の一覧と分類（a/b/c）の表、ユーザーが決めた扱い。
- `repos.json` の変更（どのリポジトリが shared / own になったか、どこで配布をやめたか）。
- 次の配布で上書きされるリポジトリ。
- コミットはユーザーに言われたときだけ。
