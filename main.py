from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import List

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.spec_parser import parse_spec
from app.walker import walk
from app.compare import compare, summarize


BASE = Path(__file__).parent
app = FastAPI(title="Qualtrics Checker")

(BASE / "static").mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse((BASE / "templates" / "index.html").read_text())


def _split_links(raw: str) -> List[str]:
    items = []
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("http://") or line.startswith("https://"):
            items.append(line)
    return items


@app.post("/api/check")
async def check(
    links: str = Form(...),
    spec: UploadFile = File(...),
) -> JSONResponse:
    urls = _split_links(links)
    if not urls:
        return JSONResponse({"error": "No valid http(s) links found."}, status_code=400)

    spec_bytes = await spec.read()
    spec_questions = parse_spec(spec.filename or "spec", spec_bytes)

    reports = []
    for url in urls:
        try:
            report = await walk(url)
        except Exception as e:
            from app.models import LinkReport
            report = LinkReport(url=url, ok=False, pages_visited=0, errors=[f"Walker crashed: {e}"])

        report.matches = compare(spec_questions, report.found_questions)
        report.summary = summarize(report.matches)
        reports.append(report)

    def ser(obj):
        if hasattr(obj, "__dataclass_fields__"):
            return {k: ser(getattr(obj, k)) for k in obj.__dataclass_fields__}
        if isinstance(obj, list):
            return [ser(x) for x in obj]
        if isinstance(obj, dict):
            return {k: ser(v) for k, v in obj.items()}
        return obj

    return JSONResponse({
        "spec_count": len(spec_questions),
        "spec": [asdict(q) for q in spec_questions],
        "reports": [ser(r) for r in reports],
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8765, reload=False)
