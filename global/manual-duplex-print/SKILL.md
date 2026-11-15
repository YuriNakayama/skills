---
name: manual-duplex-print
description: Print a PDF (URL or local file, optional page range / book-page range) in grayscale with manual double-sided printing on the user's EPSON EP-M552T, which has no auto-duplex. Use when the user says "印刷して", "両面印刷", "白黒で印刷", "この論文を印刷", "手動で両面", "print this PDF", or asks to print specific sections/pages of a paper or book PDF. Handles PDF-page vs printed-page-number offsets, odd/even passes, and the exact paper reload orientation that has been verified on this printer.
---

# Manual Duplex Print (EPSON EP-M552T)

The printer `EPSON_EP_M552T_Series` (system default) prints grayscale but has **no auto duplex**.
Double-sided output is done in two passes: fronts (odd pages), user reloads paper, backs (even pages).

## Verified facts about this printer (do not re-test)

- **Feed order**: the sheet on the **top** of the stack in the front cassette is fed **first**.
  (An older version of this skill said "bottom first". That was wrong and caused p.1 to come out with a blank back.)
- **Reload orientation** (front cassette): put the fronts stack back **exactly as it came out, without reordering**.
  Printed side **down**, page top edge toward the **front (user side)**. The first page stays at the bottom.
- Grayscale: `-o ColorModel=Gray`. High quality: `-o cupsPrintQuality=High` (default is Normal).
- Letter-size PDFs: add `-o fit-to-page` so they fit A4.
- Testing with 1 sheet is meaningless (always "succeeds"). If a test is needed, use 2–3 sheets.

## Procedure

1. **Get the PDF** into the scratchpad (its own directory):
   `curl -sL -o <dir>/x.pdf <url>` ; check with `pdfinfo` (page count).
2. **Resolve the page range.**
   - Papers: find where references and appendices start.
     Find the `References` heading page with `pdftotext -f N -l N -layout`; the page is body if body text is on it.
     Check whether an appendix (`A  <Title>`) follows the references.
     **Before printing, ask the user** with AskUserQuestion whether to print references and appendices.
     Show a table (paper | body pages | references pages | appendix pages | sheets with / without).
     Options: 本文のみ (recommended), 本文＋付録, すべて. Do not send any job until answered.
   - If the user gives book/printed page numbers or section numbers, compute the PDF-page offset:
     `pdftotext -f N -l N -layout x.pdf - | grep -oE '(^| )[0-9]{3}( |$)'` to read the printed number on PDF page N,
     and grep for `§` / section headers to find section boundaries. Report a table
     (section | printed pages | PDF pages) and confirm before printing when the request is ambiguous.
   - Non-contiguous ranges: build one combined PDF with `pdfseparate` + `pdfunite` so page parity is simple.
3. **One job at a time.** Before every `lp`, run `lpstat -o` and send only when the queue is empty.
   Never queue the back pass behind an unfinished front pass.
4. **Pass 1 – fronts** (odd pages, forward order):
   `lp -d EPSON_EP_M552T_Series -o ColorModel=Gray -o cupsPrintQuality=High -P <range> -o page-set=odd file.pdf`
   Report the job ID and the list of printed page numbers.
5. **Tell the user how to reload**, in concrete words, and **decide the removal yourself**:
   - 「束を出てきた順のまま、印刷面を下・上端を手前にして入れる」
   - If the number of pages in the range is **odd**, the last front sheet has no back:
     say 「<最終ページ> ページの紙を抜いてからセット」. If even, say 「抜く紙はない」.
     Never leave this judgment to the user.
   Wait for 「セットした」.
6. **Pass 2 – backs** (even pages, **reverse order**, because the top sheet = last front is fed first):
   `lp -d EPSON_EP_M552T_Series -o ColorModel=Gray -o cupsPrintQuality=High -P <explicit list, e.g. 22,20,…,2> file.pdf`
   Use an explicit descending `-P` list; check with `lpstat -o` first.
7. Report which pages are now paired and any sheet left with a blank back.

## Response style the user expects

- Japanese, terse, no extra background. When the cause is unknown, say 「原因は不明」 instead of guessing. Answer exactly what is asked (e.g. "which page goes at the bottom": name the page).
- Give physical instructions concretely (手前/奥, 上/下, 印刷面の向き), never "same as before".
- Always include the job ID (`lp` prints 要求ID) and the pages sent.
- Use `cancel <job-id>` immediately if the user reports a misprint while a job is running.

## Troubleshooting seen in practice

- p.1 back blank and p.2 on the back of p.3 → feed order was assumed bottom-first. It is top-first; use step 5–6 above.
- Backs landed on the wrong sheets (e.g. p.188 on the back of p.153) → feed order or removal was wrong. Stack is ruined; reprint fronts.
- Several jobs queued at once (fronts and backs) → backs print on fresh paper. `cancel` the extra jobs immediately.
- Backs upside-down but on correct sheets → rotate the stack 180° (top edge to front).
- Pages missing at the start → earlier test sheets were discarded; reprint just those fronts then backs.
