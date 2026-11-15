"""切れたパスと、配布できない絶対パスの検査（uv run src/hub.py check-paths）。"""
import json
import os
import re
import subprocess
import sys

from common import CONFIG, HUB, USER_SKILLS, repo_dir

DOC = """ハブ内の切れたパスと、配布できない絶対パスを検出する。

  uv run src/hub.py check-paths            全チェック（問題があれば exit 1、チェック自体が失敗したら exit 2）
  uv run src/hub.py check-paths --no-abs   ファイル中の絶対パスのチェックを省く

チェック内容:
  repos     skills/repos.json の path が存在するか、shared/own のスキルがハブにあるか、
            skills/repos/<repo>/ 配下が repos.json と一致しているか、skills/shared/ に誰も使わないスキルが無いか
  symlink   ハブ・~/.claude/skills・各リポジトリの .claude/skills の切れたシンボリックリンク
  link      Markdown の相対リンク [text](path) と参照定義 [id]: path の参照先が存在するか
            （フェンスで囲んだコードブロック、インラインコード、脚注は除く）
  abs       ファイル中の絶対パス。
            - skills/shared/ と skills/repos/（リポジトリへコピー配布するスキル）: プロジェクト置き場（ハブの親、
              通常 ~/project）のパス（~/project、$HOME/project、${HOME}/project、/Users/<name>/project の形）と、
              /Users/<name>・/home/<name>/ で始まるパスは、存在しても不可。
              書き方は skills/global/skill-share/references/portability.md。
              例示（<branch> など）が続いても、手前が具体的な絶対パスなので不可。
              例外（許可リスト）は無い。直すまでそのスキルは配布できない。
            - それ以外（skills/global/、src/、README など）: プロジェクト置き場のパスが存在するか。
              無くても、それを含む git リポジトリ（ハブ以外）があれば、実行時に作られるパス（.dvc/cache、data/ など）とみなして通す。
            - 配布物以外では、例示（<...>、...、{...}、$VAR、* を含むもの）は例示の手前のディレクトリまでを確かめる。
              パス末尾の * は Markdown の強調とみなして外す（~/project/x* は ~/project/x として確かめる）。
            - *-workspace/ スキル（eval 記録）は対象外。
            - 検出しないもの: ../<別のリポジトリ> のような相対パスでの外部参照、/home/<name>（末尾の / が無いもの）、
              英数字に続く絶対パス（foo/Users/... は別の語とみなす。-I/Users/... のような短いオプションは検出する）。
            - /home/<name>/ の形は Web のパスなども拾う。${VAR}/home/... と $(cmd)/home/... は拾わない。
              <repo>/home/x/ のような例示の直後は、HTML タグ（<code>/Users/...）と見分けられないので拾う。
"""

SELF = 'src/path_check.py'      # 自分自身は abs の検査から外す（例示や正規表現を含むため）

PC = set('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-~/+@%=<>{}$*')   # パスとして切り出す文字
WC = set('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.')                # 手前にあると別の語の一部とみなす文字


class Fail(Exception):
    """チェック自体の失敗（exit 2）。"""


def ispc(c):
    return c != '' and c in PC


def iswc(c):
    return c != '' and c in WC


def char(line, i):
    """0 始まりの位置 i の文字（範囲外なら ''）。"""
    return line[i] if 0 <= i < len(line) else ''


# ---------- 対象ファイル ----------

def tracked_files():
    """git 管理下 + 未追跡で ignore されていないファイルのうち、実在する通常ファイル（ハブからの相対パス）。"""
    r = subprocess.run(['git', 'ls-files', '-co', '--exclude-standard', '-z'], cwd=HUB, capture_output=True)
    if r.returncode != 0:
        raise Fail('git ls-files に失敗')
    out = []
    for f in r.stdout.decode('utf-8', 'surrogateescape').split('\0'):
        p = os.path.join(HUB, f)
        if f and os.path.isfile(p) and not os.path.islink(p):
            out.append(f)
    return out


def read_text(f):
    with open(os.path.join(HUB, f), 'rb') as fh:
        data = fh.read()
    return data, data.decode('utf-8', 'surrogateescape')


# ---------- repos ----------

