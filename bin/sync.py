#!/usr/bin/env python3
"""Distribute skills from this hub (the single source of truth).

  global/          -> ~/.claude/skills/<name>   (symlink, every project)
  shared/          -> <repo>/.claude/skills     (copy, skills listed in repos.json "shared")
  repos/<repo>/    -> <repo>/.claude/skills     (copy, repo-specific or customized skills)
  codex/           -> <repo>/.agents/skills     (copy, repos with "codex": true)

Usage:
  bin/sync.py            write changes
  bin/sync.py --check    report drift only, exit 1 if anything differs
  bin/sync.py --repo X   limit to one repo
Never edit the copies in a repo. Edit here, then run sync.
"""
import argparse, filecmp, json, os, shutil, sys

HUB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IGN = {'.DS_Store', '__pycache__'}
MANIFEST = '.hub-manifest'
USER_SKILLS = os.path.expanduser('~/.claude/skills')

def files(d):
    out = {}
    for root, dirs, fs in os.walk(d):
        dirs[:] = [x for x in dirs if x not in IGN]
        for f in fs:
            if f not in IGN:
                p = os.path.join(root, f)
                out[os.path.relpath(p, d)] = p
    return out

def mirror(src, dst, check):
    """Make dst identical to src (ignoring IGN). Return list of changed paths."""
    s, d = files(src), files(dst) if os.path.isdir(dst) else {}
    changes = []
    for k, p in s.items():
        if k not in d or not filecmp.cmp(p, d[k], shallow=False):
            changes.append(('update' if k in d else 'add', os.path.join(dst, k)))
            if not check:
                os.makedirs(os.path.dirname(os.path.join(dst, k)), exist_ok=True)
                shutil.copy2(p, os.path.join(dst, k))
    for k in d.keys() - s.keys():
        changes.append(('remove', d[k]))
        if not check:
            os.remove(d[k])
    return changes

def manifest_text(names):
    return ('# Managed by the skills hub (~/project/98_skills). Do not edit these skills here.\n'
            '# Edit the hub copy and run: ~/project/98_skills/bin/sync.py\n' + ''.join(n + '\n' for n in names))

def sync_dir(target, sources, check, label):
    drift = []
    for name, src in sources.items():
        drift += mirror(src, os.path.join(target, name), check)
    existing = {n for n in os.listdir(target) if os.path.isdir(os.path.join(target, n))} if os.path.isdir(target) else set()
    unmanaged = sorted(existing - sources.keys())
    mpath = os.path.join(target, MANIFEST)
    want = manifest_text(sorted(sources))
    if not os.path.exists(mpath) or open(mpath).read() != want:
        drift.append(('manifest', mpath))
        if not check:
            os.makedirs(target, exist_ok=True)
            open(mpath, 'w').write(want)
    for kind, path in drift:
        print(f'  [{label}] {kind:8} {path}')
    if unmanaged:
        print(f'  [{label}] unmanaged (exists only in repo, not in hub): {", ".join(unmanaged)}')
    return drift, unmanaged

def sync_global(check):
    drift = []
    gdir = os.path.join(HUB, 'global')
    os.makedirs(USER_SKILLS, exist_ok=True)
    for name in sorted(os.listdir(gdir)):
        src = os.path.join(gdir, name)
        if not os.path.isdir(src):
            continue
        link = os.path.join(USER_SKILLS, name)
        if os.path.islink(link) and os.path.realpath(link) == os.path.realpath(src):
            continue
        if os.path.exists(link) and not os.path.islink(link):
            print(f'  [global] CONFLICT  {link} is a real directory. Move it into the hub first.')
            drift.append(('conflict', link))
            continue
        drift.append(('link', link))
        print(f'  [global] link     {link} -> {src}')
        if not check:
            if os.path.islink(link):
                os.remove(link)
            os.symlink(src, link)
    for name in sorted(os.listdir(USER_SKILLS)):
        p = os.path.join(USER_SKILLS, name)
        if os.path.islink(p) and not os.path.exists(p):
            print(f'  [global] broken link {p} -> {os.readlink(p)}')
            drift.append(('broken', p))
        elif os.path.isdir(p) and not os.path.islink(p) and name not in ('synced', 'learned'):
            print(f'  [global] unmanaged real directory {p} (move it into hub/global)')
            drift.append(('unmanaged', p))
    return drift

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--repo')
    a = ap.parse_args()
    cfg = json.load(open(os.path.join(HUB, 'repos.json')))['repos']
    total = 0
    if not a.repo:
        print('== global (~/.claude/skills)')
        total += len(sync_global(a.check))
    for repo, e in cfg.items():
        if a.repo and repo != a.repo:
            continue
        root = os.path.normpath(os.path.join(HUB, e['path']))
        print(f'== {repo} ({root})')
        if not os.path.isdir(root):
            print('  missing repo, skipped'); continue
        srcs = {s: os.path.join(HUB, 'shared', s) for s in e.get('shared', [])}
        for s in e.get('own', []):
            srcs[s] = os.path.join(HUB, 'repos', repo, s)
        missing = [s for s, p in srcs.items() if not os.path.isdir(p)]
        if missing:
            print(f'  ERROR hub has no source for: {missing}'); total += 1; continue
        d, _ = sync_dir(os.path.join(root, '.claude', 'skills'), srcs, a.check, '.claude')
        total += len(d)
        if e.get('codex'):
            cdir = os.path.join(HUB, 'codex')
            csrc = {s: os.path.join(cdir, s) for s in sorted(os.listdir(cdir)) if os.path.isdir(os.path.join(cdir, s))}
            d, _ = sync_dir(os.path.join(root, '.agents', 'skills'), csrc, a.check, '.agents')
            total += len(d)
    print(f'\n{"drift" if a.check else "changes"}: {total}')
    sys.exit(1 if (a.check and total) else 0)

if __name__ == '__main__':
    main()
