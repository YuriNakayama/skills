"""Grade code-explain eval runs.

Checks the mechanically verifiable assertions so the human review can focus on
the judgement calls (is the tree annotation actually useful, did it find the
right things). Writes grading.json per run in the shape the eval viewer wants:
each expectation is {text, passed, evidence}.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ITER = Path(__file__).parent / (sys.argv[1] if len(sys.argv) > 1 else "iteration-1")
TODAY = date.today().strftime("%Y%m%d")

REPO = Path("/Users/user/project/01_kaggle/kaggriculture")


def _docs(outputs: Path) -> list[Path]:
    """Analysis documents, excluding the side files we asked for separately."""
    skip = {"terminal_summary.md", "scope_resolution.md"}
    return [p for p in sorted(outputs.glob("*.md")) if p.name not in skip]


def grade(run_dir: Path, scope_slugs: list[str]) -> dict:
    outputs = run_dir / "outputs"
    docs = _docs(outputs) if outputs.is_dir() else []
    body = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in docs)
    low = body.lower()
    exp: list[dict] = []

    def add(text: str, passed: bool, evidence: str) -> None:
        exp.append({"text": text, "passed": bool(passed), "evidence": evidence})

    # --- output exists -----------------------------------------------------
    add(
        "Output document exists as a .md file",
        bool(docs),
        f"found: {[p.name for p in docs]}" if docs else "no .md document in outputs/",
    )

    # --- filename convention ----------------------------------------------
    named = [p.name for p in docs if re.match(rf"^{TODAY}_[a-z0-9_]+\.md$", p.name)]
    add(
        f"Filename matches the {{yyyymmdd}}_{{scope}}.md convention using today's date ({TODAY})",
        bool(named),
        f"matching: {named}" if named else f"names were {[p.name for p in docs]}",
    )

    # --- three passes present ---------------------------------------------
    tree = bool(re.search(r"├|└|```\s*\n[\w./-]+/", body)) or "ディレクトリ" in body
    inventory = ("クラス" in body or "class" in low) and body.count("|") > 20
    steps = bool(re.search(r"^\s*\d+\.\s", body, re.M)) and (
        "処理" in body or "step" in low or "フロー" in body
    )
    add(
        "Document contains all three analysis passes: directory tree, class/method inventory, processing steps",
        tree and inventory and steps,
        f"tree={tree}, inventory={inventory}, steps={steps}",
    )

    # --- inventory table has responsibility + I/O columns ------------------
    header_rows = re.findall(r"^\|.*\|$", body, re.M)
    io_table = any(
        ("責務" in h or "responsib" in h.lower())
        and ("input" in h.lower() or "入力" in h or "引数" in h)
        for h in header_rows
    )
    add(
        "Class/method inventory is a table including responsibility and input/output columns",
        io_table,
        "found a table header with責務/responsibility + input columns"
        if io_table
        else f"{len(header_rows)} table rows, none with both columns",
    )

    # --- numbered steps cite file:line -------------------------------------
    anchors = re.findall(r"[\w/]+\.py[:#]\s?L?\d+", body)
    add(
        "Processing steps are numbered and cite specific file:line anchors",
        steps and len(anchors) >= 3,
        f"{len(anchors)} file:line anchors (e.g. {anchors[:3]})"
        if anchors
        else "no file:line anchors found",
    )

    # --- header block ------------------------------------------------------
    has_scope = "対象" in body or "scope" in low
    has_size = bool(re.search(r"\d+\s*(ファイル|files?)", body)) and bool(
        re.search(r"\d[\d,]*\s*(行|lines?)", body)
    )
    has_date = bool(re.search(r"20\d{2}-?\d{2}-?\d{2}", body))
    sha = bool(re.search(r"\b[0-9a-f]{7,40}\b", body))
    add(
        "Header block records scope paths, file/line counts, analysis date, and commit sha",
        has_scope and has_size and has_date and sha,
        f"scope={has_scope}, size={has_size}, date={has_date}, sha={sha}",
    )

    # --- terminal summary --------------------------------------------------
    ts = outputs / "terminal_summary.md"
    add(
        "A separate terminal summary was produced (terminal_summary.md)",
        ts.is_file(),
        f"{ts.stat().st_size} bytes" if ts.is_file() else "missing",
    )

    # --- repo pollution ----------------------------------------------------
    polluted = subprocess.run(
        ["git", "status", "--porcelain", "docs/"],
        cwd=REPO,
        capture_output=True,
        text=True,
    ).stdout.strip()
    add(
        "Document does not write into the repo's docs/ tree (no repo pollution)",
        not polluted,
        "repo docs/ clean" if not polluted else f"dirty: {polluted[:200]}",
    )


    # --- glossary present (self-contained requirement) ---------------------
    glossary = bool(re.search(r"##\s*(用語|Glossary)", body))
    gloss_rows = 0
    if glossary:
        seg = body.split("用語", 1)[1]
        seg = seg.split("\n## ", 1)[0]
        gloss_rows = len([r for r in re.findall(r"^\|.*\|$", seg, re.M)]) - 2
    add(
        "Document opens with a 用語 (glossary) table defining identifiers and domain terms",
        glossary and gloss_rows >= 3,
        f"glossary section={glossary}, ~{max(gloss_rows,0)} terms defined",
    )

    # --- visual density (show, don't narrate) ------------------------------
    mermaid = body.count("```mermaid")
    tables = len(re.findall(r"^\|", body, re.M))
    codeblocks = body.count("```") // 2
    # Count formats used rather than demanding a quota of each: a document
    # with dense tables and one well-placed diagram is not worse than one with
    # two diagrams. Requiring >=2 mermaid would reward padding.
    formats = sum([tables >= 25, mermaid >= 1, codeblocks >= 4])
    add(
        "Uses at least 3 visual formats densely (tables, mermaid, skeleton code) rather than prose",
        formats >= 3,
        f"mermaid={mermaid}, table rows={tables}, code blocks={codeblocks} -> {formats}/3 formats",
    )

    # --- self-review evidence ----------------------------------------------
    ts_body = ts.read_text(encoding="utf-8", errors="replace") if ts.is_file() else ""
    reviewed = bool(re.search(r"セルフレビュー|self-review", ts_body, re.I))
    add(
        "Terminal summary reports a self-review pass and what it changed",
        reviewed,
        "self-review line present" if reviewed else "no self-review line in terminal_summary.md",
    )

    # --- scope slug (eval-1 only) ------------------------------------------
    if scope_slugs:
        hit = [s for s in scope_slugs if any(s in p.name for p in docs)]
        add(
            f"Scope slug in the filename reflects the resolved scope ({'/'.join(scope_slugs)})",
            bool(hit),
            f"matched {hit}" if hit else f"names were {[p.name for p in docs]}",
        )

    passed = sum(1 for e in exp if e["passed"])
    total = len(exp)
    return {
        "expectations": exp,
        # aggregate_benchmark.py reads pass_rate / passed / failed / total.
        "summary": {
            "passed": passed,
            "failed": total - passed,
            "total": total,
            "pass_rate": round(passed / total, 4) if total else 0.0,
        },
    }


def main() -> None:
    slugs = {"eval-1-vague-scope-jaxenv": ["jaxenv", "jax_env", "jax"]}
    for eval_dir in sorted(ITER.glob("eval-*")):
        for run in ("with_skill", "without_skill", "old_skill"):
            # aggregate_benchmark.py expects config/run-N/, so outputs and
            # grading live one level deeper than the config directory.
            run_dir = eval_dir / run / "run-1"
            if not run_dir.is_dir():
                continue
            result = grade(run_dir, slugs.get(eval_dir.name, []))
            (run_dir / "grading.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            s = result["summary"]
            print(f"{eval_dir.name:34s} {run:14s} {s['passed']}/{s['total']}")


if __name__ == "__main__":
    sys.exit(main())