def check_repos(cfg, err):
    print('== skills/repos.json')
    repos = cfg.get('repos', {})
    for repo in sorted(repos):
        e = repos[repo]
        rpath = e.get('path', '')
        if rpath.startswith('~'):
            err('repos', f'repos.json:{repo}', f'path に ~ は使えない（sync.py は展開しない）: {rpath}')
        elif not os.path.isdir(repo_dir(rpath)):
            err('repos', f'repos.json:{repo}', f'path が存在しない: {rpath}')
        for s in e.get('shared') or []:
            if not os.path.isdir(os.path.join(HUB, 'skills/shared', s)):
                err('repos', f'repos.json:{repo}', f'skills/shared/{s} が存在しない')
        for s in e.get('own') or []:
            if not os.path.isdir(os.path.join(HUB, 'skills/repos', repo, s)):
                err('repos', f'repos.json:{repo}', f'skills/repos/{repo}/{s} が存在しない')
            if s in (e.get('shared') or []):
                err('repos', f'repos.json:{repo}', f'{s} が shared と own の両方にある')
        for s in dirs_of(f'skills/repos/{repo}'):
            if s not in (e.get('own') or []):
                err('repos', f'skills/repos/{repo}/{s}', 'repos.json の own に無い（配布されない）')
    for repo in dirs_of('skills/repos'):
        if repo not in repos:
            err('repos', f'skills/repos/{repo}', 'repos.json に登録されていない')
    used = {s for e in repos.values() for s in (e.get('shared') or [])}
    for s in dirs_of('skills/shared'):
        if s not in used:
            err('repos', f'skills/shared/{s}', 'どのリポジトリの shared にも無い（配布されない）')


def dirs_of(rel):
    """ハブからの相対パス rel の直下のディレクトリ（シェルの glob */ と同じく隠しものは除く）。"""
    d = os.path.join(HUB, rel)
    if not os.path.isdir(d):
        return []
    return sorted(n for n in os.listdir(d) if not n.startswith('.') and os.path.isdir(os.path.join(d, n)))


# ---------- symlink ----------

def check_symlinks(cfg, err):
    print('== symlinks')
    dirs = [HUB, USER_SKILLS]
    for repo in sorted(cfg.get('repos', {})):
        rpath = cfg['repos'][repo].get('path', '')
        if not rpath.startswith('~'):
            dirs.append(os.path.join(repo_dir(rpath), '.claude/skills'))
    for d in dirs:
        if not os.path.isdir(d):
            continue
        broken = []
        for root, subdirs, fs in os.walk(d):          # d 自体がリンクでも中を見る。中のリンクはたどらない
            subdirs[:] = [x for x in subdirs if not (x == '.git' and not os.path.islink(os.path.join(root, x)))]
            for n in subdirs + fs:
                p = os.path.join(root, n)
                if os.path.islink(p) and not os.path.exists(p):
                    broken.append(p)
        for p in sorted(broken):
            err('symlink', p, f'リンク先が無い: {os.readlink(p)}')


# ---------- link ----------

FENCE = re.compile(r'^ {0,3}(`{3,}|~{3,})')
CLOSE = re.compile(r'^ {0,3}[`~]+[ \t]*$')
CODE2 = re.compile(r'``[^`]*(`[^`]+)*``')
CODE1 = re.compile(r'`[^`]*`')
REFDEF = re.compile(r'^ {0,3}\[[^\]^][^\]]*\]:[ \t]*[^ \t]+')
REFHEAD = re.compile(r'^[^\]]*\]:[ \t]*')
INLINE = re.compile(r'\]\(((?:[^()]|\([^()]*\))+)\)')
TITLE = re.compile(r'[ \t]+".*"$')


def md_links(text):
    """[(行番号, リンク先)] を返す。"""
    out = []
    open_fence = ''
    for n, line in enumerate(text.split('\n'), 1):
        m = FENCE.match(line)
        f = m.group(1) if m else ''
        if open_fence:      # 開いたのと同じ文字で、同じ長さ以上の行だけが閉じる
            if f and f[0] == open_fence[0] and len(f) >= len(open_fence) and CLOSE.match(line):
                open_fence = ''
            continue
        if f:
            open_fence = f
            continue
        line = CODE1.sub('', CODE2.sub('', line))      # インラインコード
        m = REFDEF.match(line)
        if m:       # 参照定義 [id]: path（脚注 [^1]: は除く）
            out.append((n, strip_angle(REFHEAD.sub('', m.group(0), count=1))))
            continue
        for m in INLINE.finditer(line):     # [x](path)。括弧 1 段まで
            out.append((n, strip_angle(TITLE.sub('', m.group(1), count=1))))
    return out


