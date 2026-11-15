"""リポジトリを管理下に入れる（uv run src/hub.py register）。"""
import os
import stat
import subprocess
import sys

from common import HUB, SKILLS, list_skills, load_cfg, save_cfg, subdirs, tree_hash

DOC = """リポジトリをハブの管理下に入れる。

  uv run src/hub.py register <名前> <path> [--shared a,b,...]

行うこと:
  1. skills/repos.json に登録する（path はハブのルートからの相対パスで保存する）。
     shared は --shared で指定したもの。加えて、リポジトリの .claude/skills に既にあり、
     skills/shared の同名と内容が同一のスキルは自動で shared に入れる。own は空で始める。
  2. フックを設置する（worktree も含め、そのリポジトリのすべての作業ツリーで効く）。
     pre-commit      .claude/skills の変更をコミットしようとしたとき、ハブに取り込まれていない変更や
                     未管理のスキルを知らせる。止めるのは既定のブランチ（main など）でだけ
                     （check-repo --default-branch-only を呼ぶ。git commit --no-verify で飛ばせる）。
     post-checkout   ブランチを切り替えたとき・worktree を作ったときに、その作業ツリーのスキルがハブと違えば知らせる
                     （配るのは export。自動で書くと未コミットの変更が残り、次の checkout が止まるので書かない）。
     既にフックのファイルがあれば末尾に追記する。core.hooksPath（husky など）や
     .pre-commit-config.yaml があるときは触らず、追記する行を表示する。
  3. 残りの既存スキルの振り分けの一覧を表示する（取り込み・統合は skill-transfer / skill-share で行う）。

配布（export --repo <名前>）はしない。振り分けが済んでから行う。
"""

BEGIN = '# >>> skills-hub >>>'
END = '# <<< skills-hub <<<'


def git(args, cwd):
    r = subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def hook_block(name, hook='pre-commit'):
    if hook == 'post-checkout':
        return f"""{BEGIN}
# skills hub（{HUB}）: ブランチを切り替えたとき・worktree を作ったときに、この作業ツリーのスキルが
# ハブより古ければ知らせる（書き込まない。書き込むと未コミットの変更が残り、次の checkout が止まるため）。
# ハブのツールや uv が無い、ファイルの checkout だけ、rebase・merge・bisect の途中のときは何もしない。
# この部分は uv run src/hub.py install-hook が書き換え、uninstall-hook が消す。
skills_hub="{HUB}"
skills_hub_git="$(git rev-parse --git-dir 2>/dev/null)"
if [ "$3" = 1 ] && [ -f "$skills_hub/src/hub.py" ] && command -v uv >/dev/null 2>&1 \\
   && [ -n "$skills_hub_git" ] && [ ! -d "$skills_hub_git/rebase-merge" ] && [ ! -d "$skills_hub_git/rebase-apply" ] \\
   && [ ! -f "$skills_hub_git/MERGE_HEAD" ] && [ ! -f "$skills_hub_git/BISECT_LOG" ]; then
  skills_hub_tree="$(git rev-parse --show-toplevel)"
  if ! uv run --quiet --project "$skills_hub" "$skills_hub/src/hub.py" diff --repo {name} --path "$skills_hub_tree" >/dev/null 2>&1; then
    echo "skills hub: この作業ツリーのスキルはハブと差がある。" >&2
    echo "  見る: uv run --project $skills_hub $skills_hub/src/hub.py diff --path $skills_hub_tree" >&2
    echo "  配る: uv run --project $skills_hub $skills_hub/src/hub.py export --path $skills_hub_tree" >&2
  fi
fi
{END}
"""
    return f"""{BEGIN}
# skills hub（{HUB}）: .claude/skills の変更がハブに取り込まれているか確かめる。
# 止めるのは既定のブランチ（main など）で、取り込まれていない変更が見つかったとき（exit 1）だけ。
# ほかのブランチでは知らせるだけ（開発中のスキルをコミットできるように）。ハブのツールや uv が無い、
# 確かめられなかった（ハブが別のブランチにある、リポジトリの登録を外したなど）ときは警告してコミットを続ける。
# 今回だけ飛ばすなら git commit --no-verify。この部分は uv run src/hub.py install-hook が書き換え、uninstall-hook が消す。
skills_hub="{HUB}"
if [ -f "$skills_hub/src/hub.py" ] && command -v uv >/dev/null 2>&1 \\
   && git diff --cached --name-only -- .claude/skills | grep -q .; then
  uv run --quiet --project "$skills_hub" "$skills_hub/src/hub.py" check-repo {name} --default-branch-only --path "$(git rev-parse --show-toplevel)"
  skills_hub_rc=$?
  if [ "$skills_hub_rc" -eq 1 ]; then exit 1; fi
  if [ "$skills_hub_rc" -ne 0 ]; then echo "skills hub: 確かめられなかった（exit $skills_hub_rc）。コミットは続ける" >&2; fi
fi
{END}
"""


