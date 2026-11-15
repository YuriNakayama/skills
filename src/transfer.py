"""配布（export）と取り込み（import）。入口は src/hub.py。

  skills/global/          -> ~/.claude/skills/<name>   （シンボリックリンク。全プロジェクト）
  skills/shared/          -> <repo>/.claude/skills     （コピー。repos.json の "shared" に書いたもの）
  skills/repos/<repo>/    -> <repo>/.claude/skills     （コピー。repos.json の "own" に書いたもの）

各リポジトリの .claude/skills/.hub-manifest に、前回配布した時点の各スキルのハッシュを記録する。
ハブ・リポジトリ・そのハッシュを比べて、どちらが変わったかを判定する:
  new       リポジトリにまだ無い         -> export でコピーする
  same      同じ                         -> 何もしない（diff にも出ない）
  hub       ハブだけ変わった             -> export で上書きする（import は拒否）
  repo      リポジトリだけ変わった       -> export はスキップ、import で取り込む
  both      両方変わった                 -> export も import も --force が要る
  unknown   差分があり記録が無い         -> export も import も --force が要る
  unmanaged リポジトリにだけある         -> import でそのリポジトリの own として取り込む

export は配布の前に check-paths と check-duplicates を実行し、どちらかが失敗したら配布しない。
export が書くのは、既定のブランチを checkout している作業ツリーだけ（ほかのブランチは作業中とみなす。--path / --here で
明示すれば書く）。ハブで未コミットのスキルは配らない（編集途中を広げない。コミットしてから export する）。
"""
import argparse
import os
import shutil
import subprocess
import sys

from common import (HUB, MANIFEST, SKILLS, USER_SKILLS, list_skills, load_cfg, mirror, repo_root,
                    save_cfg, sources, subdirs, tree_hash)

SYNC_DOC = __doc__
IMPORT_DOC = """リポジトリ側の変更・未管理のスキルをハブへ取り込む。

  uv run src/hub.py import X               X の変更（repo / both / unknown）と未管理のスキルをすべて取り込む
  uv run src/hub.py import X a b           a と b だけ取り込む（今の分類 shared / own のまま）
  uv run src/hub.py import X a --to shared skills/shared/ に取り込む（使っている全リポジトリに配布される）
  uv run src/hub.py import X a --to own    skills/repos/X/ に取り込む
  uv run src/hub.py import X a --force     ハブ側も変わっていても取り込む

取り込み元（省いたら登録した場所の作業ツリー）:
  --here           作業中のディレクトリを含む作業ツリー（worktree でも、別のブランチを checkout していてもよい）
  --path D         作業ツリー D
  --ref R          ブランチやコミット R にコミットされている中身（checkout していなくてよい。git が無視するファイルは入らない）
--here / --path では、取り込んだ後にその作業ツリーの .hub-manifest を更新する。--ref では作業ツリーに何も書かない。

1 つの名前には 1 つの中身（規則）。取り込む先以外（global・shared・ほかのリポジトリの own）に
同じ名前のスキルがあれば、--force でも取り込まない。振る舞いの違う版は skill-share で別の名前に分ける。
"""


# ---------- manifest (baseline) ----------

GITATTRIBUTES = '.gitattributes'
GITATTRIBUTES_TEXT = ('# skills hub: ブランチのマージで .hub-manifest がぶつからないように、両方の行を残す。\n'
                      '# 判定は記録のどれかと一致すれば「変わっていない」とみなし、次の export で 1 行に戻す。\n'
                      f'{MANIFEST} merge=union\n')


def read_manifest(target):
    """{名前: 記録されたハッシュの集合} を返す。

    マージ（merge=union）で 1 つのスキルに複数の行が残ることがあるので集合にする。ハッシュの無い古い形式は空集合。
    """
    path = os.path.join(target, MANIFEST)
    out = {}
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.rstrip('\n')
                if not line or line.startswith('#'):
                    continue
                name, _, h = line.partition('\t')
                out.setdefault(name, set())
                if h:
                    out[name].add(h)
    return out


