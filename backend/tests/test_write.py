from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor

from app.parse_resume import parse_document
from app.write_resume import apply_bullet_updates


def _sample_doc(path: Path) -> None:
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Inches(0.7)
    section.bottom_margin = Inches(0.7)
    section.left_margin = Inches(0.8)
    section.right_margin = Inches(0.8)

    name = doc.add_paragraph()
    run = name.add_run("Alex Rivera")
    run.bold = True
    run.font.name = "Calibri"
    run.font.size = Pt(22)
    run.font.color.rgb = RGBColor(0x17, 0x36, 0x5D)
    name.alignment = WD_ALIGN_PARAGRAPH.CENTER

    heading = doc.add_paragraph()
    hrun = heading.add_run("EXPERIENCE")
    hrun.bold = True
    hrun.font.name = "Calibri"
    hrun.font.size = Pt(12)

    role = doc.add_paragraph()
    rrun = role.add_run("Staff Engineer, Northwind  |  Jan 2018 – Dec 2020")
    rrun.bold = True
    rrun.font.name = "Calibri"
    rrun.font.size = Pt(11)

    bullets = [
        "Built Java 8 Spring Boot services for claims intake and reduced batch failures across nightly jobs.",
        "Designed PostgreSQL schemas and indexed queries that cut report time for finance operations.",
        "Automated Jenkins pipelines for test, package, and deploy of internal services.",
    ]
    for text in bullets:
        paragraph = doc.add_paragraph(text, style="List Bullet")
        for run in paragraph.runs:
            run.font.name = "Calibri"
            run.font.size = Pt(10.5)

    later = doc.add_paragraph()
    lrun = later.add_run("Staff Engineer, Contoso  |  Jan 2021 – Present")
    lrun.bold = True
    lrun.font.name = "Calibri"
    lrun.font.size = Pt(11)
    current = doc.add_paragraph(
        "Led platform work on AWS EKS and Terraform for regulated data products.",
        style="List Bullet",
    )
    for run in current.runs:
        run.font.name = "Calibri"
        run.font.size = Pt(10.5)

    doc.save(path)


def test_replace_keeps_list_and_font(tmp_path: Path) -> None:
    source = tmp_path / "resume.docx"
    _sample_doc(source)
    doc, rows = parse_document(str(source), present_year=2026)
    bullets = [r for r in rows if r.is_bullet]
    assert len(bullets) == 4
    target = bullets[0]
    apply_bullet_updates(
        doc,
        rows,
        {target.id: "Rebuilt Java 8 Spring Boot intake services and stabilized overnight claims processing."},
    )
    saved = tmp_path / "out.docx"
    doc.save(saved)

    again = Document(str(saved))
    updated = [p for p in again.paragraphs if p.text.startswith("Rebuilt Java 8")]
    assert updated
    paragraph = updated[0]
    assert paragraph.style.name == "List Bullet"
    run = paragraph.runs[0]
    assert run.font.size == Pt(10.5)
    heading = [p for p in again.paragraphs if p.text == "EXPERIENCE"][0]
    assert heading.runs[0].bold is True
    assert heading.runs[0].font.size == Pt(12)
    originals = [
        "Designed PostgreSQL schemas and indexed queries that cut report time for finance operations.",
        "Automated Jenkins pipelines for test, package, and deploy of internal services.",
    ]
    texts = [p.text for p in again.paragraphs]
    for original in originals:
        assert original in texts
    name = [p for p in again.paragraphs if p.text == "Alex Rivera"][0]
    assert name.runs[0].font.color.rgb == RGBColor(0x17, 0x36, 0x5D)
    assert name.alignment == WD_ALIGN_PARAGRAPH.CENTER


