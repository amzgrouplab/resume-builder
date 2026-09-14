"""Local API for Vellum: parse a Word resume and tailor only its bullets."""

from __future__ import annotations

import base64
import io
import tempfile
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from openai import AuthenticationError, APIConnectionError, APITimeoutError, OpenAI, RateLimitError
from pydantic import BaseModel, Field

from .parse_resume import parse_document, summarize_parse
from .profiles import create_profile, delete_profile, get_profile, list_profiles, resume_path
from .tailor import tailor_bullets, validate_updates
from .write_resume import apply_bullet_updates

PRESENT_YEAR = 2026
ALLOWED_MODELS = {
    "gpt-4o",
    "gpt-4.1",
    "gpt-4o-mini",
    "gpt-5",
    "gpt-5-mini",
}

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


def _require_docx_name(name: str) -> None:
    if not (name or "").lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Please upload a .docx Word resume.")


def _save_upload(file: UploadFile) -> str:
    suffix = Path(file.filename or "resume.docx").suffix or ".docx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        handle.write(file.file.read())
        return handle.name


def _key(x_openai_key: str | None) -> str:
    key = (x_openai_key or "").strip()
    if not key:
        raise HTTPException(status_code=401, detail="Add your OpenAI API key in Settings.")
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
    try:
        client = OpenAI(api_key=body.api_key, timeout=12.0, max_retries=0)
        client.models.retrieve(body.model)
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail="That OpenAI API key was rejected.") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "model": body.model}


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
    strict_timeline: str = Form("true"),
    match_length: str = Form("true"),
    x_openai_key: str | None = Header(default=None, alias="X-OpenAI-Key"),
) -> dict[str, Any]:
    started = time.perf_counter()
    if model not in ALLOWED_MODELS:
        raise HTTPException(status_code=400, detail="Choose a supported OpenAI model in Settings.")
    jd = job_description.strip()
    if len(jd) < 40:
        raise HTTPException(status_code=400, detail="Paste a fuller job description so the rewrite can be specific.")
    api_key = _key(x_openai_key)
    path, filename, temporary = _resolve_resume(resume, profile_id)
    try:
        doc, rows = parse_document(path, present_year=PRESENT_YEAR)
        summary = summarize_parse(rows)
        if summary["bullets"] == 0:
            raise HTTPException(
                status_code=400,
                detail="No bullet points were detected. Vellum only rewrites list items so your layout can stay identical.",
            )
        try:
            payload = tailor_bullets(
                api_key=api_key,
                model=model,
                job_description=jd,
                rows=rows,
            )
        except AuthenticationError as exc:
            raise HTTPException(status_code=401, detail="That OpenAI API key was rejected.") from exc
        except RateLimitError as exc:
            raise HTTPException(status_code=429, detail="OpenAI rate-limited the request. Wait a moment and retry.") from exc
        except APITimeoutError as exc:
            raise HTTPException(
                status_code=504,
                detail="OpenAI is still working through a long resume. Retry; Vellum now waits up to 3 minutes per role.",
            ) from exc
        except APIConnectionError as exc:
            raise HTTPException(status_code=502, detail="Could not reach OpenAI. Check your network and retry.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        applied, report, warnings = validate_updates(
            rows,
            payload,
            strict_timeline=strict_timeline.lower() == "true",
            match_length=match_length.lower() == "true",
        )
        changed = apply_bullet_updates(doc, rows, applied)
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
