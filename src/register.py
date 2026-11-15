"""リポジトリを管理下に入れる（uv run src/hub.py register）。"""
import os
import stat
import subprocess
import sys

from common import HUB, SKILLS, load_cfg, save_cfg, subdirs, tree_hash

DOC = """リポジトリをハブの管理下に入れる。

  uv run src/hub.py register <名前> <path> [--shared a,b,...]

行うこと:
  1. skills/repos.json に登録する（path はハブのルートからの相対パスで保存する）。
     shared は --shared で指定したもの。加えて、リポジトリの .claude/skills に既にあり、
     skills/shared の同名と内容が同一のスキルは自動で shared に入れる。own は空で始める。
  2. pre-commit を設置する。.claude/skills の変更をコミットしようとしたとき、ハブに取り込まれていない
     変更や未管理のスキルがあれば止める（check-repo を呼ぶ。git commit --no-verify で飛ばせる）。
     既に .git/hooks/pre-commit があれば末尾に追記する。core.hooksPath（husky など）や
     .pre-commit-config.yaml があるときは触らず、追記する行を表示する。
  3. 残りの既存スキルの振り分けの一覧を表示する（取り込み・統合は skill-sync / skill-share で行う）。

配布（sync --repo <名前>）はしない。振り分けが済んでから行う。
"""

BEGIN = '# >>> skills-hub >>>'
END = '# <<< skills-hub <<<'


def git(args, cwd):
    r = subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def hook_block(name):
    return f"""{BEGIN}
# skills hub（{HUB}）: .claude/skills の変更がハブに取り込まれているか確かめる。
# 止めるのは取り込まれていない変更が見つかったとき（exit 1）だけ。ハブのツールや uv が無い、
# 確かめられなかった（ハブが別のブランチにある、リポジトリの登録を外したなど）ときは警告してコミットを続ける。
# 今回だけ飛ばすなら git commit --no-verify。この部分は uv run src/hub.py install-hook が書き換え、uninstall-hook が消す。
skills_hub="{HUB}"
if [ -f "$skills_hub/src/hub.py" ] && command -v uv >/dev/null 2>&1 \\
   && git diff --cached --name-only -- .claude/skills | grep -q .; then
  uv run --quiet --project "$skills_hub" "$skills_hub/src/hub.py" check-repo {name} --path "$(git rev-parse --show-toplevel)"
  skills_hub_rc=$?
  if [ "$skills_hub_rc" -eq 1 ]; then exit 1; fi
  if [ "$skills_hub_rc" -ne 0 ]; then echo "skills hub: 確かめられなかった（exit $skills_hub_rc）。コミットは続ける" >&2; fi
fi
{END}
"""


def install_hook(root, name):
    """pre-commit を設置し、何をしたかの説明を返す。"""
    if git(['rev-parse', '--git-dir'], root) is None:
        return 'git リポジトリではないので、pre-commit は設置しない'
    block = hook_block(name)
    manual = None
    hooks_path = git(['config', '--get', 'core.hooksPath'], root)
    if hooks_path:
        manual = f'core.hooksPath（{hooks_path}）が設定されている（husky など）'
    elif os.path.exists(os.path.join(root, '.pre-commit-config.yaml')):
        manual = '.pre-commit-config.yaml がある（pre-commit install で .git/hooks/pre-commit が作り直される）'
    if manual:
        return (f'{manual}ので、pre-commit は設置しない。そのフックの仕組みの pre-commit に、次を追記する:\n\n'
                + block)
    hooks = git(['rev-parse', '--path-format=absolute', '--git-path', 'hooks'], root)
    path = os.path.join(hooks, 'pre-commit')
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

    print('== pre-commit')
    print('  ' + install_hook(root, a.name).replace('\n', '\n  '))

    rest = [n for n in existing if n not in shared + auto]
    print('== 既存スキルの振り分け（skill-sync / skill-share で行う）')
    if not rest:
        print('  なし')
    for n in rest:
        if os.path.isdir(os.path.join(SKILLS, 'shared', n)):
            print(f'  {n}: skills/shared/{n} の改変版。skill-share で統合するか、own にするかを決める')
        elif any(os.path.isdir(os.path.join(SKILLS, 'repos', r, n)) for r in subdirs(os.path.join(SKILLS, 'repos'))):
            print(f'  {n}: 他のリポジトリの own と同名。skill-share で共通化するか、own にするかを決める')
        else:
            print(f'  {n}: ハブに無い。own にするなら uv run src/hub.py import {a.name} {n}')
    print('\n次: 振り分けが済んだら uv run src/hub.py sync --repo ' + a.name +
          ' で配布し、リポジトリ側で .claude/skills と .hub-manifest をコミットする')
    return 0


INSTALL_DOC = """登録済みのリポジトリに pre-commit を設置する（register と同じ設置の規則）。

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
        if 'pre-commit は設置しない。' in msg:
            manual += 1
    return 1 if manual else 0


UNINSTALL_DOC = """pre-commit から skills-hub の部分を取り除く（管理から外したリポジトリの後始末）。

  uv run src/hub.py uninstall-hook <名前>        skills/repos.json に登録されているリポジトリ
  uv run src/hub.py uninstall-hook --path <dir>  登録を外したリポジトリなど、場所で指定する

取り除いた後に shebang しか残らなければ、ファイルごと消す。core.hooksPath や .pre-commit-config.yaml の
仕組みに自分で足した行は対象外（それぞれの設定から手で消す）。
"""


def remove_hook(root):
    if git(['rev-parse', '--git-dir'], root) is None:
        return 'git リポジトリではないので、何もしない'
    hooks = git(['rev-parse', '--path-format=absolute', '--git-path', 'hooks'], root)
    path = os.path.join(hooks, 'pre-commit')
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
    print(f'== {label}\n  ' + remove_hook(root))
    return 0