def parse_manifest(text):
    out = {}
    for line in text.splitlines():
        if not line or line.startswith('#'):
            continue
        name, _, h = line.partition('\t')
        out.setdefault(name, set())
        if h:
            out[name].add(h)
    return out


def branch_point_bases(tree):
    """既定のブランチ以外を checkout している作業ツリーで、既定のブランチとの分岐点の記録を返す。

    {名前: ハッシュの集合}。分岐点にコミットされていた .hub-manifest の記録と、分岐点のスキルの中身のハッシュ。
    .hub-manifest に記録の無いスキル（ハブを使い始める前に分けたブランチなど）を判定する基準にする:
    分岐点のままなら「ハブだけ変わった」、ブランチで直していれば「リポジトリだけ変わった」になる。
    既定のブランチそのもの、git でない、分岐点が分からないときは {}。
    """
    if not tree or not git_out(['rev-parse', '--git-dir'], tree):
        return {}
    default = default_branch(tree)
    branch = git_out(['branch', '--show-current'], tree)
    if not default or branch == default:
        return {}
    mb = git_out(['merge-base', 'HEAD', default], tree)
    if not mb:
        return {}
    out = parse_manifest(git_out(['show', f'{mb}:.claude/skills/{MANIFEST}'], tree))
    tmp, error = export_ref(tree, mb)
    if tmp:
        try:
            snap = os.path.join(tmp, '.claude', 'skills')
            for n in subdirs(snap):
                out.setdefault(n, set()).add(tree_hash(os.path.join(snap, n)))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return out


def load_base(target, tree):
    """target（.claude/skills）の記録。記録の無いスキルは、分岐点の記録で補う（branch_point_bases）。"""
    base = read_manifest(target)
    missing = [n for n in subdirs(target) if not base.get(n)]
    if missing:
        fb = branch_point_bases(tree)
        for n in missing:
            if fb.get(n):
                base[n] = set(fb[n])
    return base


def write_manifest(target, base):
    """base は {名前: ハッシュ または ハッシュの集合}。変わったときだけ書いて True を返す。"""
    def hashes(v):
        return sorted(v) if isinstance(v, (set, frozenset, list, tuple)) else ([v] if v else [])
    lines = ''
    for n in sorted(base):
        hs = hashes(base[n])
        lines += ''.join(f'{n}\t{h}\n' for h in hs) if hs else f'{n}\t\n'
    text = ('# Managed by the skills hub (~/project/98_skills). Do not edit these skills here.\n'
            '# Edit the hub copy and run: cd ~/project/98_skills && uv run src/hub.py export\n'
            '# Changed one here anyway? Run: cd ~/project/98_skills && uv run src/hub.py import <repo> --path <this worktree>\n'
            + lines)
    path = os.path.join(target, MANIFEST)
    if os.path.exists(path):
        with open(path) as f:
            if f.read() == text:
                return False
    os.makedirs(target, exist_ok=True)
    with open(path, 'w') as f:
        f.write(text)
    return True


def classify(src, dst, bases):
    """bases は記録されたハッシュの集合（マージで複数になることがある。無ければ空か None）。"""
    hs, hd = tree_hash(src), tree_hash(dst)
    bases = bases or set()
    if hd is None:
        return 'new', hs
    if hs == hd:
        return 'same', hs
    if not bases:
        return 'unknown', hs
    if hd in bases:         # リポジトリ側は過去に配った版のどれかのまま
        return 'hub', hs
    if hs in bases:
        return 'repo', hs
    return 'both', hs


def write_gitattributes(target, check):
    """.claude/skills/.gitattributes（.hub-manifest を merge=union にする）。書く必要があれば True。"""
    path = os.path.join(target, GITATTRIBUTES)
    if os.path.exists(path):
        with open(path) as f:
            if f.read() == GITATTRIBUTES_TEXT:
                return False
    if not check:
        os.makedirs(target, exist_ok=True)
        with open(path, 'w') as f:
            f.write(GITATTRIBUTES_TEXT)
    return True


# ---------- distribute ----------

