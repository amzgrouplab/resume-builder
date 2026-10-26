"""Local API for Vellum: parse a Word resume and tailor only its bullets."""

from __future__ import annotations

import base64
import io
import tempfile
import time
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from anthropic import APIConnectionError as AnthropicConnectionError
from anthropic import APITimeoutError as AnthropicTimeoutError
from anthropic import AuthenticationError as AnthropicAuthError
from anthropic import RateLimitError as AnthropicRateLimitError
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    NotFoundError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)
from pydantic import BaseModel, Field

from .keywords import coverage, extract_jd_stack
from .parse_resume import parse_document, summarize_parse
from .profiles import create_profile, delete_profile, get_profile, list_profiles, resume_path
from .roles import list_role_profiles, load_taxonomy, resolve_role_profile
from .tailor import ANTHROPIC_MODELS, extract_jd_stack_llm, provider_for, tailor_bullets, validate_updates
from .write_resume import apply_bullet_updates

PRESENT_YEAR = 2026
OPENAI_MODELS = {
    "gpt-4o",
    "gpt-4.1",
    "gpt-4o-mini",
    "gpt-5",
    "gpt-5-mini",
}
ALLOWED_MODELS = OPENAI_MODELS | ANTHROPIC_MODELS

app = FastAPI(title="Vellum", version="1.0.0")
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:8001",
        "http://localhost:8001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class KeyTestBody(BaseModel):
    api_key: str = Field(min_length=10)
    model: str = "gpt-4o"
    provider: str = "openai"


def _require_docx_name(name: str) -> None:
    if not (name or "").lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Please upload a .docx Word resume.")


def _save_upload(file: UploadFile) -> str:
    suffix = Path(file.filename or "resume.docx").suffix or ".docx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        handle.write(file.file.read())
        return handle.name


def _error_fields(exc: BaseException) -> tuple[str | None, str]:
    body = getattr(exc, "body", None)
    code = getattr(exc, "code", None)
    message = str(getattr(exc, "message", None) or exc).strip()
    if isinstance(body, dict):
        err = body.get("error") if isinstance(body.get("error"), dict) else body
        if isinstance(err, dict):
            code = err.get("code") or err.get("type") or code
            message = str(err.get("message") or message).strip()
    return (str(code) if code else None), message


def _looks_like_quota(code: str | None, message: str) -> bool:
    blob = f"{code or ''} {message}".lower()
    return any(token in blob for token in ("insufficient_quota", "quota", "billing", "credit balance", "exceeded your current quota"))


def provider_http_error(exc: BaseException, provider: str) -> tuple[int, str]:
    label = "Anthropic" if provider == "anthropic" else "OpenAI"
    code, message = _error_fields(exc)
    if isinstance(exc, (AuthenticationError, AnthropicAuthError)):
        return 401, f"That {label} API key was rejected."
    if isinstance(exc, (APITimeoutError, AnthropicTimeoutError)):
        return 504, f"{label} is still working through a long resume. Retry; Vellum waits up to 3 minutes per role."
    if isinstance(exc, (APIConnectionError, AnthropicConnectionError)):
        return 502, f"Could not reach {label}. Check your network and retry."
    if isinstance(exc, (RateLimitError, AnthropicRateLimitError)):
        if _looks_like_quota(code, message):
            return 429, (
                f"{label} reports this key has no remaining quota. "
                "Add billing credits, or switch provider in Settings."
            )
        return 429, f"{label} rate-limited the request. Wait a moment and retry."
    if isinstance(exc, NotFoundError):
        return 400, f"{label} does not offer that model on this key. Pick another model in Settings."
    if isinstance(exc, PermissionDeniedError):
        return 403, f"{label} denied this model for this key. Check project access or pick another model."
    if isinstance(exc, APIStatusError):
        status = int(getattr(exc, "status_code", 400) or 400)
        return status, message or f"{label} returned an error."
    return 400, message or f"{label} returned an error."


def _key(value: str | None, provider: str) -> str:
    key = (value or "").strip()
    label = "Anthropic" if provider == "anthropic" else "OpenAI"
    if not key:
        raise HTTPException(status_code=401, detail=f"Add your {label} API key in Settings.")
    return key