def strip_angle(t):
    if t.startswith('<'):
        t = t[1:]
    if t.endswith('>'):
        t = t[:-1]
    return t


def check_links(files, err):
    print('== markdown links')
    home = os.environ.get('HOME', '')
    for f in files:
        if not (f.endswith('.md') or f.endswith('.markdown')):
            continue
        _, text = read_text(f)
        d = os.path.dirname(f) or '.'
        for n, t in md_links(text):
            if not t or t.startswith('#') or '://' in t or t.startswith(('mailto:', 'tel:', 'data:')) or '{' in t or '$' in t:
                continue
            p = t.split('#', 1)[0].split('?', 1)[0]
            if not p:
                continue
            p = p.replace('%20', ' ')
            if p.startswith('/'):
                target = p
            elif p.startswith('~'):
                target = home + p[1:]
            else:
                target = os.path.join(HUB, d, p)
            if not os.path.exists(target):
                err('link', f'{f}:{n}', t)


# ---------- abs ----------

def distributed(f):
    """配布するスキル（skills/shared/<skill>/... と skills/repos/<repo>/<skill>/...）なら 0。*-workspace スキルは 2、それ以外は 1。"""
    if f.startswith('skills/shared/'):
        rest = f[len('skills/shared/'):]
    elif f.startswith('skills/repos/') and '/' in f[len('skills/repos/'):]:
        rest = f[len('skills/repos/'):].split('/', 1)[1]
    else:
        return 1
    if '/' not in rest:         # ディレクトリ直下のファイルはスキルではない
        return 1
    return 2 if rest.split('/', 1)[0].endswith('-workspace') else 0


def roots_of(projects):
    """プロジェクト置き場の表記ゆれ。正規表現を使わず固定文字列で探す。"""
    roots = [projects]
    home = os.environ.get('HOME', '')
    home_p = os.path.realpath(home) if home and os.path.isdir(home) else ''
    for h in (home, home_p):
        if h and projects.startswith(h + '/'):
            rel = projects[len(h):]
            roots += ['~' + rel, '$HOME' + rel, '${HOME}' + rel]
            break
    return roots


def closes(line, p, op, spaces):
    """p-1 の文字が、その手前の最後の op（"${" か "$("）から始まる展開の閉じか。spaces=False なら中に空白を許さない。"""
    pre = line[:p - 1]
    j = pre.rfind(op)
    if j < 0:
        return False
    return spaces or not re.search(r'[ \t]', pre[j + len(op):])


def inword(line, p, generic):
    """位置 p（0 始まり）から始まるパスが、手前の文字から見て別の語の一部（= 絶対パスではない）か。

    -I/Users/... や -L/Users/... のようなコンパイラの短いオプションは絶対パスとみなす。
    /Users/・/home/ の判定（generic=True）では、${ROOT}/home/... と $(pwd)/home/... のように
    変数展開・コマンド置換の閉じ（} と )）の直後も別の語の一部とみなす。> の直後（リダイレクト、HTML タグ、<repo>）は検出する。
    """
    if p <= 0:
        return False
    b, bb = char(line, p - 1), char(line, p - 2)
    if b.isascii() and b.isalpha() and bb == '-' and (p <= 2 or not iswc(char(line, p - 3))):
        return False
    if generic and b == '}' and closes(line, p, '${', False):
        return True
    if generic and b == ')' and closes(line, p, '$(', True):
        return True
    return iswc(b)


def take(line, i):
    j = i
    while j < len(line) and ispc(line[j]):
        j += 1
    return line[i:j]


USERS = re.compile(r'/Users/[A-Za-z0-9._-]+')     # 末尾の / が無くても拾う
HOMES = re.compile(r'/home/[A-Za-z0-9._-]+/')     # Web のパスと紛れるので / まで要る


