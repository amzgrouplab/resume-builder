"""OpenAI rewrite of resume bullets, constrained to truth, dates, stack, and length."""

from __future__ import annotations

import json
import re
from typing import Any

from anthropic import Anthropic
from openai import OpenAI

from .keywords import (
    allowed_for_group,
    ensure_mention_targets,
    extract_jd_stack,
    inject_missing_keywords,
    is_keyword_dump,
    is_skills_or_summary,
    merge_jd_stacks,
    polish_sentence,
    resume_inventory,
    stack_from_llm_payload,
)
from .parse_resume import ResumeParagraph
from .roles import resolve_role_profile, writing_strategy
from .timeline import (
    format_timeline_for_prompt,
    relevant_timeline,
    tech_index,
    technologies_in_text,
    timeline_violations,
)

CORE_SYSTEM_PROMPT = """You are a precise resume editor for a real candidate on a role-agnostic platform.

Rewrite existing work, summary, and skills lines so they align with REQUIRED and PREFERRED
skills from THIS job description. The document layout is frozen. Only wording may change.

Do not assume the candidate is a full-stack software engineer. Do not default to Java, React,
or Spring Boot. Use only tools and responsibilities supported by the original lines and the
TARGET STACK for this posting.

Write like a hiring manager would believe a person wrote it: clear, specific, professional.
Keep the original voice and the real project.

Hard rules:
1. Return JSON only.
2. Include in `updates` every line you were given. If a line should stay, return the original text.
3. Never add or delete lines. Never change ids, employers, titles, dates, or education.
4. Do not invent metrics, customers, awards, headcount, employers, or tools.
5. Keep the real project. Preserve named systems, products, pipelines, models, and implementation details.
6. Do not replace concrete work with generic consulting language unless that work is already in the line.
7. Weave REQUIRED/PREFERRED skills using the exact JD wording by swapping close phrasing already in the line. One or two skills per bullet. Never append a comma-dump.
8. You may use TARGET STACK skills this resume already supports with related work. Never use BLOCKED tools. Never invent a vendor product with no related evidence.
9. Skills and summary lines should name the TARGET STACK the resume actually supports, as a readable list or sentence.
10. `rewritten` MUST be within ±10% of `char_budget` characters.
11. Technology dates are binding. If a tool launched after a role ended, it must not appear there.
12. Do not move a later stack into an earlier role. Do not convert one cloud into another.
13. No bullet glyphs such as •.
14. No AI filler: leveraged, utilized, spearheaded, robust, cutting-edge, synergy.
15. No repeated commas, trailing commas, or empty list items.
16. Mention each REQUIRED and PREFERRED skill in as many date-safe lines as it honestly fits. Keep existing mentions; never remove them. At most once per bullet.
17. If TARGET STACK includes a programming language and the line already names another language, pair them naturally using the JD name (Python and Go, Python/Go). Never invent a language from BLOCKED or NOT ON THIS RESUME.

JSON:
{"target_role":"","company":"","updates":[{"id":12,"rewritten":"...","reason":"≤8 words"}],"notes":[]}
"""

SYSTEM_PROMPT = CORE_SYSTEM_PROMPT

EXTRACT_SYSTEM = """You analyze a job description for a centralized, role-agnostic resume platform.

Return JSON only:
{
  "target_role":"",
  "company":"",
  "role_family":"ai_ml|agentic_ai|ai_platform|ai_architecture|mlops|data_science|data_engineering|software|cloud_devops|custom",
  "specialization":"",
  "seniority":"junior|mid|senior|staff|principal",
  "required":["Python"],
  "preferred":["Salesforce"],
  "domains":["healthcare"],
  "priority":["Python"],
  "architecture":["distributed systems"],
  "responsibilities":["own production reliability"]
}

required: every must-have technology, language, platform, framework, protocol, library, method, and hard skill in qualifications, responsibilities, and stack lists.
preferred: nice-to-have / bonus tools.
domains: industry or work context only.
priority: the most important required items first.
architecture: architecture expectations named in the posting.
responsibilities: professional duties, not tools.

Rules:
1. Only terms clearly present in the posting. Do not invent tools.
2. Keep the posting's own skill names when they are specific (API design, multi-agent coordination, secure SDLC).
3. Split lists. Pull tools out of parentheses and slash lists (TypeScript, Go, or Java → three items).
4. Skip soft skills, degrees, years of experience, salary, and location.
5. Be exhaustive. 12–60 required items is fine. This feed drives ATS coverage.
6. role_family must be one of the enum values. Hybrid postings still pick the primary family and put the rest in specialization.
"""

