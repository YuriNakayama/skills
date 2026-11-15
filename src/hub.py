#!/usr/bin/env python3
"""スキルのハブ（~/project/98_skills）の配布・取り込み・検査。

  uv run src/hub.py sync [--check] [--repo X] [--force]      配布する（--check は状態を見るだけ）
  uv run src/hub.py import X [skill ...] [--to own|shared] [--force]
                                                             リポジトリ側の変更・未管理のスキルを取り込む
  uv run src/hub.py register NAME PATH [--shared a,b]        リポジトリを管理下に入れる（登録と pre-commit の設置）
  uv run src/hub.py install-hook NAME... | --all              登録済みのリポジトリに pre-commit を設置する
  uv run src/hub.py check-repo [NAME | --here] [--path D]    リポジトリ側に未取り込みの変更が無いかを見る（pre-commit 用）
  uv run src/hub.py claude-hook                              Claude Code の PostToolUse フックから呼ぶ（--here の判定）
  uv run src/hub.py check-paths [--no-abs]                   切れたパスと、配布できない絶対パスを検出する
  uv run src/hub.py check-duplicates                         スキルの重複を検出する

終了コード: 0 は問題なし、1 は差分・問題あり、2 はチェックや処理そのものの失敗。
各サブコマンドの詳細は --help を見る。
"""
import argparse
import sys

import duplicated_skill
import path_check
import register
import sync


def main(argv=None):
    ap = argparse.ArgumentParser(prog='src/hub.py', description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True, metavar='{sync,import,register,install-hook,check-repo,claude-hook,check-paths,check-duplicates}')

    p = sub.add_parser('sync', help='配布する', description=sync.SYNC_DOC,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--check', action='store_true', help='状態を表示するだけ（ずれがあれば exit 1）')
    p.add_argument('--repo', help='1 リポジトリだけ')
    p.add_argument('--force', action='store_true', help='リポジトリ側の変更も上書きする')
    p.set_defaults(func=sync.cmd_sync)

    p = sub.add_parser('import', help='取り込む', description=sync.IMPORT_DOC,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('repo')
    p.add_argument('skills', nargs='*', help='省くと、変更・未管理のスキルをすべて取り込む')
    p.add_argument('--to', choices=['own', 'shared'], help='分類を変えて取り込む（省くと今の分類を保つ）')
    p.add_argument('--force', action='store_true', help='ハブ側も変わっていても取り込む')
    p.set_defaults(func=sync.cmd_import)

    p = sub.add_parser('register', help='リポジトリを管理下に入れる', description=register.DOC,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('name', help='skills/repos.json での名前')
    p.add_argument('path', help='リポジトリの場所（絶対パスか、今いる場所からの相対パス）')
    p.add_argument('--shared', help='配る shared スキル（カンマ区切り）')
    p.set_defaults(func=register.cmd_register)

    p = sub.add_parser('install-hook', help='登録済みのリポジトリに pre-commit を設置する', description=register.INSTALL_DOC,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('names', nargs='*', metavar='name')
    p.add_argument('--all', action='store_true', help='skills/repos.json のすべてのリポジトリ')
    p.set_defaults(func=register.cmd_install_hook)

    p = sub.add_parser('check-repo', help='リポジトリ側の未取り込みの変更を見る', description=sync.CHECK_REPO_DOC,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('repo', nargs='?', help='skills/repos.json での名前（省くと --here と同じ）')
    p.add_argument('--here', action='store_true', help='作業中のディレクトリからリポジトリを判定する')
    p.add_argument('--path', help='見る作業ツリー（省くと作業中のディレクトリの作業ツリー）')
    p.set_defaults(func=sync.cmd_check_repo)

    p = sub.add_parser('claude-hook', help='Claude Code の PostToolUse フックから呼ぶ', description=sync.CLAUDE_HOOK_DOC,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.set_defaults(func=sync.cmd_claude_hook)

    p = sub.add_parser('check-paths', help='パスを検査する', description=path_check.DOC,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--no-abs', action='store_true', help='ファイル中の絶対パスの検査を省く')
    p.set_defaults(func=path_check.main)

    p = sub.add_parser('check-duplicates', help='スキルの重複を検査する', description=duplicated_skill.DOC,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.set_defaults(func=duplicated_skill.main)

    a = ap.parse_args(argv)
    try:
        return a.func(a)
    except KeyboardInterrupt:
        return 130
    except Exception as e:      # 処理そのものの失敗
        print(f'失敗: {e}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
