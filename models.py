from dataclasses import dataclass, field
from typing import List, Optional, Literal

QuestionType = Literal[
    "radio", "checkbox", "text", "textarea", "dropdown",
    "matrix", "slider", "rank", "constant_sum", "unknown"
]


@dataclass
class SpecQuestion:
    """A question expected to exist, parsed from an uploaded spec doc."""
    number: Optional[str]  # e.g. "Q1", "1.", "1a"
    text: str
    raw_line: str = ""


@dataclass
class FoundQuestion:
    """A question encountered while walking a Qualtrics survey."""
    page: int
    text: str
    type: QuestionType
    options: List[str] = field(default_factory=list)
    required: bool = False


@dataclass
class MatchResult:
    spec: Optional[SpecQuestion]
    found: Optional[FoundQuestion]
    score: float  # 0-100 similarity
    status: Literal["match", "typo", "missing", "extra"]


@dataclass
class LinkReport:
    url: str
    ok: bool
    pages_visited: int
    errors: List[str] = field(default_factory=list)
    found_questions: List[FoundQuestion] = field(default_factory=list)
    matches: List[MatchResult] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