def _resolve_resume(resume: UploadFile | None, profile_id: str) -> tuple[str, str, bool]:
    profile_id = (profile_id or "").strip()
    if profile_id:
        try:
            meta = get_profile(profile_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="That profile was not found.") from exc
        return str(resume_path(profile_id)), str(meta.get("filename") or "resume.docx"), False
    if resume is None or not resume.filename:
        raise HTTPException(status_code=400, detail="Select a saved profile or upload a Word resume.")
    _require_docx_name(resume.filename)
    return _save_upload(resume), resume.filename, True


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/settings/test")
def test_key(body: KeyTestBody) -> dict[str, Any]:
    provider = provider_for(body.model, body.provider)
    if body.model not in ALLOWED_MODELS:
        raise HTTPException(status_code=400, detail="Choose a supported model in Settings.")
    if provider == "anthropic" and body.model not in ANTHROPIC_MODELS:
        raise HTTPException(status_code=400, detail="Choose a Claude model for Anthropic.")
    if provider == "openai" and body.model not in OPENAI_MODELS:
        raise HTTPException(status_code=400, detail="Choose an OpenAI model for OpenAI.")
    try:
        if provider == "anthropic":
            client = Anthropic(api_key=body.api_key, timeout=12.0, max_retries=0)
            client.messages.create(
                model=body.model,
                max_tokens=8,
                messages=[{"role": "user", "content": "Reply with ok"}],
            )
        else:
            client = OpenAI(api_key=body.api_key, timeout=12.0, max_retries=0)
            client.models.retrieve(body.model)
    except Exception as exc:
        status, detail = provider_http_error(exc, provider)
        raise HTTPException(status_code=status, detail=detail) from exc
    return {"ok": True, "model": body.model, "provider": provider}


class StackBody(BaseModel):
    job_description: str = Field(min_length=20)
    model: str = "gpt-4o"
    provider: str = "openai"
    selected_role: str = ""
    seniority: str = ""


def _with_role(stack: dict[str, Any], job_description: str, selected_role: str = "") -> dict[str, Any]:
    profile = resolve_role_profile(
        job_description=job_description,
        selected_role_id=selected_role,
        inferred_role=str(stack.get("target_role") or stack.get("role_family") or ""),
    )
    stack = dict(stack)
    stack["role_id"] = profile.get("roleId") or ""
    stack["role_display"] = profile.get("displayName") or ""
    stack["role_family"] = stack.get("role_family") or profile.get("roleFamily") or ""
    return stack


@app.get("/api/roles")
def roles_catalog() -> dict[str, Any]:
    return {"roles": list_role_profiles()}


@app.get("/api/taxonomy")
def taxonomy_catalog() -> dict[str, Any]:
    return load_taxonomy()


@app.post("/api/stack")
def preview_stack(
    body: StackBody,
    x_openai_key: str | None = Header(default=None, alias="X-OpenAI-Key"),
    x_anthropic_key: str | None = Header(default=None, alias="X-Anthropic-Key"),
) -> dict[str, Any]:
    catalog = extract_jd_stack(body.job_description)
    chosen = provider_for(body.model, body.provider)
    key = ((x_anthropic_key if chosen == "anthropic" else x_openai_key) or "").strip()
    if not key:
        return _with_role(catalog, body.job_description, body.selected_role)
    try:
        stacked = extract_jd_stack_llm(
            api_key=key,
            model=body.model if body.model in ALLOWED_MODELS else ("claude-sonnet-4-5" if chosen == "anthropic" else "gpt-4o"),
            job_description=body.job_description,
            provider=chosen,
            selected_role=body.selected_role,
            seniority=body.seniority,
        )
        return _with_role(stacked, body.job_description, body.selected_role)
    except Exception:
        return _with_role(catalog, body.job_description, body.selected_role)


@app.get("/api/profiles")
def profiles() -> dict[str, Any]:
    return {"profiles": list_profiles()}


@app.post("/api/profiles")
async def add_profile(
    resume: UploadFile = File(...),
    name: str = Form(""),
) -> dict[str, Any]:
    _require_docx_name(resume.filename or "")
    path = _save_upload(resume)
    try:
        return create_profile(name, path, resume.filename or "resume.docx")
    finally:
        Path(path).unlink(missing_ok=True)


@app.get("/api/profiles/{profile_id}")
def profile_detail(profile_id: str) -> dict[str, Any]:
    try:
        return get_profile(profile_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="That profile was not found.") from exc


@app.delete("/api/profiles/{profile_id}")
def remove_profile(profile_id: str) -> dict[str, bool]:
    try:
        delete_profile(profile_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="That profile was not found.") from exc
    return {"ok": True}


@app.post("/api/parse")
async def parse_resume(
    resume: UploadFile | None = File(None),
    profile_id: str = Form(""),
) -> dict[str, Any]:
    path, filename, temporary = _resolve_resume(resume, profile_id)
    try:
        _doc, rows = parse_document(path, present_year=PRESENT_YEAR)
        summary = summarize_parse(rows)
        return {
            "filename": filename,
            "paragraphs": summary["paragraphs"],
            "bullets": summary["bullets"],
            "roles": summary["roles"],
            "profile_id": profile_id or None,
        }
    finally:
        if temporary:
            Path(path).unlink(missing_ok=True)


