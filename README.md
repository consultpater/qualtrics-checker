# qualtrics-checker

A small web tool that auto-walks live Qualtrics surveys with a headless browser
and compares the questions it sees against an expected questionnaire (PDF or
DOCX). Useful for QA'ing a survey before launch.

## What it does
- Paste one or more Qualtrics survey URLs.
- Upload the reference questionnaire (`.pdf` or `.docx`).
- The tool launches a headless Chromium via Playwright, walks every page,
  auto-fills answers enough to advance, and extracts the questions it sees.
- Results are fuzzy-matched against the spec and reported as:
  `match` / `typo` / `missing` / `extra`, plus any validation errors the
  survey returned.

## Quick start
Requires [`uv`](https://github.com/astral-sh/uv) (no sudo needed):

```bash
# one-time setup
uv sync
uv run playwright install chromium

# run the app
uv run uvicorn main:app --port 8765
```

Then open http://127.0.0.1:8765/.

## Layout
```
main.py               # FastAPI app + /api/check endpoint
app/spec_parser.py    # PDF/DOCX -> list of expected questions
app/walker.py         # Playwright survey walker
app/compare.py        # Fuzzy compare (rapidfuzz)
app/models.py         # Dataclasses
templates/index.html  # Single-page UI
```

## Caveats
- Spec parsing is heuristic (looks for `1.` / `Q1.` / `?`-ending lines).
- The walker advances by picking the first valid answer; it does not handle
  every Qualtrics widget (sliders, rank-order, drag-drop, captchas).
- Branching/logic surveys will only traverse the single path the auto-filler
  happens to take.
