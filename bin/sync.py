#!/usr/bin/env python3
"""Skills hub: distribute skills to repos and import repo-side changes back.

  global/          -> ~/.claude/skills/<name>   (symlink, every project)
  shared/          -> <repo>/.claude/skills     (copy, skills listed in repos.json "shared")
  repos/<repo>/    -> <repo>/.claude/skills     (copy, skills listed in repos.json "own")

Usage:
  bin/sync.py                        distribute (skills changed in the repo are skipped)
  bin/sync.py --check                report state only, exit 1 if anything differs
  bin/sync.py --repo X               limit to one repo
  bin/sync.py --force                distribute even over repo-side changes
  bin/sync.py import X               import every repo-side change / unmanaged skill of repo X
  bin/sync.py import X a b           import only skills a and b (each keeps its shared/own classification)
  bin/sync.py import X a --to shared import into shared/ (affects every repo using it)
  bin/sync.py import X a --to own    import into repos/X/ (stops sharing it for repo X)
  bin/sync.py import X a --force     import even if the hub side also changed

Each repo's .claude/skills/.hub-manifest records the hash of every skill as last
distributed. Comparing hub, repo and that baseline tells which side changed:
  new       not in the repo yet       -> sync copies it
  same      identical                 -> nothing to do (not shown by --check)
  hub       only the hub changed      -> sync updates the repo (import only with --to own, to unshare)
  repo      only the repo changed     -> sync skips it, import brings it into the hub
  both      both changed              -> sync and import refuse without --force
  unknown   no baseline recorded      -> sync and import refuse without --force
  unmanaged only in the repo          -> import brings it in as the repo's own skill
"""
import argparse, filecmp, hashlib, json, os, shutil, sys

HUB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IGN = {'.DS_Store', '__pycache__'}
MANIFEST = '.hub-manifest'
USER_SKILLS = os.path.expanduser(os.environ.get('SKILLS_HUB_USER_DIR', '~/.claude/skills'))
CONFIG = os.path.join(HUB, 'repos.json')


# ---------- file helpers ----------

def files(d):
    out = {}
    for root, dirs, fs in os.walk(d):
        dirs[:] = [x for x in dirs if x not in IGN]
        for f in fs:
            if f not in IGN:
                p = os.path.join(root, f)
                out[os.path.relpath(p, d)] = p
    return out

def tree_hash(d):
    if not os.path.isdir(d):
        return None
    h = hashlib.sha256()
    for k, p in sorted(files(d).items()):
        h.update(k.encode() + b'\0')
        with open(p, 'rb') as f:
            h.update(f.read())
        h.update(b'\0')
    return h.hexdigest()[:16]

def mirror(src, dst, write):
    """Make dst identical to src (ignoring IGN). Return list of (kind, path)."""
    s, d = files(src), files(dst) if os.path.isdir(dst) else {}
    changes = []
    for k, p in s.items():
        if k not in d or not filecmp.cmp(p, d[k], shallow=False):
            changes.append(('update' if k in d else 'add', os.path.join(dst, k)))
            if write:
                os.makedirs(os.path.dirname(os.path.join(dst, k)), exist_ok=True)
                shutil.copy2(p, os.path.join(dst, k))
    for k in d.keys() - s.keys():
        changes.append(('remove', d[k]))
        if write:
            os.remove(d[k])
    return changes


# ---------- manifest (baseline) ----------

def read_manifest(target):
    """Return {name: hash or None}. Old manifests without hashes give None."""
    path = os.path.join(target, MANIFEST)
    out = {}
    if os.path.exists(path):
        for line in open(path):
            line = line.rstrip('\n')
            if not line or line.startswith('#'):
                continue
            name, _, h = line.partition('\t')
            out[name] = h or None
    return out

def write_manifest(target, base):
    text = ('# Managed by the skills hub (~/project/98_skills). Do not edit these skills here.\n'
            '# Edit the hub copy and run: ~/project/98_skills/bin/sync.py\n'
            '# Changed one here anyway? Run: ~/project/98_skills/bin/sync.py import <repo>\n'
            + ''.join(f'{n}\t{base[n] or ""}\n' for n in sorted(base)))
    path = os.path.join(target, MANIFEST)
    if os.path.exists(path) and open(path).read() == text:
        return False
    os.makedirs(target, exist_ok=True)
    open(path, 'w').write(text)
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