@app.post("/api/tailor")
async def tailor_resume(
    resume: UploadFile | None = File(None),
    profile_id: str = Form(""),
    job_description: str = Form(...),
    model: str = Form("gpt-4o"),
    provider: str = Form("openai"),
    strict_timeline: str = Form("true"),
    match_length: str = Form("true"),
    selected_role: str = Form(""),
    seniority: str = Form(""),
    x_openai_key: str | None = Header(default=None, alias="X-OpenAI-Key"),
    x_anthropic_key: str | None = Header(default=None, alias="X-Anthropic-Key"),
) -> dict[str, Any]:
    started = time.perf_counter()
    if model not in ALLOWED_MODELS:
        raise HTTPException(status_code=400, detail="Choose a supported model in Settings.")
    chosen = provider_for(model, provider)
    if chosen == "anthropic" and model not in ANTHROPIC_MODELS:
        raise HTTPException(status_code=400, detail="Choose a Claude model for Anthropic.")
    if chosen == "openai" and model not in OPENAI_MODELS:
        raise HTTPException(status_code=400, detail="Choose an OpenAI model for OpenAI.")
    jd = job_description.strip()
    if len(jd) < 40:
        raise HTTPException(status_code=400, detail="Paste a fuller job description so the rewrite can be specific.")
    api_key = _key(x_anthropic_key if chosen == "anthropic" else x_openai_key, chosen)
    path, filename, temporary = _resolve_resume(resume, profile_id)
    try:
        doc, rows = parse_document(path, present_year=PRESENT_YEAR)
        summary = summarize_parse(rows)
        editable = summary["bullets"] + int(summary.get("summaries") or 0)
        if editable == 0:
            raise HTTPException(
                status_code=400,
                detail="No summary or bullet points were detected. Vellum only rewrites those lines so your layout can stay identical.",
            )
        try:
            payload = tailor_bullets(
                api_key=api_key,
                model=model,
                job_description=jd,
                rows=rows,
                provider=chosen,
                selected_role=selected_role,
                seniority=seniority,
            )
        except (
            AuthenticationError,
            AnthropicAuthError,
            RateLimitError,
            AnthropicRateLimitError,
            APITimeoutError,
            AnthropicTimeoutError,
            APIConnectionError,
            AnthropicConnectionError,
            PermissionDeniedError,
            NotFoundError,
            APIStatusError,
        ) as exc:
            status, detail = provider_http_error(exc, chosen)
            raise HTTPException(status_code=status, detail=detail) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        applied, report, warnings = validate_updates(
            rows,
            payload,
            strict_timeline=strict_timeline.lower() == "true",
            match_length=match_length.lower() == "true",
            job_description=jd,
            jd_stack=payload.get("jd_stack"),
        )
        changed = apply_bullet_updates(doc, rows, applied)
        rewritten_blob = "\n".join(item["rewritten"] for item in report)
        stack = payload.get("jd_stack") or extract_jd_stack(jd)
        stack_coverage = coverage(stack, rewritten_blob)
        buffer = io.BytesIO()
        doc.save(buffer)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        original_name = Path(filename or "resume.docx").stem
        company = str(payload.get("company") or "").strip()
        target = str(payload.get("target_role") or "").strip()
        suffix_bits = [bit for bit in (company, target) if bit]
        suffix = ("_" + "_".join(suffix_bits)) if suffix_bits else "_tailored"
        out_name = f"{original_name}{suffix}.docx".replace(" ", "_")
        return {
            "filename": out_name,
            "docx_base64": base64.b64encode(buffer.getvalue()).decode("ascii"),
            "elapsed_ms": elapsed_ms,
            "target_role": target,
            "company": company,
            "notes": payload.get("notes") or [],
            "roles": summary["roles"],
            "bullets_total": summary["bullets"],
            "bullets_changed": changed,
            "updates": report,
            "warnings": warnings,
            "stack": {
                "required": stack.get("required") or [],
                "preferred": stack.get("preferred") or [],
                "domains": stack.get("domains") or [],
                "on_resume": payload.get("resume_stack") or [],
                "placed": stack_coverage.get("placed") or [],
                "missing": stack_coverage.get("missing") or [],
                "source": stack.get("source") or "catalog",
                "role_id": stack.get("role_id") or "",
                "role_display": stack.get("role_display") or "",
                "role_family": stack.get("role_family") or "",
                "seniority": stack.get("seniority") or seniority,
            },
            "role_profile": payload.get("role_profile") or {},
        }
    finally:
        if temporary:
            Path(path).unlink(missing_ok=True)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/styles.css")
def styles() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "styles.css", headers={"Cache-Control": "no-store"})


@app.get("/app.js")
def script() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "app.js", headers={"Cache-Control": "no-store"})