OPENAI_TIMEOUT_SEC = 180.0
LENGTH_LOW = 0.90
LENGTH_HIGH = 1.10
ANTHROPIC_MODELS = {
    "claude-sonnet-4-5",
    "claude-opus-4-5",
    "claude-opus-4-1",
    "claude-haiku-4-5",
}


def provider_for(model: str, provider: str = "") -> str:
    chosen = (provider or "").strip().lower()
    if chosen in {"openai", "anthropic"}:
        return chosen
    if (model or "").startswith("claude"):
        return "anthropic"
    return "openai"


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise ValueError("The model did not return valid JSON. Try again.")
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("The model did not return a JSON object.")
    return parsed


def _parse_model_json(raw: str) -> dict[str, Any]:
    parsed = _parse_json_object(raw)
    if "updates" not in parsed:
        raise ValueError("The model response was missing updates.")
    return parsed


def _tailorable(row: ResumeParagraph) -> bool:
    return bool(row.text) and (row.is_bullet or row.is_summary)


def _frozen_context(rows: list[ResumeParagraph], limit: int = 24) -> str:
    lines: list[str] = []
    for row in rows:
        if _tailorable(row) or not row.text:
            continue
        lines.append(f"[FROZEN {row.id}] {row.text}")
        if len(lines) >= limit:
            break
    return "\n".join(lines)


def _line_body(row: ResumeParagraph) -> str:
    body = row.text
    if row.manual_prefix:
        body = body[len(row.manual_prefix) :].strip()
    return body


def _bullet_block(bullets: list[ResumeParagraph]) -> str:
    lines = ["id | role | years | end | char_budget | original"]
    for row in bullets:
        end = row.end_year if row.end_year is not None else "?"
        role = re.sub(r"\s+", " ", row.role_title or "Unknown")
        years = row.role_dates or "?"
        lines.append(f"{row.id} | {role} | {years} | {end} | {row.char_budget} | {_line_body(row)}")
    return "\n".join(lines)


def _openai_client(api_key: str) -> OpenAI:
    return OpenAI(api_key=api_key, timeout=OPENAI_TIMEOUT_SEC, max_retries=1)


def _anthropic_client(api_key: str) -> Anthropic:
    return Anthropic(api_key=api_key, timeout=OPENAI_TIMEOUT_SEC, max_retries=1)


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


def _stack_block(allowed: dict[str, list[str]]) -> str:
    weave = ", ".join(allowed["weave"]) or "(none — keep original tools)"
    blocked = "; ".join(allowed["blocked"]) or "none"
    missing = ", ".join(allowed["missing"]) or "none"
    required = ", ".join(allowed.get("required") or allowed.get("priority") or [])
    preferred = ", ".join(allowed.get("preferred") or [])
    block = (
        f"TARGET STACK (weave these into this group by swapping words, not dumping a list):\n{weave}\n\n"
        f"BLOCKED FOR THIS ROLE (launch date):\n{blocked}\n\n"
        f"NOT ON THIS RESUME (do not invent):\n{missing}\n"
    )
    if required:
        block += (
            "\nREQUIRED (mention in every date-safe line where it honestly fits; "
            "keep existing mentions; at most once per line):\n"
            f"{required}\n"
        )
    if preferred:
        block += (
            "\nPREFERRED (mention in every date-safe line where it honestly fits; "
            "keep existing mentions; at most once per line):\n"
            f"{preferred}\n"
        )
    return block


def _user_prompt(
    *,
    job_description: str,
    timeline_text: str,
    frozen: str,
    bullets: list[ResumeParagraph],
    allowed: dict[str, list[str]],
    strategy: str = "",
    target_role: str = "",
    seniority: str = "",
) -> str:
    heading = ""
    if target_role or seniority or strategy:
        heading = (
            f"TARGET ROLE: {target_role or 'infer from the job description'}\n"
            f"SENIORITY: {seniority or 'infer from the job description'}\n"
            f"WRITING STRATEGY:\n{strategy or 'Follow the job description and evidenced experience.'}\n\n"
        )
    return (
        heading
        + "JOB DESCRIPTION:\n"
        f"{job_description.strip()}\n\n"
        f"{_stack_block(allowed)}\n"
        "LAUNCH DATES (do not place a tool in a role that ended before it launched):\n"
        f"{timeline_text}\n\n"
        "HEADERS (read-only):\n"
        f"{frozen}\n\n"
        "Rewrite EVERY line below so it sounds like the candidate wrote it — professional, specific, human. "
        "Keep the real project, weave REQUIRED/PREFERRED skills by swapping words, "
        "pair related languages already in the line (Python and Go), "
        "never emit repeated commas, and hit char_budget ±10%:\n"
        f"{_bullet_block(bullets)}\n"
    )


