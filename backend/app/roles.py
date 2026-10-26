"""Configurable role profiles. Add a JSON record to support a new discipline."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(__file__).resolve().parent / "config"
PROFILES_PATH = CONFIG_DIR / "role_profiles.json"
TAXONOMY_PATH = CONFIG_DIR / "taxonomy.json"


@lru_cache(maxsize=1)
def _load_roles() -> list[dict[str, Any]]:
    data = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
    return list(data.get("roles") or [])


@lru_cache(maxsize=1)
def load_taxonomy() -> dict[str, Any]:
    return json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))


def list_role_profiles() -> list[dict[str, Any]]:
    return [
        {
            "roleId": item["roleId"],
            "displayName": item["displayName"],
            "roleFamily": item.get("roleFamily") or "",
            "aliases": item.get("aliases") or [],
            "seniorityHints": item.get("seniorityHints") or [],
        }
        for item in _load_roles()
    ]


def get_role_profile(role_id: str) -> dict[str, Any] | None:
    wanted = (role_id or "").strip().lower()
    if not wanted:
        return None
    for item in _load_roles():
        if item["roleId"].lower() == wanted:
            return deepcopy(item)
    return None


def _blob(*parts: str) -> str:
    return " ".join(part for part in parts if part).lower()


def infer_role_profile(job_description: str, target_role: str = "") -> dict[str, Any]:
    """Pick the best configured profile from the JD and optional user choice."""
    text = _blob(job_description, target_role)
    ranked: list[tuple[int, dict[str, Any]]] = []
    for item in _load_roles():
        if item["roleId"] == "custom":
            continue
        score = 0
        names = [item["displayName"], item.get("roleFamily") or "", *(item.get("aliases") or [])]
        for name in names:
            needle = name.lower().strip()
            if needle and needle in text:
                score += 4 if len(needle) > 8 else 2
            tokens = [token for token in re.findall(r"[a-z]{4,}", needle) if token not in {"engineer", "software", "senior"}]
            if tokens and all(token in text for token in tokens):
                score += 3
        if score:
            ranked.append((score, item))
    if ranked:
        ranked.sort(key=lambda pair: (-pair[0], pair[1]["displayName"]))
        return deepcopy(ranked[0][1])
    return deepcopy(get_role_profile("custom") or _load_roles()[-1])


def resolve_role_profile(
    *,
    job_description: str,
    selected_role_id: str = "",
    inferred_role: str = "",
) -> dict[str, Any]:
    """User selection wins as preference; JD inference can add a hybrid emphasis."""
    selected = get_role_profile(selected_role_id)
    inferred = infer_role_profile(job_description, inferred_role)
    if selected is None or selected["roleId"] == "custom":
        return inferred
    if inferred["roleId"] == selected["roleId"]:
        return selected
    merged = deepcopy(selected)
    extra = inferred.get("writingEmphasis") or ""
    own = merged.get("writingEmphasis") or ""
    if extra and extra not in own:
        merged["writingEmphasis"] = own + " Also honor this JD specialization: " + extra
        merged["hybridWith"] = inferred["roleId"]
    aliases = list(dict.fromkeys([*(merged.get("aliases") or []), *(inferred.get("aliases") or [])]))
    merged["aliases"] = aliases
    return merged


def writing_strategy(profile: dict[str, Any] | None) -> str:
    if not profile:
        return (
            "Write for the actual job description and the candidate's evidenced work. "
            "Do not assume a software-engineering stack."
        )
    return str(profile.get("writingEmphasis") or "")
