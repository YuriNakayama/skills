"""配布（sync）と取り込み（import）。入口は src/hub.py。

  skills/global/          -> ~/.claude/skills/<name>   （シンボリックリンク。全プロジェクト）
  skills/shared/          -> <repo>/.claude/skills     （コピー。repos.json の "shared" に書いたもの）
  skills/repos/<repo>/    -> <repo>/.claude/skills     （コピー。repos.json の "own" に書いたもの）

各リポジトリの .claude/skills/.hub-manifest に、前回配布した時点の各スキルのハッシュを記録する。
ハブ・リポジトリ・そのハッシュを比べて、どちらが変わったかを判定する:
  new       リポジトリにまだ無い         -> sync でコピーする
  same      同じ                         -> 何もしない（--check にも出ない）
  hub       ハブだけ変わった             -> sync で上書きする（import は --to own での非共通化だけ可）
  repo      リポジトリだけ変わった       -> sync はスキップ、import で取り込む
  both      両方変わった                 -> sync も import も --force が要る
  unknown   差分があり記録が無い         -> sync も import も --force が要る
  unmanaged リポジトリにだけある         -> import でそのリポジトリの own として取り込む
"""
import argparse
import os
import shutil
import subprocess
import sys

from common import (HUB, MANIFEST, SKILLS, USER_SKILLS, load_cfg, mirror, repo_root, save_cfg,
                    sources, tree_hash)

SYNC_DOC = __doc__
IMPORT_DOC = """リポジトリ側の変更・未管理のスキルをハブへ取り込む。

  uv run src/hub.py import X               X の変更（repo / both / unknown）と未管理のスキルをすべて取り込む
  uv run src/hub.py import X a b           a と b だけ取り込む（今の分類 shared / own のまま）
  uv run src/hub.py import X a --to shared skills/shared/ に取り込む（使っている全リポジトリに配布される）
  uv run src/hub.py import X a --to own    skills/repos/X/ に取り込む（X だけ非共通化する）
  uv run src/hub.py import X a --force     ハブ側も変わっていても取り込む
"""


# ---------- manifest (baseline) ----------

def read_manifest(target):
    """{名前: ハッシュ または None} を返す。ハッシュの無い古い形式は None。"""
    path = os.path.join(target, MANIFEST)
    out = {}
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.rstrip('\n')
                if not line or line.startswith('#'):
                    continue
                name, _, h = line.partition('\t')
                out[name] = h or None
    return out


def write_manifest(target, base):
    text = ('# Managed by the skills hub (~/project/98_skills). Do not edit these skills here.\n'
            '# Edit the hub copy and run: cd ~/project/98_skills && uv run src/hub.py sync\n'
            '# Changed one here anyway? Run: cd ~/project/98_skills && uv run src/hub.py import <repo>\n'
            + ''.join(f'{n}\t{base[n] or ""}\n' for n in sorted(base)))
    path = os.path.join(target, MANIFEST)
    if os.path.exists(path):
        with open(path) as f:
            if f.read() == text:
                return False
    os.makedirs(target, exist_ok=True)
    with open(path, 'w') as f:
        f.write(text)
    return True


def classify(src, dst, base_hash):
    hs, hd = tree_hash(src), tree_hash(dst)
    if hd is None:
        return 'new', hs
    if hs == hd:
        return 'same', hs
    if base_hash is None:
        return 'unknown', hs
    if hd == base_hash:
        return 'hub', hs
    if hs == base_hash:
        return 'repo', hs
    return 'both', hs


# ---------- distribute ----------