def norm(base):
    """manifest の比較用に {名前: frozenset(ハッシュ)} にそろえる。"""
    out = {}
    for n, v in base.items():
        if isinstance(v, (set, frozenset, list, tuple)):
            out[n] = frozenset(v)
        else:
            out[n] = frozenset([v]) if v else frozenset()
    return out


def worktrees(root):
    """root のリポジトリの作業ツリー（メインと linked worktree）の一覧。git でなければ [root]。

    bare の項目と、場所が無くなった（prunable な）worktree は除く。
    """
    r = subprocess.run(['git', 'worktree', 'list', '--porcelain'], cwd=root, capture_output=True, text=True)
    if r.returncode != 0:
        return [root]
    out, cur = [], None
    for line in r.stdout.splitlines() + ['']:
        if line.startswith('worktree '):
            cur = {'path': line[len('worktree '):]}
        elif line == 'bare' and cur is not None:
            cur['bare'] = True
        elif line == '' and cur is not None:
            if not cur.get('bare') and os.path.isdir(cur['path']):
                out.append(os.path.realpath(cur['path']))
            cur = None
    main = os.path.realpath(root)
    return sorted(set(out) | {main}, key=lambda p: (p != main, p)) if out else [root]


_UNCOMMITTED = None


def uncommitted_skills():
    """ハブで未コミットの変更があるスキルのディレクトリ（ハブからの相対パス）の集合。"""
    global _UNCOMMITTED
    if _UNCOMMITTED is None:
        r = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=all', '--', 'skills'],
                           cwd=HUB, capture_output=True, text=True)
        out = r.stdout if r.returncode == 0 else ''     # git_out は先頭の空白も削るので使わない
        dirs = set()
        for line in out.splitlines():
            path = line[3:].split(' -> ')[-1].strip('"')
            parts = path.split('/')
            if len(parts) >= 3 and parts[1] in ('global', 'shared'):
                dirs.add('/'.join(parts[:3]))
            elif len(parts) >= 4 and parts[1] == 'repos':
                dirs.add('/'.join(parts[:4]))
        _UNCOMMITTED = dirs
    return _UNCOMMITTED


def on_default_branch(tree):
    """tree が既定のブランチを checkout しているか。git でない、既定のブランチが分からないときは True。"""
    if not git_out(['rev-parse', '--git-dir'], tree):
        return True
    default = default_branch(tree)
    return not default or git_out(['branch', '--show-current'], tree) == default


def sync_repo(repo, e, check, force, tree=None):
    """tree（作業ツリー。省いたら登録した場所）の .claude/skills に配る。"""
    target = os.path.join(tree or repo_root(e), '.claude', 'skills')
    srcs = sources(repo, e)
    missing = [s for s, p in srcs.items() if not os.path.isdir(p)]
    if missing:
        print(f'  ERROR hub has no source for: {missing}')
        return 1
    base = load_base(target, tree or repo_root(e))
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
            hint = {'repo': f'changed in repo. Run: uv run src/hub.py import {repo} {name}{path_opt(e, tree)}',
                    'both': 'changed in both hub and repo. Resolve, then use --force',
                    'unknown': 'differs and no baseline. Decide which to keep, then import --force or export --force'}[state]
            print(f'  {state:8} {name}  ({hint})')
            continue
        if os.path.relpath(src, HUB) in uncommitted_skills():
            # ハブで編集中（未コミット）のスキルは配らない。ほかのセッションの作業途中を広げないため
            blocked_n += 1
            new_base[name] = base.get(name)
            print(f'  {state:8} {name}  (uncommitted in the hub: commit {os.path.relpath(src, HUB)} first, then export)')
            continue
        changes = mirror(src, dst, write=not check)
        print(f'  {state:8} {name}  ({len(changes)} file(s){" to write" if check else " written"})')
        new_base[name] = hs
    existing = set(subdirs(target))       # *-workspace（評価の記録）はスキルではないので数えない
    unmanaged = sorted(existing - srcs.keys())
    if unmanaged:
        print(f'  unmanaged {", ".join(unmanaged)}  (only in repo. Run: uv run src/hub.py import {repo} <name>{path_opt(e, tree)})')
    if check:
        if norm(read_manifest(target)) != norm(new_base):
            print('  manifest  baseline to update')
            drift += 1
        if os.path.isdir(target) and write_gitattributes(target, check=True):
            print(f'  manifest  {GITATTRIBUTES} to write')
            drift += 1
        return drift + len(unmanaged)
    if write_manifest(target, new_base):
        print('  manifest  updated')
    if write_gitattributes(target, check=False):
        print(f'  manifest  {GITATTRIBUTES} written')
    return blocked_n + len(unmanaged)


