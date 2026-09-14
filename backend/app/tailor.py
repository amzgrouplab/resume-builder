"""OpenAI rewrite of resume bullets, constrained to truth, dates, and length."""

from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from .parse_resume import ResumeParagraph
from .timeline import format_timeline_for_prompt, relevant_timeline, timeline_violations

SYSTEM_PROMPT = """You are a precise resume editor for a real candidate.

Rewrite existing work and skills bullets so they align with the job description.
The document layout is frozen. Only bullet wording may change.

Hard rules:
1. Return JSON only.
2. Include in `updates` every bullet you were given. If a bullet should stay, return the original text.
3. Never add or delete bullets. Never change ids, employers, titles, dates, or education.
4. Do not invent metrics, customers, awards, headcount, or tools the original bullet does not support.
5. Keep the real project. Preserve named systems, products, pipelines, models, and implementation details.
6. Do not replace concrete engineering with generic consulting language such as "supported client delivery" or "partnered with stakeholders" unless that work is already in the bullet.
7. Map the job description onto the real work: APIs, full-stack components, LLM workflows, cloud, testing, and deployment that the original already shows.
8. `rewritten` MUST be within ±6% of `char_budget` characters so the Word layout does not shift. Count characters. Match the original line length.
9. Technology dates are binding. If a tool launched after a role ended, it must not appear there.
10. Do not move a later stack into an earlier role. Do not convert a GCP-only role into Azure, or the reverse.
11. No bullet glyphs such as •.

JSON:
{"target_role":"","company":"","updates":[{"id":12,"rewritten":"...","reason":"≤8 words"}],"notes":[]}
"""

OPENAI_TIMEOUT_SEC = 180.0


def _frozen_context(rows: list[ResumeParagraph], limit: int = 24) -> str:
    lines: list[str] = []
    for row in rows:
        if row.is_bullet or not row.text:
            continue
        lines.append(f"[FROZEN {row.id}] {row.text}")
        if len(lines) >= limit:
            break
    return "\n".join(lines)


def _bullet_block(bullets: list[ResumeParagraph]) -> str:
    lines = ["id | role | years | end | char_budget | original"]
    for row in bullets:
        body = row.text
        if row.manual_prefix:
            body = body[len(row.manual_prefix) :].strip()
        end = row.end_year if row.end_year is not None else "?"
        role = re.sub(r"\s+", " ", row.role_title or "Unknown")
        years = row.role_dates or "?"
        lines.append(f"{row.id} | {role} | {years} | {end} | {row.char_budget} | {body}")
    return "\n".join(lines)


def _client(api_key: str) -> OpenAI:
    return OpenAI(api_key=api_key, timeout=OPENAI_TIMEOUT_SEC, max_retries=1)


def _group_bullets(bullets: list[ResumeParagraph]) -> list[list[ResumeParagraph]]:
    groups: list[list[ResumeParagraph]] = []
    current: list[ResumeParagraph] = []
    key: tuple[str, str] | None = None
    for row in bullets:
        item_key = (row.role_title, row.role_dates)
        if key is None or item_key == key:
            current.append(row)
            key = item_key
            continue
        groups.append(current)
        current = [row]
        key = item_key
    if current:
        groups.append(current)
    return groups


