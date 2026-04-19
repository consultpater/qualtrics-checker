"""Compare spec questions against questions found on the Qualtrics site."""
from __future__ import annotations

import re
from typing import List

from rapidfuzz import fuzz

from .models import SpecQuestion, FoundQuestion, MatchResult


# Similarity cutoffs.
STRONG_MATCH = 88   # treat as "match"
WEAK_MATCH = 72     # treat as "typo/drift"


def _norm(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def compare(spec: List[SpecQuestion], found: List[FoundQuestion]) -> List[MatchResult]:
    results: List[MatchResult] = []
    used_found: set[int] = set()

    # For each spec question, find the best unused match in found.
    for sq in spec:
        sq_norm = _norm(sq.text)
        best_idx = -1
        best_score = 0.0
        for i, fq in enumerate(found):
            if i in used_found:
                continue
            score = fuzz.token_set_ratio(sq_norm, _norm(fq.text))
            if score > best_score:
                best_score = score
                best_idx = i
        if best_idx >= 0 and best_score >= STRONG_MATCH:
            used_found.add(best_idx)
            results.append(MatchResult(spec=sq, found=found[best_idx], score=best_score, status="match"))
        elif best_idx >= 0 and best_score >= WEAK_MATCH:
            used_found.add(best_idx)
            results.append(MatchResult(spec=sq, found=found[best_idx], score=best_score, status="typo"))
        else:
            results.append(MatchResult(spec=sq, found=None, score=best_score, status="missing"))

    # Whatever's left in found is "extra".
    for i, fq in enumerate(found):
        if i in used_found:
            continue
        results.append(MatchResult(spec=None, found=fq, score=0.0, status="extra"))

    return results


def summarize(results: List[MatchResult]) -> dict:
    s = {"match": 0, "typo": 0, "missing": 0, "extra": 0, "total_spec": 0, "total_found": 0}
    for r in results:
        s[r.status] += 1
        if r.spec:
            s["total_spec"] += 1
        if r.found:
            s["total_found"] += 1
    return s
