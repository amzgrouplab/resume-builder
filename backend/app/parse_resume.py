"""Read a .docx into ordered paragraphs without altering the file."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Iterator

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from .dates import RANGE_RE, RoleDates, parse_role_dates

BULLET_PREFIX_RE = re.compile(r"^([\u2022\u25cf\u25e6\u25aa\u25ab\u2043\-–—]\s*)")
MANUAL_BULLET_RE = re.compile(
    r"^[\u2022\u25cf\u25e6\u25aa\u25ab\u2043\-–—]\s+\S"
)
SECTION_HINTS = (
    "experience",
    "employment",
    "work history",
    "professional",
    "skills",
    "technical",
    "summary",
    "education",
    "projects",
    "certif",
)


@dataclass
class ResumeParagraph:
    id: int
    text: str
    is_bullet: bool
    style_name: str
    in_table: bool
    manual_prefix: str
    role_title: str
    role_dates: str
    start_year: int | None
    end_year: int | None
    is_current_role: bool
    char_budget: int
    is_summary: bool = False

    def to_public(self) -> dict[str, Any]:
        data = asdict(self)
        return data


def _iter_body_paragraphs(doc: Document) -> Iterator[tuple[Paragraph, bool]]:
    body = doc.element.body
    for node in body.iter():
        if node.tag != qn("w:p"):
            continue
        in_table = False
        parent = node.getparent()
        while parent is not None:
            if parent.tag == qn("w:tbl"):
                in_table = True
                break
            parent = parent.getparent()
        yield Paragraph(node, doc), in_table


def _has_numpr(paragraph: Paragraph) -> bool:
    ppr = paragraph._p.pPr
    if ppr is None:
        return False
    return ppr.find(qn("w:numPr")) is not None


def _style_name(paragraph: Paragraph) -> str:
    try:
        return paragraph.style.name if paragraph.style else ""
    except Exception:
        return ""


def _looks_like_job_or_edu_header(text: str) -> bool:
    compact = " ".join(text.split())
    if not compact:
        return False
    dated = parse_role_dates(compact, present_year=2026) is not None
    sentence = bool(re.search(r"[.!?]$", compact))
    if dated and not sentence and len(compact) < 160:
        return True
    if re.search(r"\b(Bachelor|Master|University|College|GPA)\b", compact, re.I):
        if not sentence and len(compact) < 140:
            return True
    return False


def is_bullet_paragraph(paragraph: Paragraph) -> bool:
    text = paragraph.text.replace("\xa0", " ").strip()
    if not text:
        return False
    listed = _has_numpr(paragraph)
    if not listed:
        style = _style_name(paragraph).lower()
        listed = bool(re.search(r"list|bullet", style) or MANUAL_BULLET_RE.match(text))
    if not listed:
        return False
    if _looks_like_section(text) or _looks_like_job_or_edu_header(text):
        return False
    return True


def _looks_like_section(text: str) -> bool:
    compact = text.strip()
    if not compact or len(compact) > 48:
        return False
    lower = compact.lower()
    if any(hint in lower for hint in SECTION_HINTS) and len(compact.split()) <= 6:
        return True
    letters = re.sub(r"[^A-Za-z]", "", compact)
    return bool(letters) and letters.upper() == letters and len(compact.split()) <= 6


def _looks_like_role_header(text: str) -> bool:
    if not text or _looks_like_section(text):
        return False
    if parse_role_dates(text, present_year=2026):
        return True
    if len(text) <= 90 and not text.endswith("."):
        return True
    return False


def _prefix_of(text: str) -> str:
    match = BULLET_PREFIX_RE.match(text)
    return match.group(1) if match else ""


def parse_document(path: str, present_year: int = 2026) -> tuple[Document, list[ResumeParagraph]]:
    doc = Document(path)
    raw: list[tuple[Paragraph, bool]] = list(_iter_body_paragraphs(doc))
    rows: list[ResumeParagraph] = []
    header_window: list[str] = []
    current_dates: RoleDates | None = None
    current_title = ""
    in_summary = False

    for index, (paragraph, in_table) in enumerate(raw):
        text = paragraph.text.replace("\xa0", " ").strip()
        bullet = is_bullet_paragraph(paragraph) if text else False
        summary_body = False
        if text and not bullet:
            if _looks_like_section(text):
                header_window = []
                lower = text.lower()
                in_summary = "summary" in lower
                if any(hint in lower for hint in ("skill", "summary")):
                    current_dates = None
                    current_title = " ".join(text.split())
                elif "education" in lower:
                    current_dates = None
                    in_summary = False
                elif any(hint in lower for hint in ("experience", "employment", "work history")):
                    in_summary = False
            else:
                header_window = (header_window + [text])[-4:]
                dates = parse_role_dates(text, present_year)
                if dates:
                    current_dates = dates
                    remainder = RANGE_RE.sub("", text)
                    remainder = re.sub(r"\s+", " ", remainder)
                    remainder = re.sub(r"[\s|,/–—-]+$", "", remainder)
                    remainder = re.sub(r"^[\s|,/–—-]+", "", remainder).strip()
                    if remainder and not _looks_like_section(remainder):
                        current_title = remainder
                elif _looks_like_role_header(text):
                    current_title = text
                elif in_summary and len(text) > 60:
                    summary_body = True
                    current_title = current_title or "PROFESSIONAL SUMMARY"

        tailorable = bullet or summary_body
        role_dates = current_dates.prompt_line() if current_dates else ""
        rows.append(
            ResumeParagraph(
                id=index,
                text=text,
                is_bullet=bullet,
                style_name=_style_name(paragraph),
                in_table=in_table,
                manual_prefix=_prefix_of(paragraph.text.lstrip()) if bullet else "",
                role_title=current_title if tailorable else "",
                role_dates=role_dates if (bullet and not summary_body) else "",
                start_year=current_dates.start_year if current_dates and bullet and not summary_body else None,
                end_year=current_dates.end_year if current_dates and bullet and not summary_body else None,
                is_current_role=bool(current_dates and current_dates.is_current) if bullet and not summary_body else False,
                char_budget=len(BULLET_PREFIX_RE.sub("", text).strip()) if tailorable else 0,
                is_summary=summary_body,
            )
        )
    return doc, rows


def summarize_parse(rows: list[ResumeParagraph]) -> dict[str, Any]:
    bullets = [r for r in rows if r.is_bullet and r.text]
    summaries = [r for r in rows if r.is_summary and r.text]
    roles: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for bullet in bullets:
        key = (bullet.role_title, bullet.role_dates)
        if key in seen or not (bullet.role_title or bullet.role_dates):
            continue
        seen.add(key)
        count = sum(1 for b in bullets if (b.role_title, b.role_dates) == key)
        roles.append(
            {
                "title": bullet.role_title or "Untitled role",
                "dates": bullet.role_dates,
                "start_year": bullet.start_year,
                "end_year": bullet.end_year,
                "is_current": bullet.is_current_role,
                "bullets": count,
            }
        )
    return {
        "paragraphs": len(rows),
        "bullets": len(bullets),
        "summaries": len(summaries),
        "roles": roles,
        "preview": [b.to_public() for b in bullets],
    }