def scan(text, roots):
    """[(行番号, root の番号（0 は /Users/・/home/）, root の後ろ（root 0 ならパス全体）)] を返す。"""
    out = []
    for n, line in enumerate(text.split('\n'), 1):
        for k, root in enumerate(roots, 1):
            i = line.find(root)
            while i >= 0:
                after = i + len(root)
                nxt = char(line, after)
                # ルートの直後は / か、パスに使えない文字（文末の . も可。project2 や project-archive は別の名前）
                okn = nxt == '/' or not ispc(nxt) or (nxt == '.' and not ispc(char(line, after + 1)))
                if not inword(line, i, False) and okn:
                    out.append((n, k, take(line, after)))
                i = line.find(root, i + 1)
        for rx in (USERS, HOMES):
            for m in rx.finditer(line):
                if not inword(line, m.start(), True):
                    out.append((n, 0, take(line, m.start())))
    return out


def git_toplevel(d):
    r = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=d, capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return ''
    return os.path.realpath(r.stdout.strip())


def strip_dots(s):
    return re.sub(r'\.+$', '', s)


def check_abs(files, err):
    print('== absolute paths')
    projects = os.path.dirname(HUB)
    roots = roots_of(projects)
    seen = set()
    for f in files:
        if f == SELF:
            continue
        data, text = read_text(f)
        if b'\0' in data:       # バイナリ
            continue
        if not any(r in text for r in roots) and '/Users/' not in text and '/home/' not in text:
            continue
        kind = distributed(f)
        if kind == 2:
            continue
        for n, k, rest in scan(text, roots):
            # 例示（<branch>、...、{repo}、$VAR、*）。root の後ろだけを見る（$HOME 形式の root 自体の $ は例示ではない）。
            # 配布物では手前が具体的な絶対パスなので違反のまま。存在チェックでは例示の手前のディレクトリまでを確かめる
            rest = rest.rstrip('*')         # 末尾の * は Markdown の強調
            head = re.split(r'[<>{}$*]', rest, maxsplit=1)[0]
            if '...' in head:
                head = head.split('...', 1)[0]
            if head != rest:
                head = head.rsplit('/', 1)[0] + '/' if '/' in head else ''
                rest = head if kind != 0 else strip_dots(rest)
            else:
                rest = strip_dots(rest)
            if k == 0:
                if kind != 0:       # /Users/ 形式のルートそのものは root 側で拾うので、配布物以外ではここで扱わない
                    continue
                p = rest
            else:
                p = roots[k - 1] + rest
            if kind == 0:
                key = (f, n, p)     # root 形式と /Users/ 形式の二重報告を避ける
                if key in seen:
                    continue
                seen.add(key)
                err('abs', f'{f}:{n}', f'{p}（配布するスキルに絶対パスは書けない）')
                continue
            target = projects + rest
            if os.path.exists(target):
                continue
            # リポジトリ自体があれば、その中の .dvc/cache や data/、<repo>.worktrees/ など
            # 実行時に作られる（git 管理外の）パスは切れているとみなさない
            anc = target[:-1] if target.endswith('/') else target
            anc = re.sub(r'\.worktrees(/.*)?$', '', anc, count=1)
            while not os.path.exists(anc):
                anc = os.path.dirname(anc) or '.'
            if not os.path.isdir(anc):
                anc = os.path.dirname(anc) or '.'
            top = git_toplevel(anc)
            if top and top != HUB:
                continue
            err('abs', f'{f}:{n}', p)


# ---------- entry ----------

def main(a):
    try:
        with open(CONFIG) as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        print('skills/repos.json を JSON として読めない', file=sys.stderr)
        return 2
    errors = 0

    def err(kind, loc, msg):
        nonlocal errors
        print(f'  {kind:<8} {loc}: {msg}')
        errors += 1

    try:
        files = tracked_files()
        check_repos(cfg, err)
        check_symlinks(cfg, err)
        check_links(files, err)
        if not a.no_abs:
            check_abs(files, err)
    except Fail as e:
        print(str(e), file=sys.stderr)
        return 2
    print()
    if errors:
        print(f'NG: 問題のあるパスが {errors} 件')
        return 1
    print('OK: 問題のあるパスは無い')
    return 0