def _call_model(
    *,
    client: OpenAI,
    model: str,
    job_description: str,
    timeline_text: str,
    frozen: str,
    bullets: list[ResumeParagraph],
) -> dict[str, Any]:
    user_prompt = (
        "JOB DESCRIPTION:\n"
        f"{job_description.strip()}\n\n"
        "LAUNCH DATES (do not place a tool in a role that ended before it launched):\n"
        f"{timeline_text}\n\n"
        "HEADERS (read-only):\n"
        f"{frozen}\n\n"
        "Rewrite EVERY bullet below. Keep the real project and hit char_budget ±6%:\n"
        f"{_bullet_block(bullets)}\n"
    )
    max_tokens = min(8000, 700 + (len(bullets) * 220))
    response = client.chat.completions.create(
        model=model,
        temperature=0.15,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    raw = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("The model did not return valid JSON. Try again.") from exc
    if not isinstance(parsed, dict) or "updates" not in parsed:
        raise ValueError("The model response was missing updates.")
    return parsed


def tailor_bullets(
    *,
    api_key: str,
    model: str,
    job_description: str,
    rows: list[ResumeParagraph],
) -> dict[str, Any]:
    bullets = [r for r in rows if r.is_bullet and r.text]
    if not bullets:
        raise ValueError("No bullet points were found in this Word resume.")

    timeline_text = format_timeline_for_prompt(
        relevant_timeline([job_description, *[r.text for r in rows if r.text]])
    )
    frozen = _frozen_context(rows)
    client = _client(api_key)
    merged: list[dict[str, Any]] = []
    notes: list[str] = []
    target_role = ""
    company = ""
    for group in _group_bullets(bullets):
        payload = _call_model(
            client=client,
            model=model,
            job_description=job_description,
            timeline_text=timeline_text,
            frozen=frozen,
            bullets=group,
        )
        merged.extend(payload.get("updates") or [])
        notes.extend(str(item) for item in (payload.get("notes") or []) if item)
        target_role = str(payload.get("target_role") or target_role)
        company = str(payload.get("company") or company)
    return {
        "target_role": target_role,
        "company": company,
        "updates": merged,
        "notes": notes,
    }


def _strip_glyph(text: str) -> str:
    return re.sub(r"^[\u2022\u25cf\u25e6\u25aa\u25ab\u2043\-–—]\s*", "", text.strip())


def validate_updates(
    rows: list[ResumeParagraph],
    model_payload: dict[str, Any],
    *,
    strict_timeline: bool,
    match_length: bool,
) -> tuple[dict[int, str], list[dict[str, Any]], list[dict[str, Any]]]:
    by_id = {r.id: r for r in rows if r.is_bullet}
    applied: dict[int, str] = {}
    report: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    seen: set[int] = set()
    for item in model_payload.get("updates") or []:
        if not isinstance(item, dict):
            continue
        try:
            pid = int(item["id"])
        except (KeyError, TypeError, ValueError):
            continue
        if pid in seen or pid not in by_id:
            continue
        seen.add(pid)
        row = by_id[pid]
        rewritten = _strip_glyph(str(item.get("rewritten") or "").strip())
        original_body = _strip_glyph(row.text)
        if not rewritten:
            rewritten = original_body

        reasons: list[str] = []
        final = rewritten

        if match_length and row.char_budget:
            low = max(1, int(row.char_budget * 0.92))
            high = int(row.char_budget * 1.08)
            if len(final) < low or len(final) > high:
                final = original_body
                reasons.append("kept original; rewrite did not match the original bullet length")

        if strict_timeline:
            violations = timeline_violations(final, row.end_year)
            if violations:
                final = original_body
                names = ", ".join(str(v["technology"]) for v in violations)
                reasons.append(f"kept original; {names} launched after this role ended")
                warnings.append(
                    {
                        "id": pid,
                        "type": "timeline",
                        "detail": violations,
                    }
                )

        changed = _strip_glyph(final) != original_body
        if changed:
            applied[pid] = final
        report.append(
            {
                "id": pid,
                "role": row.role_title,
                "dates": row.role_dates,
                "original": original_body,
                "rewritten": _strip_glyph(final),
                "changed": changed,
                "reason": "; ".join(reasons) if reasons else str(item.get("reason") or ""),
                "char_original": row.char_budget,
                "char_new": len(_strip_glyph(final)),
            }
        )

    for pid, row in by_id.items():
        if pid not in seen:
            original_body = _strip_glyph(row.text)
            report.append(
                {
                    "id": pid,
                    "role": row.role_title,
                    "dates": row.role_dates,
                    "original": original_body,
                    "rewritten": original_body,
                    "changed": False,
                    "reason": "model omitted this bullet; left unchanged",
                    "char_original": row.char_budget,
                    "char_new": row.char_budget,
                }
            )

    report.sort(key=lambda item: int(item["id"]))
    return applied, report, warnings
