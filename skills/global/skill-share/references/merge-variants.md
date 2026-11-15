# 改変版の統合

同じ名前のスキルが `skills/shared/` と `skills/repos/<repo>/` に複数あるとき、差分を 3 種類に分けて扱う。

## 1. 版を整理する

```bash
cd ~/project/98_skills
{ find skills/shared -mindepth 1 -maxdepth 1 -type d -name '<name>'; find skills/repos -mindepth 2 -maxdepth 2 -type d -name '<name>'; } | while read -r d; do
  echo "$(cd "$d" && find . -type f ! -name .DS_Store ! -path '*/__pycache__/*' -exec shasum {} + | sort -k2 | shasum | cut -c1-8)  $d"
done
# リポジトリにだけある未管理の版も比べるときは <repo>/.claude/skills/<name> を同じ式で足す
```

ハッシュが同じ版は 1 つにまとめて扱う（例: ptcg と carrier が同一）。各版の最終更新は `git log -1 --format=%ci -- <dir>` で見る。

## 2. 差分を分類する

代表となる版どうしを `diff -ru` で比べ、差分の塊ごとに分類する。

| 分類 | 見分け方 | 扱い |
|---|---|---|
| (a) 環境依存の値 | 絶対パス、リポジトリ名、AWS プロファイル、バケット名、ディレクトリ名、使うコマンドのパス | `portability.md` の方法で実行時に求めるか、リポジトリ側の設定から読む形にする。統合版には値を書かない |
| (b) 振る舞いの本当の違い | 手順・選択肢・判断基準が違う。そのリポジトリにしか無い機能（例: dvc.yaml が無いリポジトリでは `repro` を出さない） | 存在確認で分岐できるなら統合版に条件として入れる。分岐が大きい・頻繁に変わるならそのリポジトリは own に残す |
| (c) 単に古いだけ | 片方が他方の古い版。誤記の修正、追記、後から入ったルールが片方に無い | 新しい方に揃える。どちらが新しいかは更新日時と内容で判断し、迷ったらユーザーに聞く |

(b) か (c) か迷うもの（片方にだけある手順）は、そのリポジトリでもその手順が意味を持つか確認する。持つなら (c)、持たないなら (b)。

## 3. ユーザーに見せる

次の形の表で見せ、(b) の扱いと迷った (c) を決めてもらう。

| 箇所 | 版ごとの内容 | 分類 | 提案 |
|---|---|---|---|
| キャッシュの場所 | ptcg: `/Users/.../ptcg/.dvc/cache` / reinforce: `/Users/.../05_reinforce/.dvc/cache` | a | `$MAIN/.dvc/cache` |
| `dvc repro` の選択肢 | kaggriculture: あり / reinforce: なし | b | `dvc.yaml` があるときだけ出す |

## 4. 統合版を残すか own に残すか

- 全差分が (a) と (c) → 全リポジトリを shared にする。
- (b) が条件分岐で書ける → shared にする。分岐の条件はリポジトリの中身で判定できるもの（ファイルの有無など）にし、リポジトリ名で分岐しない。
- (b) が条件分岐で書けない → そのリポジトリだけ own に残し、残りを shared にする。own に残す版にも (a) の修正は入れる。