HOOKS = ('pre-commit', 'post-checkout')


def install_hook(root, name):
    """pre-commit と post-checkout を設置し、何をしたかの説明を返す。"""
    if git(['rev-parse', '--git-dir'], root) is None:
        return 'git リポジトリではないので、フックは設置しない'
    manual = None
    hooks_path = git(['config', '--get', 'core.hooksPath'], root)
    if hooks_path:
        manual = f'core.hooksPath（{hooks_path}）が設定されている（husky など）'
    elif os.path.exists(os.path.join(root, '.pre-commit-config.yaml')):
        manual = '.pre-commit-config.yaml がある（pre-commit install で .git/hooks/pre-commit が作り直される）'
    if manual:
        return (f'{manual}ので、フックは設置しない。そのフックの仕組みの pre-commit と post-checkout に、それぞれ次を追記する:\n\n'
                + '\n'.join(f'--- {h}\n' + hook_block(name, h) for h in HOOKS))
    hooks = git(['rev-parse', '--path-format=absolute', '--git-path', 'hooks'], root)
    return '\n'.join(install_one(hooks, h, hook_block(name, h)) for h in HOOKS)


def install_one(hooks, hook, block):
    path = os.path.join(hooks, hook)
    if os.path.exists(path):
        with open(path) as f:
            text = f.read()
        if BEGIN in text and END in text:
            head, rest = text.split(BEGIN, 1)
            text = head + block.rstrip('\n') + rest.split(END, 1)[1]
            what = f'{path} の skills-hub の部分を書き換えた'
        else:
            text = text.rstrip('\n') + '\n\n' + block
            what = f'{path} の末尾に追記した'
            body = [ln.strip() for ln in text.split(BEGIN)[0].splitlines()]
            if any(ln.startswith('exec ') or ln.startswith('exit') for ln in body):
                what += '（既存の部分に exec か exit があり、追記した部分まで実行されないことがある。確かめる）'
    else:
        os.makedirs(hooks, exist_ok=True)
        text = '#!/bin/sh\n' + block
        what = f'{path} を作った'
    with open(path, 'w') as f:
        f.write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return what


def cmd_register(a):
    cfg = load_cfg()
    if a.name in cfg['repos']:
        print(f'既に登録されている: {a.name}', file=sys.stderr)
        return 2
    root = os.path.realpath(os.path.expanduser(a.path))
    if not os.path.isdir(root):
        print(f'ディレクトリが無い: {a.path}', file=sys.stderr)
        return 2
    if any(os.path.realpath(os.path.join(HUB, e['path'])) == root for e in cfg['repos'].values()
           if not e['path'].startswith('~')):
        print(f'同じ場所が別の名前で登録されている: {a.path}', file=sys.stderr)
        return 2
    shared = [s for s in (a.shared or '').split(',') if s]
    missing = [s for s in shared if not os.path.isdir(os.path.join(SKILLS, 'shared', s))]
    if missing:
        print(f'skills/shared に無い: {", ".join(missing)}', file=sys.stderr)
        return 2

    target = os.path.join(root, '.claude', 'skills')
    existing = subdirs(target)
    auto = [n for n in existing if n not in shared
            and tree_hash(os.path.join(SKILLS, 'shared', n)) == tree_hash(os.path.join(target, n))]
    rel = os.path.relpath(root, HUB)
    cfg['repos'][a.name] = {'path': rel, 'shared': shared + auto, 'own': []}
    save_cfg(cfg)
    print(f'== 登録: {a.name}（path: {rel}）')
    print(f'  shared  {len(shared + auto)} 件（指定 {len(shared)} 件、既存と同一で自動 {len(auto)} 件'
          f'{": " + ", ".join(auto) if auto else ""}）')

    print('== フック（pre-commit、post-checkout）')
    print('  ' + install_hook(root, a.name).replace('\n', '\n  '))

    rest = [n for n in existing if n not in shared + auto]
    print('== 既存スキルの振り分け（skill-transfer / skill-share で行う）')
    if not rest:
        print('  なし')
    where = {}
    for loc, n, _ in list_skills():
        where.setdefault(n, []).append(loc)
    for n in rest:
        locs = where.get(n, [])
        if 'shared' in locs:
            print(f'  {n}: skills/shared/{n} と中身が違う。skill-share で統合するか、別の名前に分ける'
                  '（同じ名前のまま own にはできない）')
        elif locs:
            print(f'  {n}: {", ".join("skills/" + l for l in locs)} と同名。skill-share で統合・共通化するか、'
                  '別の名前に分ける（同じ名前のまま own にはできない）')
        else:
            print(f'  {n}: ハブに無い。own にするなら uv run src/hub.py import {a.name} {n}')
    print('\n次: 振り分けが済んだら uv run src/hub.py export --repo ' + a.name +
          ' で配布し、リポジトリ側で .claude/skills と .hub-manifest をコミットする')
    return 0


