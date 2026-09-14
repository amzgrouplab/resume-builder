"""Replace bullet text in an existing Word document without touching layout."""

from __future__ import annotations

from copy import deepcopy

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from lxml import etree

from .parse_resume import ResumeParagraph, _iter_body_paragraphs, _prefix_of


def _first_run_properties(paragraph: Paragraph) -> etree._Element | None:
    for run in paragraph._p.findall(qn("w:r")):
        text_nodes = [t for t in run.findall(qn("w:t")) if (t.text or "").strip()]
        if not text_nodes:
            continue
        rpr = run.find(qn("w:rPr"))
        return deepcopy(rpr) if rpr is not None else None
    return None


def replace_paragraph_text(paragraph: Paragraph, new_text: str, manual_prefix: str = "") -> None:
    """Keep paragraph properties, numbering, and the dominant run style."""
    p_elm = paragraph._p
    rpr = _first_run_properties(paragraph)
    prefix = manual_prefix or _prefix_of(paragraph.text.lstrip())
    payload = new_text.strip()
    if prefix and not payload.startswith(prefix.strip()[0] if prefix.strip() else "\u2022"):
        # Only re-apply a visible glyph when Word is not numbering the paragraph.
        if p_elm.pPr is None or p_elm.pPr.find(qn("w:numPr")) is None:
            payload = f"{prefix}{payload}"

    for child in list(p_elm):
        if child.tag in {qn("w:r"), qn("w:hyperlink"), qn("w:ins"), qn("w:del"), qn("w:proofErr"), qn("w:bookmarkStart"), qn("w:bookmarkEnd")}:
            p_elm.remove(child)

    run = etree.SubElement(p_elm, qn("w:r"))
    if rpr is not None:
        run.append(rpr)
    text_node = etree.SubElement(run, qn("w:t"))
    text_node.set(qn("xml:space"), "preserve")
    text_node.text = payload


def apply_bullet_updates(
    doc: Document,
    rows: list[ResumeParagraph],
    updates: dict[int, str],
) -> int:
    paragraphs = list(_iter_body_paragraphs(doc))
    changed = 0
    for row in rows:
        if row.id not in updates:
            continue
        if not row.is_bullet:
            continue
        new_text = updates[row.id].strip()
        if not new_text or new_text == row.text:
            continue
        paragraph, _in_table = paragraphs[row.id]
        replace_paragraph_text(paragraph, new_text, manual_prefix=row.manual_prefix)
        changed += 1
    return changed