def _openai_output_text(response: Any) -> str:
    text = getattr(response, "output_text", None)
    if text:
        return str(text)
    chunks: list[str] = []
    for item in getattr(response, "output", None) or []:
        for content in getattr(item, "content", None) or []:
            value = getattr(content, "text", None)
            if value:
                chunks.append(str(value))
    return "\n".join(chunks)


def _openai_json(
    client: OpenAI,
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    if hasattr(client, "responses"):
        try:
            response = client.responses.create(
                model=model,
                instructions=system,
                input=user,
                max_output_tokens=max_tokens,
                temperature=temperature,
            )
            return _parse_json_object(_openai_output_text(response) or "{}")
        except Exception:
            pass
    response = client.chat.completions.create(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return _parse_json_object(response.choices[0].message.content or "{}")


def _call_openai(client: OpenAI, model: str, user_prompt: str, max_tokens: int) -> dict[str, Any]:
    parsed = _openai_json(client, model, SYSTEM_PROMPT, user_prompt, max_tokens, 0.2)
    if "updates" not in parsed:
        raise ValueError("The model response was missing updates.")
    return parsed


def _call_anthropic(client: Anthropic, model: str, user_prompt: str, max_tokens: int) -> dict[str, Any]:
    response = client.messages.create(
        model=model,
        temperature=0.2,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    raw = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
    return _parse_model_json(raw or "{}")


def _call_model(
    *,
    provider: str,
    openai_client: OpenAI | None,
    anthropic_client: Anthropic | None,
    model: str,
    job_description: str,
    timeline_text: str,
    frozen: str,
    bullets: list[ResumeParagraph],
    allowed: dict[str, list[str]],
    strategy: str = "",
    target_role: str = "",
    seniority: str = "",
) -> dict[str, Any]:
    user_prompt = _user_prompt(
        job_description=job_description,
        timeline_text=timeline_text,
        frozen=frozen,
        bullets=bullets,
        allowed=allowed,
        strategy=strategy,
        target_role=target_role,
        seniority=seniority,
    )
    max_tokens = min(8000, 700 + (len(bullets) * 220))
    if provider == "anthropic":
        if anthropic_client is None:
            raise ValueError("Add your Anthropic API key in Settings.")
        return _call_anthropic(anthropic_client, model, user_prompt, max_tokens)
    if openai_client is None:
        raise ValueError("Add your OpenAI API key in Settings.")
    return _call_openai(openai_client, model, user_prompt, max_tokens)


def _extract_json(
    *,
    provider: str,
    openai_client: OpenAI | None,
    anthropic_client: Anthropic | None,
    model: str,
    job_description: str,
    resume_excerpt: str = "",
    selected_role: str = "",
    seniority: str = "",
) -> dict[str, Any]:
    user = "JOB DESCRIPTION:\n" + job_description.strip()
    if selected_role:
        user += f"\n\nUSER-SELECTED TARGET ROLE: {selected_role}"
    if seniority:
        user += f"\nUSER-SELECTED SENIORITY: {seniority}"
    if resume_excerpt:
        user += "\n\nCANDIDATE EVIDENCE (do not invent beyond this):\n" + resume_excerpt.strip()
    if provider == "anthropic":
        if anthropic_client is None:
            raise ValueError("Add your Anthropic API key in Settings.")
        response = anthropic_client.messages.create(
            model=model,
            temperature=0,
            max_tokens=4000,
            system=EXTRACT_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        raw = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
        return _parse_json_object(raw or "{}")
    if openai_client is None:
        raise ValueError("Add your OpenAI API key in Settings.")
    return _openai_json(openai_client, model, EXTRACT_SYSTEM, user, 4000, 0)


def _attach_analysis(merged: dict[str, Any], payload: dict[str, Any], profile: dict[str, Any] | None) -> dict[str, Any]:
    for key in ("target_role", "company", "role_family", "specialization", "seniority"):
        value = payload.get(key)
        if value:
            merged[key] = str(value)
    if payload.get("architecture"):
        merged["architecture"] = [str(item) for item in payload.get("architecture") or [] if item]
    if payload.get("responsibilities"):
        merged["responsibilities"] = [str(item) for item in payload.get("responsibilities") or [] if item]
    if profile:
        merged["role_id"] = profile.get("roleId") or ""
        merged["role_display"] = profile.get("displayName") or ""
        if profile.get("hybridWith"):
            merged["hybrid_with"] = profile.get("hybridWith")
    return merged


def extract_jd_stack_llm(
    *,
    api_key: str,
    model: str,
    job_description: str,
    provider: str = "openai",
    selected_role: str = "",
    seniority: str = "",
    resume_excerpt: str = "",
) -> dict[str, list[str]]:
    catalog = extract_jd_stack(job_description)
    chosen = provider_for(model, provider)
    openai_client = _openai_client(api_key) if chosen == "openai" else None
    anthropic_client = _anthropic_client(api_key) if chosen == "anthropic" else None
    payload = _extract_json(
        provider=chosen,
        openai_client=openai_client,
        anthropic_client=anthropic_client,
        model=model,
        job_description=job_description,
        resume_excerpt=resume_excerpt,
        selected_role=selected_role,
        seniority=seniority,
    )
    llm = stack_from_llm_payload(payload)
    if not llm["all"]:
        profile = resolve_role_profile(
            job_description=job_description,
            selected_role_id=selected_role,
            inferred_role=str(payload.get("target_role") or ""),
        )
        return _attach_analysis({**catalog, "source": catalog.get("source") or "catalog"}, payload, profile)
    merged = merge_jd_stacks(llm, catalog)
    merged["source"] = "llm"
    profile = resolve_role_profile(
        job_description=job_description,
        selected_role_id=selected_role,
        inferred_role=str(payload.get("target_role") or payload.get("role_family") or ""),
    )
    return _attach_analysis(merged, payload, profile)


def _resume_excerpt(rows: list[ResumeParagraph], limit: int = 40) -> str:
    lines: list[str] = []
    for row in rows:
        if not row.text:
            continue
        if not (row.is_bullet or row.is_summary):
            continue
        lines.append(row.text.strip())
        if len(lines) >= limit:
            break
    return "\n".join(lines)


def tailor_bullets(
    *,
    api_key: str,
    model: str,
    job_description: str,
    rows: list[ResumeParagraph],
    provider: str = "openai",
    selected_role: str = "",
    seniority: str = "",
) -> dict[str, Any]:
    bullets = [r for r in rows if _tailorable(r)]
    if not bullets:
        raise ValueError("No rewriteable summary or bullet points were found in this Word resume.")

    catalog = extract_jd_stack(job_description)
    chosen = provider_for(model, provider)
    openai_client = _openai_client(api_key) if chosen == "openai" else None
    anthropic_client = _anthropic_client(api_key) if chosen == "anthropic" else None
    excerpt = _resume_excerpt(rows)
    try:
        extracted = _extract_json(
            provider=chosen,
            openai_client=openai_client,
            anthropic_client=anthropic_client,
            model=model,
            job_description=job_description,
            resume_excerpt=excerpt,
            selected_role=selected_role,
            seniority=seniority,
        )
        llm = stack_from_llm_payload(extracted)
        jd_stack = merge_jd_stacks(llm, catalog) if llm["all"] else catalog
        if llm["all"]:
            jd_stack["source"] = "llm"
    except ValueError:
        jd_stack = catalog
        extracted = {}
    profile = resolve_role_profile(
        job_description=job_description,
        selected_role_id=selected_role,
        inferred_role=str(extracted.get("target_role") or extracted.get("role_family") or ""),
    )
    jd_stack = _attach_analysis(jd_stack, extracted, profile)
    strategy = writing_strategy(profile)
    inventory = resume_inventory(rows)
    index = tech_index()
    timeline_text = format_timeline_for_prompt(
        relevant_timeline([job_description, *[r.text for r in rows if r.text]])
    )
    frozen = _frozen_context(rows)
    merged: list[dict[str, Any]] = []
    notes: list[str] = []
    target_role = str(extracted.get("target_role") or profile.get("displayName") or "")
    company = str(extracted.get("company") or "")
    seniority_label = seniority or str(extracted.get("seniority") or "")
    for group in _group_bullets(bullets):
        role_title = group[0].role_title or ""
        role_names = set(inventory["by_role"].get(role_title, set()))
        for row in group:
            role_names.update(t.name for t in technologies_in_text(_line_body(row)))
        skills = all(is_skills_or_summary(row) for row in group)
        end_years = [row.end_year for row in group if row.end_year is not None]
        allowed = allowed_for_group(
            jd_stack=jd_stack,
            resume_names=inventory["overall"],
            role_names=role_names,
            role_end_year=max(end_years) if end_years and not skills else None,
            is_skills_or_summary=skills,
            tech_by_name=index,
            is_current_role=any(row.is_current_role for row in group),
        )
        payload = _call_model(
            provider=chosen,
            openai_client=openai_client,
            anthropic_client=anthropic_client,
            model=model,
            job_description=job_description,
            timeline_text=timeline_text,
            frozen=frozen,
            bullets=group,
            allowed=allowed,
            strategy=strategy,
            target_role=target_role,
            seniority=seniority_label,
        )
        merged.extend(payload.get("updates") or [])
        notes.extend(str(item) for item in (payload.get("notes") or []) if item)
        target_role = str(payload.get("target_role") or target_role)
        company = str(payload.get("company") or company)
    prefix = "JD stack (LLM): " if jd_stack.get("source") == "llm" else "JD stack: "
    if jd_stack["all"]:
        notes.insert(0, prefix + ", ".join(jd_stack["all"][:60]))
    if profile.get("displayName"):
        hybrid = f" + {profile.get('hybridWith')}" if profile.get("hybridWith") else ""
        notes.insert(0, f"Role profile: {profile.get('displayName')}{hybrid}")
    return {
        "target_role": target_role,
        "company": company,
        "updates": merged,
        "notes": notes,
        "jd_stack": jd_stack,
        "resume_stack": sorted(inventory["overall"]),
        "role_profile": {
            "roleId": profile.get("roleId"),
            "displayName": profile.get("displayName"),
            "roleFamily": profile.get("roleFamily"),
            "hybridWith": profile.get("hybridWith"),
        },
    }


def _strip_glyph(text: str) -> str:
    return re.sub(r"^[\u2022\u25cf\u25e6\u25aa\u25ab\u2043\-–—]\s*", "", text.strip())


def validate_updates(
    rows: list[ResumeParagraph],
    model_payload: dict[str, Any],
    *,
    strict_timeline: bool,
    match_length: bool,
    job_description: str = "",
    jd_stack: dict[str, list[str]] | None = None,
) -> tuple[dict[int, str], list[dict[str, Any]], list[dict[str, Any]]]:
    by_id = {r.id: r for r in rows if _tailorable(r)}
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
        rewritten = polish_sentence(_strip_glyph(str(item.get("rewritten") or "").strip()))
        original_body = _strip_glyph(row.text)
        if not rewritten:
            rewritten = original_body
        if is_keyword_dump(original_body, rewritten):
            rewritten = original_body

        reasons: list[str] = []
        final = rewritten

        if match_length and row.char_budget:
            low = max(1, int(row.char_budget * LENGTH_LOW))
            high = int(row.char_budget * LENGTH_HIGH)
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

    if job_description:
        stack = jd_stack or extract_jd_stack(job_description)
        inventory = resume_inventory(rows)
        applied = inject_missing_keywords(
            rows,
            applied,
            jd_stack=stack,
            resume_names=inventory["overall"],
            match_length=match_length,
        )
        applied = ensure_mention_targets(
            rows,
            applied,
            jd_stack=stack,
            resume_names=inventory["overall"],
            match_length=match_length,
        )
        polished: dict[int, str] = {}
        for pid, text in applied.items():
            row = by_id.get(pid)
            if not row:
                continue
            cleaned = polish_sentence(text)
            if cleaned != _strip_glyph(row.text):
                polished[pid] = cleaned
        applied = polished
        by_report = {item["id"]: item for item in report}
        for pid, text in applied.items():
            row = by_id.get(pid)
            if not row:
                continue
            original_body = _strip_glyph(row.text)
            item = by_report.get(pid)
            changed = text != original_body
            if item:
                item["rewritten"] = text
                item["changed"] = changed
                item["char_new"] = len(text)
                if changed and "kept original" in (item.get("reason") or ""):
                    item["reason"] = "aligned wording to the job-description stack"
            elif changed:
                report.append(
                    {
                        "id": pid,
                        "role": row.role_title,
                        "dates": row.role_dates,
                        "original": original_body,
                        "rewritten": text,
                        "changed": True,
                        "reason": "aligned wording to the job-description stack",
                        "char_original": row.char_budget,
                        "char_new": len(text),
                    }
                )

    report.sort(key=lambda item: int(item["id"]))
    return applied, report, warnings
