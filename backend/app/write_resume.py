"""Replace bullet text in an existing Word document without touching layout."""

from __future__ import annotations

from copy import deepcopy

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from lxml import etree

from .parse_resume import ResumeParagraph, _iter_body_paragraphs, _prefix_of


def _run_text_len(run: etree._Element) -> int:
    return sum(len(node.text or "") for node in run.findall(qn("w:t")))


def _dominant_run_properties(paragraph: Paragraph) -> etree._Element | None:
    """Use the run that holds most of the sentence so color/font stay with the body text."""
    runs = [node for node in paragraph._p.iter() if node.tag == qn("w:r")]
    if not runs:
        return None
    ranked = sorted(runs, key=_run_text_len, reverse=True)
    for run in ranked:
        if _run_text_len(run) <= 0:
            continue
        rpr = run.find(qn("w:rPr"))
        if rpr is not None:
            return deepcopy(rpr)
    for run in ranked:
        rpr = run.find(qn("w:rPr"))
        if rpr is not None:
            return deepcopy(rpr)
    return None


def replace_paragraph_text(paragraph: Paragraph, new_text: str, manual_prefix: str = "") -> None:
    """Keep paragraph properties, numbering, and the dominant run style."""
    p_elm = paragraph._p
    rpr = _dominant_run_properties(paragraph)
    if rpr is None:
        ppr = paragraph._p.find(qn("w:pPr"))
        if ppr is not None:
            para_rpr = ppr.find(qn("w:rPr"))
            if para_rpr is not None:
                rpr = deepcopy(para_rpr)
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
        if not row.is_bullet and not row.is_summary:
            continue
        new_text = updates[row.id].strip()
        if not new_text or new_text == row.text:
            continue
        paragraph, _in_table = paragraphs[row.id]
        replace_paragraph_text(paragraph, new_text, manual_prefix=row.manual_prefix)
        changed += 1
    return changed