def path_opt(e, tree):
    """登録した場所以外の作業ツリーなら、import に付ける --path を返す。"""
    if tree and os.path.realpath(tree) != os.path.realpath(repo_root(e)):
        return f' --path {tree}'
    return ''


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
            # ハブの skills/global を指していた切れたリンク（global のスキルを改名・削除した跡）は export が消す
            dest = os.path.join(os.path.dirname(p), os.readlink(p))
            if within(os.path.normpath(dest), os.path.normpath(gdir)) and not check:
                os.remove(p)
                print(f'  removed   {p} (the hub no longer has {os.path.relpath(dest, HUB)})')
                continue
            print(f'  broken    {p} -> {os.readlink(p)}')
            drift += 1
        elif os.path.isdir(p) and not os.path.islink(p) and name not in ('synced', 'learned'):
            print(f'  unmanaged {p} (move it into hub/skills/global)')
            drift += 1
    return drift


def gate(repo=None):
    """配布の前の関門: check-paths と check-duplicates。どちらかが 0 以外ならその終了コードを返す（例外は無い）。

    止めるのは規則の違反（配布するスキルの絶対パス、重複）と、repos.json とハブの中身の食い違いだけ。
    登録したリポジトリが無い、切れたリンクなどは警告にとどめる（詳しくは check-paths の説明）。
    repo を指定すると、絶対パスはそのリポジトリに配布するスキルの分だけを見る。
    """
    import duplicated_skill
    import path_check
    rc = path_check.main(argparse.Namespace(no_abs=False, gate=True, repo=repo))
    print()
    rd = duplicated_skill.main(argparse.Namespace())
    print()
    worst = max(rc, rd)
    if worst:
        print(f'配布しない: 配布の前の検査が失敗した（check-paths exit {rc}、check-duplicates exit {rd}）。'
              '直し方は skills/global/skill-share を参照', file=sys.stderr)
    return worst


def cmd_sync(a):
    cfg = load_cfg()['repos']
    if a.repo and a.repo not in cfg:
        print(f'unknown repo: {a.repo}', file=sys.stderr)
        return 2
    only = None         # --here / --path: 1 つの作業ツリーだけに配る
    if a.here or a.path:
        name, tree, error = resolve_tree(cfg, a.repo, a.path or os.getcwd())
        if error or name is None or tree is None:
            print(error or f'{a.path or os.getcwd()} は登録済みのリポジトリの作業ツリーではない', file=sys.stderr)
            return 2
        a.repo, only = name, tree
    if not a.check:     # 実際に配布するときだけ。diff は状態を見るだけなので検査しない
        rc = gate(a.repo)
        if rc:
            return rc
    total = 0
    if not a.repo:
        print('== global (~/.claude/skills)')
        total += sync_global(a.check)
    for repo, e in cfg.items():
        if a.repo and repo != a.repo:
            continue
        if not os.path.isdir(repo_root(e)):
            print(f'== {repo} ({repo_root(e)})\n  missing repo, skipped')
            continue
        # 既定ではそのリポジトリの作業ツリーすべて（メインと linked worktree）を見る。
        # 配る（書く）のは既定のブランチを checkout している作業ツリーだけ。ほかのブランチは作業中なので、
        # --path / --here で明示したときだけ書く（diff はすべてを表示する）
        for tree in [only] if only else worktrees(repo_root(e)):
            print(f'== {repo} ({tree})')
            if not a.check and not only and not on_default_branch(tree):
                branch = git_out(['branch', '--show-current'], tree) or 'detached HEAD'
                print(f'  skipped  ({branch} is not the default branch: work in progress. '
                      f'To update it anyway: uv run src/hub.py export --path {tree})')
                continue
            total += sync_repo(repo, e, a.check, a.force, tree)
    print(f'\n{"drift" if a.check else "not exported"}: {total}')
    return 1 if total else 0


