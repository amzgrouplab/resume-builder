"""Employment date parsing from resume header lines."""

from __future__ import annotations

import re
from dataclasses import dataclass

MONTHS = (
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
)

YEAR = r"(?:19|20)\d{2}"
PRESENT = r"Present|Current|Now|Ongoing|Till\s+Date|To\s+Date"

RANGE_RE = re.compile(
    rf"(?P<start_month>{MONTHS})?\s*,?\s*(?P<start_year>{YEAR})\s*"
    rf"(?:[\u2013\u2014\-–—]|to)\s*"
    rf"(?:(?P<end_present>{PRESENT})|(?:(?P<end_month>{MONTHS})?\s*,?\s*(?P<end_year>{YEAR})))",
    re.I,
)

YEAR_RE = re.compile(rf"\b({YEAR})\b")


@dataclass(frozen=True)
class RoleDates:
    label: str
    start_year: int | None
    end_year: int | None
    is_current: bool

    def prompt_line(self) -> str:
        start = str(self.start_year) if self.start_year else "?"
        if self.is_current:
            end = "Present"
        elif self.end_year:
            end = str(self.end_year)
        else:
            end = "?"
        return f"{start}–{end}"


def parse_role_dates(text: str, present_year: int) -> RoleDates | None:
    cleaned = " ".join(text.split())
    match = RANGE_RE.search(cleaned)
    if not match:
        years = [int(y) for y in YEAR_RE.findall(cleaned)]
        if not years:
            return None
        start = min(years)
        end = max(years)
        current = bool(re.search(PRESENT, cleaned, re.I))
        return RoleDates(
            label=cleaned[:180],
            start_year=start,
            end_year=present_year if current else end,
            is_current=current,
        )

    start_year = int(match.group("start_year"))
    if match.group("end_present"):
        return RoleDates(
            label=cleaned[:180],
            start_year=start_year,
            end_year=present_year,
            is_current=True,
        )
    end_year = int(match.group("end_year"))
    return RoleDates(
        label=cleaned[:180],
        start_year=start_year,
        end_year=end_year,
        is_current=False,
    )
