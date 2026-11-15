"""ハブのツールで共通に使うもの: 場所、設定（skills/repos.json）、スキルの一覧、ファイルの一覧とハッシュ。

配布（sync.py）と検査（path_check.py、duplicated_skill.py）が同じ規則を使うように、ここにまとめる。
"""
import filecmp
import hashlib
import json
import os
import shutil

HUB = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))   # シンボリックリンクを解決した場所
SKILLS = os.path.join(HUB, 'skills')            # global/ shared/ repos/ と repos.json を置く場所
CONFIG = os.path.join(SKILLS, 'repos.json')     # 中の path はハブのルートからの相対パス
USER_SKILLS = os.path.expanduser(os.environ.get('SKILLS_HUB_USER_DIR', '~/.claude/skills'))
IGN = {'.DS_Store', '__pycache__'}              # 配布・比較のどちらでも無視するもの
MANIFEST = '.hub-manifest'


# ---------- config ----------

def load_cfg():
    with open(CONFIG) as f:
        return json.load(f)


def save_cfg(cfg):
    for e in cfg['repos'].values():
        e['shared'] = sorted(set(e.get('shared', [])))
        e['own'] = sorted(set(e.get('own', [])))
    with open(CONFIG, 'w') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write('\n')


def repo_dir(path):
    """repos.json の path を解決する（絶対パスか、ハブのルートからの相対パス。~ は展開しない）。"""
    return path if path.startswith('/') else os.path.join(HUB, path)


def repo_root(e):
    return os.path.normpath(repo_dir(e['path']))


def sources(repo, e):
    """{スキル名: ハブ側の場所} を返す。"""
    srcs = {s: os.path.join(SKILLS, 'shared', s) for s in e.get('shared', [])}
    for s in e.get('own', []):
        srcs[s] = os.path.join(SKILLS, 'repos', repo, s)
    return srcs


# ---------- skills ----------

def subdirs(d):
    """d の直下のディレクトリ名（隠しファイルと IGN を除く）を名前順で返す。"""
    if not os.path.isdir(d):
        return []
    return sorted(n for n in os.listdir(d)
                  if not n.startswith('.') and n not in IGN and os.path.isdir(os.path.join(d, n)))


def list_skills():
    """ハブのスキルを [(場所, 名前, パス)] で返す。場所は 'global' / 'shared' / 'repos/<repo>'。"""
    out = []
    for layer in ('global', 'shared'):
        base = os.path.join(SKILLS, layer)
        if not os.path.isdir(base):
            raise RuntimeError(f'{os.path.relpath(base, HUB)} が無い')
        out += [(layer, n, os.path.join(base, n)) for n in subdirs(base)]
    base = os.path.join(SKILLS, 'repos')
    if not os.path.isdir(base):
        raise RuntimeError(f'{os.path.relpath(base, HUB)} が無い')
    for r in subdirs(base):
        out += [(f'repos/{r}', n, os.path.join(base, r, n)) for n in subdirs(os.path.join(base, r))]
    return out


# ---------- files ----------

def files(d):
    """{d からの相対パス: 実際のパス}。IGN は除く。"""
    out = {}
    for root, dirs, fs in os.walk(d):
        dirs[:] = [x for x in dirs if x not in IGN]
        for f in fs:
            if f not in IGN:
                p = os.path.join(root, f)
                out[os.path.relpath(p, d)] = p
    return out


def tree_hash(d):
    """スキルのディレクトリのハッシュ（全ファイルの相対パスと中身）。無ければ None。"""
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
    """dst を src と同じにする（IGN は無視）。変更の一覧 [(種類, パス)] を返す。"""
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