# ---------- check-repo（リポジトリ側の変更が取り込まれているか） ----------

CHECK_REPO_DOC = """リポジトリ側の .claude/skills に、ハブへ取り込まれていない変更や未管理のスキルが無いかを見る。

  uv run src/hub.py check-repo <名前>            作業中の作業ツリー（worktree を含む）の .claude/skills を見る
  uv run src/hub.py check-repo --here            リポジトリを作業中のディレクトリから判定する（管理外なら何もせず exit 0）
  uv run src/hub.py check-repo <名前> --path D   作業ツリー D の .claude/skills を見る

問題にするのはリポジトリ側の状態（unmanaged、repo、both、unknown）だけ。ハブ側の更新（hub、new）は問題にしない。
register で設置する pre-commit から使う。問題があれば exit 1。

  --default-branch-only   既定のブランチ（origin/HEAD、無ければ main か master）以外と、マージのコミットでは、
                          問題を表示するだけで exit 0（pre-commit 用。開発中のブランチでは取り込む前のスキルもコミットでき、
                          それを既定のブランチにマージしてから取り込めるようにする）
"""


def default_branch(tree):
    """既定のブランチの名前（origin/HEAD が指すもの。無ければ main、master のうちあるもの）。分からなければ ''。"""
    ref = git_out(['symbolic-ref', '--quiet', '--short', 'refs/remotes/origin/HEAD'], tree)
    if ref:
        return ref.split('/', 1)[1] if '/' in ref else ref
    for b in ('main', 'master'):
        if git_out(['rev-parse', '--verify', '--quiet', f'refs/heads/{b}'], tree):
            return b
    return ''


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
    base = load_base(target, tree)
    problems = 0
    opt = path_opt(e, tree)
    for n in subdirs(target):              # *-workspace（評価の記録）は対象外
        dst = os.path.join(target, n)
        if n not in srcs:
            print(f'  unmanaged {n}  (ハブで管理されていない。取り込む: cd ~/project/98_skills && uv run src/hub.py import {name} {n}{opt})')
            problems += 1
            continue
        state, _ = classify(srcs[n], dst, base.get(n))
        if state == 'repo':
            print(f'  repo     {n}  (リポジトリ側で変更されている。取り込む: cd ~/project/98_skills && uv run src/hub.py import {name} {n}{opt})')
            problems += 1
        elif state in ('both', 'unknown'):
            print(f'  {state:8} {n}  (ハブとリポジトリの両方に差分がある。どちらを残すか決めてから skill-transfer で解消する)')
            problems += 1
    if problems:
        branch = git_out(['branch', '--show-current'], tree)
        default = default_branch(tree)
        if getattr(a, 'default_branch_only', False) and default and branch != default:
            print(f'\n{name}: ハブに取り込まれていないスキルが {problems} 件。{branch or "（ブランチ外）"} は既定のブランチ（{default}）'
                  'ではないので、コミットは止めない（取り込みは上のコマンドか、マージ後に import --ref で行う）')
            return 0
        if getattr(a, 'default_branch_only', False) and git_out(['rev-parse', '-q', '--verify', 'MERGE_HEAD'], tree):
            print(f'\n{name}: ハブに取り込まれていないスキルが {problems} 件。マージのコミットなので止めない'
                  f'（マージした後に uv run src/hub.py import {name} <name> --ref {branch or "HEAD"} で取り込む）')
            return 0
        print(f'\n{name}: ハブに取り込まれていないスキルが {problems} 件（skill-transfer で取り込む。'
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
                  'skill-transfer で取り込むか（新しいリポジトリなら skill-register）、ユーザーに確認する。\n' + out.getvalue())
        print(json.dumps({'decision': 'block', 'reason': reason}, ensure_ascii=False))
    return 0


# ---------- import ----------