# ---------- config ----------

def load_cfg():
    return json.load(open(CONFIG))

def save_cfg(cfg):
    for e in cfg['repos'].values():
        e['shared'] = sorted(set(e.get('shared', [])))
        e['own'] = sorted(set(e.get('own', [])))
    with open(CONFIG, 'w') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write('\n')

def repo_root(e):
    return os.path.normpath(os.path.join(HUB, e['path']))

def sources(repo, e):
    srcs = {s: os.path.join(HUB, 'shared', s) for s in e.get('shared', [])}
    for s in e.get('own', []):
        srcs[s] = os.path.join(HUB, 'repos', repo, s)
    return srcs


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
            hint = {'repo': f'changed in repo. Run: sync.py import {repo} {name}',
                    'both': 'changed in both hub and repo. Resolve, then use --force',
                    'unknown': 'differs and no baseline. Import it or use --force'}[state]
            print(f'  {state:8} {name}  ({hint})')
            continue
        changes = mirror(src, dst, write=not check)
        print(f'  {state:8} {name}  ({len(changes)} file(s){" to write" if check else " written"})')
        new_base[name] = hs
    existing = {n for n in os.listdir(target) if os.path.isdir(os.path.join(target, n))} if os.path.isdir(target) else set()
    unmanaged = sorted(existing - srcs.keys())
    if unmanaged:
        print(f'  unmanaged {", ".join(unmanaged)}  (only in repo. Run: sync.py import {repo} <name>)')
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
    gdir = os.path.join(HUB, 'global')
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
            print(f'  conflict  {link} is a real directory. Move it into hub/global first.')
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
            print(f'  unmanaged {p} (move it into hub/global)')
            drift += 1
    return drift

def cmd_sync(a):
    cfg = load_cfg()['repos']
    if a.repo and a.repo not in cfg:
        sys.exit(f'unknown repo: {a.repo}')
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
    sys.exit(1 if total else 0)


# ---------- import ----------

def cmd_import(a):
    cfg = load_cfg()
    if a.repo not in cfg['repos']:
        sys.exit(f'unknown repo: {a.repo}')
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
            return

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
            dest = os.path.join(HUB, 'repos', a.repo, n)
            e['shared'] = [x for x in e.get('shared', []) if x != n]
            e.setdefault('own', []).append(n)
        else:
            dest = os.path.join(HUB, 'shared', n)
            # 別の内容の shared/<n> が既にあるのに、このリポジトリの版で黙って上書きしない（統合は skill-share の手順で）
            if (n not in e.get('shared', []) and os.path.isdir(dest)
                    and tree_hash(dest) != tree_hash(dst) and not a.force):
                print(f'  conflict {n}  (shared/{n} already exists with different content. '
                      f'Merge the variants first, or use --force to overwrite it with this repo\'s copy)')
                failed += 1
                continue
            e['own'] = [x for x in e.get('own', []) if x != n]
            e.setdefault('shared', []).append(n)
            stale = os.path.join(HUB, 'repos', a.repo, n)
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
    sys.exit(1 if failed else 0)


# ---------- entry ----------

def main():
    if len(sys.argv) > 1 and sys.argv[1] == 'import':
        ap = argparse.ArgumentParser(prog='sync.py import')
        ap.add_argument('repo')
        ap.add_argument('skills', nargs='*')
        ap.add_argument('--to', choices=['own', 'shared'])
        ap.add_argument('--force', action='store_true')
        cmd_import(ap.parse_args(sys.argv[2:]))
    else:
        ap = argparse.ArgumentParser(prog='sync.py')
        ap.add_argument('--check', action='store_true')
        ap.add_argument('--repo')
        ap.add_argument('--force', action='store_true')
        cmd_sync(ap.parse_args())

if __name__ == '__main__':
    main()