INSTALL_DOC = """登録済みのリポジトリに pre-commit と post-checkout を設置する（register と同じ設置の規則）。

  uv run src/hub.py install-hook <名前> [<名前> ...]
  uv run src/hub.py install-hook --all            skills/repos.json のすべてのリポジトリ

既に設置してあれば、skills-hub の部分だけを書き換える（何度実行してもよい）。
"""


def cmd_install_hook(a):
    from common import repo_root
    cfg = load_cfg()['repos']
    names = sorted(cfg) if a.all else a.names
    if not names:
        print('名前か --all を指定する', file=sys.stderr)
        return 2
    unknown = [n for n in names if n not in cfg]
    if unknown:
        print(f'unknown repo: {", ".join(unknown)}', file=sys.stderr)
        return 2
    manual = 0
    for n in names:
        e = cfg[n]
        if e['path'].startswith('~') or not os.path.isdir(repo_root(e)):
            print(f'== {n}\n  リポジトリが無いので飛ばした（{e["path"]}）')
            continue
        msg = install_hook(repo_root(e), n)
        print(f'== {n}\n  ' + msg.replace('\n', '\n  '))
        if 'フックは設置しない。' in msg:
            manual += 1
    return 1 if manual else 0


UNINSTALL_DOC = """pre-commit と post-checkout から skills-hub の部分を取り除く（管理から外したリポジトリの後始末）。

  uv run src/hub.py uninstall-hook <名前>        skills/repos.json に登録されているリポジトリ
  uv run src/hub.py uninstall-hook --path <dir>  登録を外したリポジトリなど、場所で指定する

取り除いた後に shebang しか残らなければ、ファイルごと消す。core.hooksPath や .pre-commit-config.yaml の
仕組みに自分で足した行は対象外（それぞれの設定から手で消す）。
"""


def remove_hook(root):
    if git(['rev-parse', '--git-dir'], root) is None:
        return 'git リポジトリではないので、何もしない'
    hooks = git(['rev-parse', '--path-format=absolute', '--git-path', 'hooks'], root)
    return '\n'.join(remove_one(os.path.join(hooks, h)) for h in HOOKS)


def remove_one(path):
    if not os.path.exists(path):
        return f'{path} が無い'
    with open(path) as f:
        text = f.read()
    if BEGIN not in text or END not in text:
        return f'{path} に skills-hub の部分が無い'
    head, rest = text.split(BEGIN, 1)
    text = (head.rstrip('\n') + '\n' + rest.split(END, 1)[1].lstrip('\n')).rstrip('\n') + '\n'
    if text.strip() in ('', '#!/bin/sh', '#!/bin/bash', '#!/usr/bin/env sh', '#!/usr/bin/env bash'):
        os.remove(path)
        return f'{path} を消した（skills-hub の部分しか無かった）'
    with open(path, 'w') as f:
        f.write(text)
    return f'{path} から skills-hub の部分を取り除いた'


def cmd_uninstall_hook(a):
    from common import repo_root
    if a.path:
        root = os.path.realpath(os.path.expanduser(a.path))
        label = a.path
    else:
        cfg = load_cfg()['repos']
        if not a.name or a.name not in cfg:
            print(f'unknown repo: {a.name}（登録を外したリポジトリは --path で指定する）', file=sys.stderr)
            return 2
        root, label = repo_root(cfg[a.name]), a.name
    if not os.path.isdir(root):
        print(f'ディレクトリが無い: {label}', file=sys.stderr)
        return 2
    print(f'== {label}\n  ' + remove_hook(root).replace('\n', '\n  '))
    return 0