def cmd_import(a):
    cfg = load_cfg()
    if a.repo not in cfg['repos']:
        print(f'unknown repo: {a.repo}', file=sys.stderr)
        return 2
    e = cfg['repos'][a.repo]
    if sum(bool(x) for x in (a.here, a.path, a.ref)) > 1:
        print('--here、--path、--ref はどれか 1 つだけ', file=sys.stderr)
        return 2
    tmp = None
    try:
        if a.ref:
            tmp, error = export_ref(repo_root(e), a.ref)
            if error:
                print(error, file=sys.stderr)
                return 2
            tree = tmp
        elif a.here or a.path:
            _, tree, error = resolve_tree(cfg['repos'], a.repo, a.path or os.getcwd())
            if error or tree is None:
                print(error or f'{a.path or os.getcwd()} は {a.repo} の作業ツリーではない', file=sys.stderr)
                return 2
        else:
            tree = repo_root(e)
        return import_from(a, cfg, e, os.path.join(tree, '.claude', 'skills'), write_back=not a.ref,
                           tree=None if a.ref else tree)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def export_ref(root, ref):
    """ref にコミットされている .claude/skills を一時ディレクトリに取り出す。(ディレクトリ, エラー) を返す。"""
    import tarfile
    import tempfile
    if not git_out(['rev-parse', '--verify', '--quiet', ref + '^{commit}'], root):
        return None, f'{ref} は {root} のブランチやコミットではない'
    tmp = tempfile.mkdtemp(prefix='skills-hub-ref-')
    r = subprocess.run(['git', 'archive', '--format=tar', ref, '--', '.claude/skills'],
                       cwd=root, capture_output=True)
    if r.returncode != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        return None, f'{ref} に .claude/skills が無い（{r.stderr.decode(errors="replace").strip()}）'
    import io
    with tarfile.open(fileobj=io.BytesIO(r.stdout)) as t:
        t.extractall(tmp, filter='data')
    return tmp, None


def import_from(a, cfg, e, target, write_back, tree):
    """target（取り込み元の .claude/skills）から取り込む。write_back なら target の .hub-manifest も更新する。"""
    srcs = sources(a.repo, e)
    base = load_base(target, tree)
    existing = subdirs(target)

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
            if state == 'hub':     # リポジトリ側は前回配布のまま。取り込むものは無い
                print(f'  hub      {n}  (only the hub changed. Run export instead of import)')
                failed += 1
                continue
            if state in ('both', 'unknown') and not a.force:
                print(f'  {state:8} {n}  (hub side may have changes too. Review, then use --force)')
                failed += 1
                continue
        # --to を省いたら今の分類を保つ（shared のスキルは shared に、それ以外は own に取り込む）
        to = a.to or ('shared' if n in e.get('shared', []) else 'own')
        # 1 つの名前には 1 つの中身: 取り込む先以外に同じ名前があれば取り込まない（--force でも）。
        # shared に取り込むとき、このリポジトリの own の版は取り込みで消えるので数えない
        here = 'shared' if to == 'shared' else f'repos/{a.repo}'
        others = [loc for loc, name, _ in list_skills()
                  if name == n and loc != here and not (to == 'shared' and loc == f'repos/{a.repo}')]
        if others:
            print(f'  conflict {n}  (the name already exists in {", ".join("skills/" + o for o in others)}. '
                  f'One name, one content: merge the variants or rename the skill (see skill-share))')
            failed += 1
            continue
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
        base[n] = {tree_hash(dest)}
        print(f'  import   {n} -> {os.path.relpath(dest, HUB)}  ({len(changes)} file(s))')
        if to == 'shared':
            users = sorted(r for r, x in cfg['repos'].items() if r != a.repo and n in x.get('shared', []))
            if users:
                print(f'           also distributed to: {", ".join(users)} (on next export)')
    if imported:
        save_cfg(cfg)
        if write_back:
            write_manifest(target, {k: v for k, v in base.items() if k in sources(a.repo, e)})
        print('\nReview with: git -C ~/project/98_skills diff')
        print(f'Then commit in the hub and distribute: uv run src/hub.py export --repo {a.repo}'
              '  (uncommitted hub skills are not exported)')
    return 1 if failed else 0