def test_parse_attaches_role_dates(tmp_path: Path) -> None:
    source = tmp_path / "resume.docx"
    _sample_doc(source)
    _doc, rows = parse_document(str(source), present_year=2026)
    bullets = [r for r in rows if r.is_bullet]
    assert bullets[0].end_year == 2020
    assert "Northwind" in bullets[0].role_title
    assert bullets[-1].is_current_role is True
    assert bullets[-1].end_year == 2026


def test_timeline_blocks_future_tools() -> None:
    from app.tailor import validate_updates
    from app.parse_resume import ResumeParagraph

    row = ResumeParagraph(
        id=3,
        text="Built Java 8 Spring Boot services for claims intake.",
        is_bullet=True,
        style_name="List Bullet",
        in_table=False,
        manual_prefix="",
        role_title="Staff Engineer, Northwind",
        role_dates="2018–2020",
        start_year=2018,
        end_year=2020,
        is_current_role=False,
        char_budget=52,
    )
    applied, report, warnings = validate_updates(
        [row],
        {
            "updates": [
                {
                    "id": 3,
                    "rewritten": "Built LangGraph agents with GPT-4o on Amazon Bedrock for claims intake.",
                    "changed": True,
                    "reason": "keyword stuffing",
                }
            ]
        },
        strict_timeline=True,
        match_length=False,
    )
    assert applied == {}
    assert report[0]["changed"] is False
    assert warnings and warnings[0]["type"] == "timeline"


def test_length_guard_keeps_layout() -> None:
    from app.tailor import validate_updates
    from app.parse_resume import ResumeParagraph

    original = "Built Java 8 services."
    row = ResumeParagraph(
        id=1,
        text=original,
        is_bullet=True,
        style_name="List Bullet",
        in_table=False,
        manual_prefix="",
        role_title="Engineer",
        role_dates="2021–Present",
        start_year=2021,
        end_year=2026,
        is_current_role=True,
        char_budget=len(original),
    )
    applied, report, _warnings = validate_updates(
        [row],
        {
            "updates": [
                {
                    "id": 1,
                    "rewritten": original + " " + ("Kubernetes Docker Terraform " * 20),
                    "changed": True,
                    "reason": "too long",
                }
            ]
        },
        strict_timeline=True,
        match_length=True,
    )
    assert applied == {}
    assert report[0]["rewritten"] == original


def test_profile_roundtrip(tmp_path: Path, monkeypatch) -> None:
    import app.profiles as profiles

    monkeypatch.setattr(profiles, "ROOT", tmp_path / "profiles")
    source = tmp_path / "resume.docx"
    _sample_doc(source)
    created = profiles.create_profile("Alex Rivera", str(source), "Alex Rivera.docx")
    assert created["name"] == "Alex Rivera"
    assert created["bullets"] == 4
    listed = profiles.list_profiles()
    assert listed[0]["id"] == created["id"]
    loaded = profiles.get_profile(created["id"])
    assert loaded["filename"] == "Alex Rivera.docx"
    profiles.delete_profile(created["id"])
    assert profiles.list_profiles() == []


def test_comma_dates_and_job_headers_are_not_bullets(tmp_path: Path) -> None:
    from app.dates import parse_role_dates

    dates = parse_role_dates("Lead AI/ML Engineer | AI Architect - IBM  Mar, 2025 – Jul, 2026", 2026)
    assert dates is not None
    assert dates.start_year == 2025
    assert dates.end_year == 2026

    doc = Document()
    doc.add_paragraph("Lead AI/ML Engineer | AI Architect - IBM  Mar, 2025 – Jul, 2026", style="List Bullet")
    doc.add_paragraph(
        "Built Python FastAPI services for model training, validation, and deployment.",
        style="List Bullet",
    )
    path = tmp_path / "headers.docx"
    doc.save(path)
    _doc, rows = parse_document(str(path), present_year=2026)
    bullets = [r for r in rows if r.is_bullet]
    assert len(bullets) == 1
    assert bullets[0].start_year == 2025
    assert bullets[0].end_year == 2026
    assert "IBM" in bullets[0].role_title
