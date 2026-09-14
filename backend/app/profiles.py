"""Save Word resumes as reusable local profiles."""

from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .parse_resume import parse_document, summarize_parse

ROOT = Path(__file__).resolve().parents[2] / "data" / "profiles"


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip()).strip("-").lower()
    return slug[:48] or "profile"


def _dir(profile_id: str) -> Path:
    return ROOT / profile_id


def _meta_path(profile_id: str) -> Path:
    return _dir(profile_id) / "meta.json"


def resume_path(profile_id: str) -> Path:
    return _dir(profile_id) / "resume.docx"


def list_profiles() -> list[dict[str, Any]]:
    if not ROOT.exists():
        return []
    rows: list[dict[str, Any]] = []
    for folder in ROOT.iterdir():
        meta_file = folder / "meta.json"
        if not meta_file.is_file():
            continue
        rows.append(json.loads(meta_file.read_text()))
    rows.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return rows


def get_profile(profile_id: str) -> dict[str, Any]:
    meta_file = _meta_path(profile_id)
    if not meta_file.is_file() or not resume_path(profile_id).is_file():
        raise FileNotFoundError(profile_id)
    return json.loads(meta_file.read_text())


def create_profile(name: str, source: str, filename: str) -> dict[str, Any]:
    cleaned = " ".join(name.split()) or Path(filename).stem
    profile_id = f"{_slug(cleaned)}-{uuid.uuid4().hex[:8]}"
    folder = _dir(profile_id)
    folder.mkdir(parents=True, exist_ok=True)
    dest = resume_path(profile_id)
    shutil.copy2(source, dest)
    _doc, rows = parse_document(str(dest))
    summary = summarize_parse(rows)
    meta = {
        "id": profile_id,
        "name": cleaned,
        "filename": filename,
        "paragraphs": summary["paragraphs"],
        "bullets": summary["bullets"],
        "roles": summary["roles"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _meta_path(profile_id).write_text(json.dumps(meta, indent=2))
    return meta


def delete_profile(profile_id: str) -> None:
    folder = _dir(profile_id)
    if not folder.exists():
        raise FileNotFoundError(profile_id)
    shutil.rmtree(folder)
