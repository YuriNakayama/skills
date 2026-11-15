"""スキルの重複の検査（uv run src/hub.py check-duplicates）。"""
import collections

from common import files, list_skills, tree_hash

DOC = """ハブ内のスキルの重複を検出する。

  uv run src/hub.py check-duplicates   全チェック（重複があれば exit 1、チェック自体が失敗したら exit 2）

対象は skills/global/<name>、skills/shared/<name>、skills/repos/<repo>/<name> のディレクトリ。
内容の比較は配布と同じ規則（スキル内の全ファイル。.DS_Store と __pycache__ は除く）で行う。

チェック内容（どれも見つかれば exit 1）:
  empty     中身が空（ファイルが 0 個）のスキル。以下の内容の比較からは外す
  layers    同じ名前のスキルが、global・shared・repos のうち 2 つ以上の層にある
  same      skills/repos/ の中で、同じ名前のスキルが複数のリポジトリにあり、内容が同一（shared にまとめられる）
  renamed   名前が違うのに内容が同一のスキル（層は問わない）
  variants  同じ名前で内容が違うスキル（層は問わない。改変版が分岐している）

1 つの重複が複数の種類に当てはまれば、それぞれの種類で報告する（例: 層をまたいだ同名で内容も違う）。
許可リストは持たない。統合の手順は skills/global/skill-share を参照。
"""


def layer_of(loc):
    return 'repos' if loc.startswith('repos/') else loc


def main(a):
    skills = list_skills()
    errors = 0

    def err(kind, what, detail):
        nonlocal errors
        print(f'  {kind:<9}{what}: {detail}')
        errors += 1

    # --- empty ---------------------------------------------------------------
    print('== 空のスキル')
    content = []          # 中身のあるスキルだけ (場所, 名前, ハッシュ)
    for loc, n, p in skills:
        if not files(p):
            err('empty', f'skills/{loc}/{n}', 'ファイルが無い')
        else:
            content.append((loc, n, tree_hash(p)))

    # --- layers --------------------------------------------------------------
    print('== 層をまたいだ同名')
    by_name = collections.defaultdict(list)
    for loc, n, _ in skills:
        by_name[n].append(loc)
    for n in sorted(by_name):
        if len({layer_of(loc) for loc in by_name[n]}) > 1:
            err('layers', n, ', '.join(by_name[n]))

    # --- same（repos/ の中で内容が同一） -------------------------------------
    print('== skills/repos/ の中で内容が同一')
    groups = collections.defaultdict(list)           # (名前, ハッシュ) -> [場所]
    for loc, n, h in content:
        if layer_of(loc) == 'repos':
            groups[(n, h)].append(loc)
    for (n, _), locs in sorted(groups.items()):
        if len(locs) > 1:
            err('same', n, ' = '.join(locs))

    # --- renamed（名前が違い内容が同一） --------------------------------------
    print('== 名前が違い内容が同一')
    by_hash = collections.defaultdict(list)
    for loc, n, h in content:
        by_hash[h].append((loc, n))
    for items in sorted(by_hash.values()):
        names = sorted({n for _, n in items})
        if len(names) > 1:
            err('renamed', ', '.join(names), ' = '.join(f'{loc}/{n}' for loc, n in items))

    # --- variants（同名で内容が違う） ----------------------------------------
    print('== 同名で内容が違う')
    versions = collections.defaultdict(lambda: collections.defaultdict(list))   # 名前 -> ハッシュ -> [場所]
    for loc, n, h in content:
        versions[n][h].append(loc)
    for n in sorted(versions):
        vs = versions[n]
        if len(vs) > 1:
            err('variants', n, f'{len(vs)} 版 — ' + ' / '.join('[' + ', '.join(locs) + ']' for locs in vs.values()))

    print()
    if errors:
        print(f'NG: 重複が {errors} 件')
        return 1
    print('OK: 重複は無い')
    return 0