def sync_repo(repo, e, check, force):
    target = os.path.join(repo_root(e), '.claude', 'skills')
    srcs = sources(repo, e)
    missing = [s for s, p in srcs.items() if not os.path.isdir(p)]
    if missing:
        print(f'  ERROR hub has no source for: {missing}')
        return 1
    base = read_manifest(target)
    new_base, drift, blocked_n = {}, 0, 0
    for name, src in sorted(srcs.items()):
        dst = os.path.join(target, name)
        state, hs = classify(src, dst, base.get(name))
        if state == 'same':
            new_base[name] = hs
            continue
        drift += 1
        blocked = state in ('repo', 'both', 'unknown') and not force
        if blocked:
            blocked_n += 1
            new_base[name] = base.get(name)
            hint = {'repo': f'changed in repo. Run: uv run src/hub.py import {repo} {name}',
                    'both': 'changed in both hub and repo. Resolve, then use --force',
                    'unknown': 'differs and no baseline. Decide which to keep, then import --force or sync --force'}[state]
            print(f'  {state:8} {name}  ({hint})')
            continue
        changes = mirror(src, dst, write=not check)
        print(f'  {state:8} {name}  ({len(changes)} file(s){" to write" if check else " written"})')
        new_base[name] = hs
    existing = ({n for n in os.listdir(target) if os.path.isdir(os.path.join(target, n))}
                if os.path.isdir(target) else set())
    unmanaged = sorted(existing - srcs.keys())
    if unmanaged:
        print(f'  unmanaged {", ".join(unmanaged)}  (only in repo. Run: uv run src/hub.py import {repo} <name>)')
    if check:
        cur = read_manifest(target)
        if cur != new_base:
            print('  manifest  baseline to update')
            drift += 1
        return drift + len(unmanaged)
    if write_manifest(target, new_base):
        print('  manifest  updated')
    return blocked_n + len(unmanaged)


def sync_global(check):
    drift = 0
    gdir = os.path.join(SKILLS, 'global')
    os.makedirs(USER_SKILLS, exist_ok=True)
    for name in sorted(os.listdir(gdir)):
        src = os.path.join(gdir, name)
        if not os.path.isdir(src):
            continue
        link = os.path.join(USER_SKILLS, name)
        if os.path.islink(link) and os.path.realpath(link) == os.path.realpath(src):
            continue
        drift += 1
        if os.path.exists(link) and not os.path.islink(link):
            print(f'  conflict  {link} is a real directory. Move it into hub/skills/global first.')
            continue
        print(f'  link      {link} -> {src}')
        if check:
            continue
        drift -= 1
        if os.path.islink(link):
            os.remove(link)
        os.symlink(src, link)
    for name in sorted(os.listdir(USER_SKILLS)):
        p = os.path.join(USER_SKILLS, name)
        if os.path.islink(p) and not os.path.exists(p):
            print(f'  broken    {p} -> {os.readlink(p)}')
            drift += 1
        elif os.path.isdir(p) and not os.path.islink(p) and name not in ('synced', 'learned'):
            print(f'  unmanaged {p} (move it into hub/skills/global)')
            drift += 1
    return drift


def cmd_sync(a):
    cfg = load_cfg()['repos']
    if a.repo and a.repo not in cfg:
        print(f'unknown repo: {a.repo}', file=sys.stderr)
        return 2
    total = 0
    if not a.repo:
        print('== global (~/.claude/skills)')
        total += sync_global(a.check)
    for repo, e in cfg.items():
        if a.repo and repo != a.repo:
            continue
        print(f'== {repo} ({repo_root(e)})')
        if not os.path.isdir(repo_root(e)):
            print('  missing repo, skipped')
            continue
        total += sync_repo(repo, e, a.check, a.force)
    print(f'\n{"drift" if a.check else "not in sync"}: {total}')
    return 1 if total else 0


# ---------- check-repo（リポジトリ側の変更が取り込まれているか） ----------

CHECK_REPO_DOC = """リポジトリ側の .claude/skills に、ハブへ取り込まれていない変更や未管理のスキルが無いかを見る。

  uv run src/hub.py check-repo <名前>            作業中の作業ツリー（worktree を含む）の .claude/skills を見る
  uv run src/hub.py check-repo --here            リポジトリを作業中のディレクトリから判定する（管理外なら何もせず exit 0）
  uv run src/hub.py check-repo <名前> --path D   作業ツリー D の .claude/skills を見る

問題にするのはリポジトリ側の状態（unmanaged、repo、both、unknown）だけ。ハブ側の更新（hub、new）は問題にしない。
register で設置する pre-commit から使う。問題があれば exit 1。
"""


def git_out(args, cwd):
    r = subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ''


def main_root(d):
    """d を含む git リポジトリのメインの作業ツリー（worktree から見ても同じ）。git でなければ ''。"""
    common = git_out(['rev-parse', '--path-format=absolute', '--git-common-dir'], d)
    if not common or os.path.basename(common) != '.git':
        return ''
    return os.path.realpath(os.path.dirname(common))


def within(path, root):
    return path == root or path.startswith(root.rstrip('/') + '/')


