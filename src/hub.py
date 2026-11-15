#!/usr/bin/env python3
"""スキルのハブ（~/project/98_skills）の配布・取り込み・検査。

  uv run src/hub.py diff [--repo X] [--here | --path D]     ハブとリポジトリの差分（状態）を表示する。何も書かない（差分があれば exit 1）
  uv run src/hub.py export [--repo X] [--force] [--here | --path D]
                                                             配布する（既定は全リポジトリの作業ツリーすべて）
  uv run src/hub.py import X [skill ...] [--to own|shared] [--force] [--here | --path D | --ref R]
                                                             リポジトリ側（worktree やブランチを含む）の変更・未管理のスキルを取り込む
  uv run src/hub.py register NAME PATH [--shared a,b]        リポジトリを管理下に入れる（登録と pre-commit の設置）
  uv run src/hub.py install-hook NAME... | --all              登録済みのリポジトリに pre-commit を設置する
  uv run src/hub.py uninstall-hook NAME | --path D           pre-commit から skills-hub の部分を取り除く
  uv run src/hub.py check-repo [NAME | --here] [--path D]    リポジトリ側に未取り込みの変更が無いかを見る（pre-commit 用）
  uv run src/hub.py claude-hook                              Claude Code の PostToolUse フックから呼ぶ（常に exit 0）
  uv run src/hub.py check-paths [--no-abs]                   切れたパスと、配布できない絶対パスを検出する
  uv run src/hub.py check-duplicates                         スキルの重複を検出する

終了コード: 0 は問題なし、1 は差分・問題あり、2 はチェックや処理そのものの失敗（claude-hook だけは常に 0）。
各サブコマンドの詳細は --help を見る。
"""
import argparse
import sys

import duplicated_skill
import path_check
import register
import transfer


def main(argv=None):
    ap = argparse.ArgumentParser(prog='src/hub.py', description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True, metavar='{diff,export,import,register,install-hook,uninstall-hook,check-repo,claude-hook,check-paths,check-duplicates}')

    p = sub.add_parser('diff', help='差分（状態）を表示する', description=transfer.SYNC_DOC,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--repo', help='1 リポジトリだけ')
    p.add_argument('--here', action='store_true', help='作業中のディレクトリを含む作業ツリーだけ（--repo は省ける）')
    p.add_argument('--path', help='作業ツリー PATH だけ（省くと、そのリポジトリの作業ツリーすべて）')
    p.set_defaults(func=transfer.cmd_sync, check=True, force=False)

    p = sub.add_parser('export', help='配布する', description=transfer.SYNC_DOC,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--repo', help='1 リポジトリだけ')
    p.add_argument('--force', action='store_true', help='リポジトリ側の変更も上書きする')
    p.add_argument('--here', action='store_true', help='作業中のディレクトリを含む作業ツリーだけに配る（--repo は省ける）')
    p.add_argument('--path', help='作業ツリー PATH だけに配る（省くと、そのリポジトリの作業ツリーすべて）')
    p.set_defaults(func=transfer.cmd_sync, check=False)

    p = sub.add_parser('import', help='取り込む', description=transfer.IMPORT_DOC,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('repo')
    p.add_argument('skills', nargs='*', help='省くと、変更・未管理のスキルをすべて取り込む')
    p.add_argument('--to', choices=['own', 'shared'], help='分類を変えて取り込む（省くと今の分類を保つ）')
    p.add_argument('--force', action='store_true', help='ハブ側も変わっていても取り込む')
    p.add_argument('--here', action='store_true', help='作業中のディレクトリを含む作業ツリーから取り込む')
    p.add_argument('--path', help='作業ツリー PATH から取り込む')
    p.add_argument('--ref', help='ブランチやコミット REF にコミットされている中身から取り込む')
    p.set_defaults(func=transfer.cmd_import)

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

    p = sub.add_parser('uninstall-hook', help='pre-commit から skills-hub の部分を取り除く', description=register.UNINSTALL_DOC,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('name', nargs='?')
    p.add_argument('--path', help='登録を外したリポジトリなど、場所で指定する')
    p.set_defaults(func=register.cmd_uninstall_hook)

    p = sub.add_parser('check-repo', help='リポジトリ側の未取り込みの変更を見る', description=transfer.CHECK_REPO_DOC,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('repo', nargs='?', help='skills/repos.json での名前（省くと --here と同じ）')
    p.add_argument('--here', action='store_true', help='作業中のディレクトリからリポジトリを判定する')
    p.add_argument('--path', help='見る作業ツリー（省くと作業中のディレクトリの作業ツリー）')
    p.add_argument('--default-branch-only', action='store_true',
                   help='既定のブランチ以外では、問題を表示するだけで exit 0（pre-commit 用）')
    p.set_defaults(func=transfer.cmd_check_repo)

    p = sub.add_parser('claude-hook', help='Claude Code の PostToolUse フックから呼ぶ', description=transfer.CLAUDE_HOOK_DOC,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.set_defaults(func=transfer.cmd_claude_hook)

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
