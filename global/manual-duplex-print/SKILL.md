---
name: manual-duplex-print
description: Print a PDF (URL or local file, optional page range / book-page range) in grayscale with manual double-sided printing on the user's EPSON EP-M552T, which has no auto-duplex. Use when the user says "印刷して", "両面印刷", "白黒で印刷", "この論文を印刷", "手動で両面", "print this PDF", or asks to print specific sections/pages of a paper or book PDF. Handles PDF-page vs printed-page-number offsets, odd/even passes, and the exact paper reload orientation that has been verified on this printer.
---

# Manual Duplex Print (EPSON EP-M552T)

The printer `EPSON_EP_M552T_Series` (system default) prints grayscale but has **no auto duplex**.
Double-sided output is done in two passes: fronts (odd pages), user reloads paper, backs (even pages).

## Verified facts about this printer (do not re-test)

- **Feed order**: the sheet at the **bottom** of the stack in the front cassette is fed **first**.
  → Backs must be sent in **forward order** (2, 4, 6, …) when the stack is reloaded exactly as it came out.
- **Reload orientation** (front cassette): printed side **down**, page top edge toward the **front (user side)**,
  first-printed sheet at the bottom, last-printed sheet on top.
- Grayscale: `-o ColorModel=Gray`.
- If the page count is odd, the last sheet simply is not fed in the back pass. No blank page needed.
- Testing with 1 sheet is meaningless (always "succeeds"). If a test is needed, use 2–3 sheets.

## Procedure

1. **Get the PDF** into the scratchpad (its own directory):
   `curl -sL -o <dir>/x.pdf <url>` ; check with `pdfinfo` (page count).
2. **Resolve the page range.**
   - If the user gives book/printed page numbers or section numbers, compute the PDF-page offset:
     `pdftotext -f N -l N -layout x.pdf - | grep -oE '(^| )[0-9]{3}( |$)'` to read the printed number on PDF page N,
     and grep for `§` / section headers to find section boundaries. Report a table
     (section | printed pages | PDF pages) and confirm before printing when the request is ambiguous.
   - Non-contiguous ranges: build one combined PDF with `pdfseparate` + `pdfunite` so page parity is simple.
3. **Pass 1 – fronts**:
   `lp -d EPSON_EP_M552T_Series -o ColorModel=Gray -P <range> -o page-set=odd file.pdf`
   (or an explicit `-P 1,3,5,…` list). Report the job ID and the list of printed page numbers.
4. **Tell the user** to reload the stack with the verified orientation above, in concrete words
   (印刷面を下、上端を手前、最初のページが一番下). Wait for 「セットした」.
5. **Pass 2 – backs**:
   `lp -d EPSON_EP_M552T_Series -o ColorModel=Gray -P <range> -o page-set=even file.pdf` (forward order).
6. Report which pages are now paired (e.g. end of §14 backs onto start of §16) and any blank back.

## Response style the user expects

- Japanese, terse, no extra background. Answer exactly what is asked (e.g. "which page goes at the bottom": name the page).
- Give physical instructions concretely (手前/奥, 上/下, 印刷面の向き), never "same as before".
- Always include the job ID (`lp` prints 要求ID) and the pages sent.
- Use `cancel <job-id>` immediately if the user reports a misprint while a job is running.

## Troubleshooting seen in practice

- Backs landed on the wrong sheets (e.g. p.188 on the back of p.153) → feed order was assumed backwards. Stack is ruined; reprint fronts.
- Backs upside-down but on correct sheets → rotate the stack 180° (top edge to front).
- Pages missing at the start → earlier test sheets were discarded; reprint just those fronts then backs.