def resolve_tree(cfg, name, path):
    """check-repo が見る作業ツリーと、リポジトリ名を決める。(名前, 作業ツリー, エラー) を返す。

    - path を省いたら作業中のディレクトリを使う。git の作業ツリー（worktree を含む）ならそのルート。
    - git でなければ（carrier など）、登録済みのリポジトリの場所を親方向にたどって照合する。
    - 名前を指定して、作業中のディレクトリがそのリポジトリの外（ハブなど）なら、登録済みの場所を見る。
    - 名前を省いたら、作業中のディレクトリから判定する（管理外なら名前は None）。
    """
    explicit = path is not None
    cwd = os.path.realpath(path or os.getcwd())
    top = git_out(['rev-parse', '--show-toplevel'], cwd)
    top = os.path.realpath(top) if top else ''
    main = main_root(cwd)
    roots = {r: os.path.realpath(repo_root(e)) for r, e in cfg.items() if not e.get('path', '').startswith('~')}

    def owner():
        if main:        # git の中: メインの作業ツリーが登録済みなら、今の作業ツリー（worktree を含む）を見る
            hit = next((r for r, rr in roots.items() if rr == main), None)
            if hit:
                return hit, top or main
        # git でない、またはメインの作業ツリーが登録されていない: 作業中のディレクトリを含む登録済みの場所（いちばん深いもの）
        hits = sorted(((r, rr) for r, rr in roots.items() if within(cwd, rr)), key=lambda x: -len(x[1]))
        return hits[0] if hits else (None, None)

    found, tree = owner()
    if name is None:
        return found, tree, None
    if name not in cfg:
        return name, None, f'unknown repo: {name}'
    if found == name:
        return name, tree, None
    if explicit:
        return name, None, f'{path} は {name} の作業ツリーではない'
    return name, roots.get(name), None


def cmd_check_repo(a):
    cfg = load_cfg()['repos']
    name, tree, error = resolve_tree(cfg, None if a.here else a.repo, a.path)
    if error:
        print(error, file=sys.stderr)
        return 2
    if name is None or tree is None:
        return 0        # 管理外のリポジトリ
    e = cfg[name]
    target = os.path.join(tree, '.claude', 'skills')
    if not os.path.isdir(target):
        return 0
    srcs = sources(name, e)
    base = read_manifest(target)
    problems = 0
    for n in sorted(os.listdir(target)):
        dst = os.path.join(target, n)
        if n.startswith('.') or not os.path.isdir(dst):
            continue
        if n not in srcs:
            print(f'  unmanaged {n}  (ハブで管理されていない。取り込む: cd ~/project/98_skills && uv run src/hub.py import {name} {n})')
            problems += 1
            continue
        state, _ = classify(srcs[n], dst, base.get(n))
        if state == 'repo':
            print(f'  repo     {n}  (リポジトリ側で変更されている。取り込む: cd ~/project/98_skills && uv run src/hub.py import {name} {n})')
            problems += 1
        elif state in ('both', 'unknown'):
            print(f'  {state:8} {n}  (ハブとリポジトリの両方に差分がある。どちらを残すか決めてから skill-sync で解消する)')
            problems += 1
    if problems:
        print(f'\n{name}: ハブに取り込まれていないスキルが {problems} 件（skill-sync で取り込む。'
              f'今回だけ飛ばすなら git commit --no-verify）')
        return 1
    return 0


CLAUDE_HOOK_DOC = """Claude Code の PostToolUse フック（Write / Edit / MultiEdit）から呼ぶ。

標準入力のフックの JSON から書いたファイルを取り出し、それが管理下のリポジトリの .claude/skills の下なら
check-repo --here と同じ判定をする。ハブへ取り込まれていない変更や未管理のスキルがあれば、
{"decision": "block", "reason": ...} を標準出力に出す（Claude に伝わる。ツールの実行は取り消されない）。

終了コードは常に 0。判定できなかったとき（ハブの設定が読めないなど）も何も出さずに 0 で終わり、
Claude の作業を邪魔しない。
"""


def cmd_claude_hook(a):
    import contextlib
    import io
    import json
    try:
        data = json.load(sys.stdin)
        if not isinstance(data, dict):
            return 0
        f = ((data.get('tool_input') or {}).get('file_path')
             or (data.get('tool_response') or {}).get('filePath') or '')
        if '/.claude/skills/' not in f or os.path.basename(f) == MANIFEST:
            return 0
        d = os.path.dirname(f)
        while d and d != '/' and not os.path.isdir(d):
            d = os.path.dirname(d)
        if not d:
            return 0
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cmd_check_repo(argparse.Namespace(repo=None, here=True, path=d))
    except Exception:
        return 0
    if rc == 1:
        reason = ('skills hub: このリポジトリの .claude/skills に、ハブへ取り込まれていない変更がある。'
                  'skill-sync で取り込むか（新しいリポジトリなら skill-register）、ユーザーに確認する。\n' + out.getvalue())
        print(json.dumps({'decision': 'block', 'reason': reason}, ensure_ascii=False))
    return 0


# ---------- import ----------

def cmd_import(a):
    cfg = load_cfg()
    if a.repo not in cfg['repos']:
        print(f'unknown repo: {a.repo}', file=sys.stderr)
        return 2
    e = cfg['repos'][a.repo]
    target = os.path.join(repo_root(e), '.claude', 'skills')
    srcs = sources(a.repo, e)
    base = read_manifest(target)
    existing = sorted(n for n in os.listdir(target) if os.path.isdir(os.path.join(target, n)))

    names = a.skills
    if not names:
        names = []
        for n in existing:
            if n not in srcs:
                names.append(n)
            else:
                state, _ = classify(srcs[n], os.path.join(target, n), base.get(n))
                if state in ('repo', 'both', 'unknown'):
                    names.append(n)
        if not names:
            print(f'{a.repo}: nothing to import')
            return 0

    failed = imported = 0
    for n in names:
        dst = os.path.join(target, n)
        if not os.path.isdir(dst):
            print(f'  skip     {n}  (not found in {target})')
            failed += 1
            continue
        if n in srcs:
            state, _ = classify(srcs[n], dst, base.get(n))
            if state == 'same' and a.to is None:
                print(f'  same     {n}  (nothing to import)')
                continue
            # hub: リポジトリ側は前回配布のまま。--to own（そのリポジトリだけ旧版で非共通化）だけ許す
            if state == 'hub' and not (a.to == 'own' and n in e.get('shared', [])):
                print(f'  hub      {n}  (only the hub changed. Run sync instead of import'
                      f'{"; to keep the old version for this repo only, use --to own" if n in e.get("shared", []) else ""})')
                failed += 1
                continue
            if state in ('both', 'unknown') and not a.force:
                print(f'  {state:8} {n}  (hub side may have changes too. Review, then use --force)')
                failed += 1
                continue
        # --to を省いたら今の分類を保つ（shared のスキルは shared に、それ以外は own に取り込む）
        to = a.to or ('shared' if n in e.get('shared', []) else 'own')
        if to == 'own':
            dest = os.path.join(SKILLS, 'repos', a.repo, n)
            e['shared'] = [x for x in e.get('shared', []) if x != n]
            e.setdefault('own', []).append(n)
        else:
            dest = os.path.join(SKILLS, 'shared', n)
            # 別の内容の skills/shared/<n> が既にあるのに、このリポジトリの版で黙って上書きしない（統合は skill-share の手順で）
            if (n not in e.get('shared', []) and os.path.isdir(dest)
                    and tree_hash(dest) != tree_hash(dst) and not a.force):
                print(f'  conflict {n}  (skills/shared/{n} already exists with different content. '
                      f'Merge the variants first, or use --force to overwrite it with this repo\'s copy)')
                failed += 1
                continue
            e['own'] = [x for x in e.get('own', []) if x != n]
            e.setdefault('shared', []).append(n)
            stale = os.path.join(SKILLS, 'repos', a.repo, n)
            if os.path.isdir(stale):
                shutil.rmtree(stale)
        changes = mirror(dst, dest, write=True)
        imported += 1
        base[n] = tree_hash(dest)
        print(f'  import   {n} -> {os.path.relpath(dest, HUB)}  ({len(changes)} file(s))')
        if to == 'shared':
            users = sorted(r for r, x in cfg['repos'].items() if r != a.repo and n in x.get('shared', []))
            if users:
                print(f'           also distributed to: {", ".join(users)} (on next sync)')
    if imported:
        save_cfg(cfg)
        write_manifest(target, {k: v for k, v in base.items() if k in sources(a.repo, e)})
        print('\nReview with: git -C ~/project/98_skills diff')
    return 1 if failed else 0
