"""Tailored CV and cover letter (DOCX + PDF) built only from verified CV facts."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer
from xml.sax.saxutils import escape

from jobbot import ai
from jobbot.ai import fact_guard
from jobbot.config import paths
from jobbot.db import DUBAI

# Which CV skill lines support each extractor skill name.
SKILL_TO_CV = {
    "ICD-10-CM": "ICD-10-CM diagnosis coding, conventions and guidelines",
    "CPT": "CPT procedure coding and modifiers",
    "Modifiers": "CPT procedure coding and modifiers",
    "HCPCS": "HCPCS Level II coding",
    "E/M coding": "Evaluation and Management (E/M) coding",
    "Record abstraction": "Medical record abstraction",
    "Clinical documentation review": "Clinical documentation review",
    "Medical terminology": "Medical terminology, human anatomy & physiology",
    "Anatomy & physiology": "Medical terminology, human anatomy & physiology",
    "Pre-authorization": "Insurance pre-authorization (approvals)",
    "Claims submission": "Claims preparation and submission",
    "Payer follow-up": "Insurance approval follow-up",
    "eClaimLink": "eClaimLink (Dubai e-claims platform)",
    "Mediware": "Mediware hospital software",
    "MS Office / Excel": "MS Office (Word, Excel, PowerPoint)",
    "HIS / EMR software": "Mediware hospital software",
    "RCM": "Claims preparation and submission",
    "Insurance / TPA": "Insurance pre-authorization (approvals)",
}

ROLE_WORDS = {
    "medical_coding": "Medical Coder",
    "medical_insurance": "Medical Insurance / Pre-Authorization",
    "billing_rcm": "Medical Billing and RCM",
}


PHOTO_NAMES = ("photo.jpg", "photo.jpeg", "photo.png")


def find_photo() -> Path | None:
    """Her photo, if one was added with `python -m jobbot init --photo <file>` (kept in data/cv, gitignored)."""
    for n in PHOTO_NAMES:
        f = paths().cv_dir / n
        if f.exists():
            return f
    return None


def _slug(s: str, n: int = 40) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", s or "").strip("-")[:n] or "job"


def template_summary(profile: dict, category: str) -> str:
    if category == "medical_insurance":
        return ("Insurance Coordinator Trainee in the Revenue Cycle Management team at International Modern Hospital, "
                "Dubai, handling insurance pre-authorizations, payer follow-ups and claim preparation and submission "
                "through eClaimLink, using Mediware hospital software daily. AAPC Certified Professional Coder (CPC) "
                "with a 90% examination score, bringing ICD-10-CM and CPT coding knowledge to clinical documentation "
                "review for approvals. Completed a 270-hour medical coding internship (A+ grade). MSc Zoology.")
    if category == "billing_rcm":
        return ("AAPC Certified Professional Coder (CPC), 90% examination score, with hands-on UAE hospital revenue "
                "cycle management experience at International Modern Hospital, Dubai: insurance pre-authorizations, "
                "claim preparation and submission through eClaimLink, and payer follow-ups using Mediware. Trained in "
                "ICD-10-CM, CPT and HCPCS Level II coding through a 270-hour internship (A+ grade), with strong "
                "clinical documentation review and an MSc in Zoology.")
    return profile.get("summary", "").strip() + (
        " Seeking an entry-level Medical Coder position in the UAE healthcare sector.")


def template_cover_letter(profile: dict, job: dict, matched: list[str], category: str) -> list[str]:
    title = job.get("title") or "the advertised role"
    company = job.get("company") or "your organisation"
    skills_txt = ", ".join(matched[:5]) if matched else "ICD-10-CM, CPT and HCPCS Level II coding"
    p1 = (f"I am writing to apply for the {title} position at {company}. I am an AAPC Certified Professional "
          f"Coder (CPC), certified in August 2026 with a 90% examination score, and I currently work in the "
          f"Revenue Cycle Management team at International Modern Hospital, Dubai.")
    if category == "medical_insurance":
        p2 = ("As an Insurance Coordinator Trainee since October 2026, I review clinical documentation to support "
              "pre-authorization requests, follow up with payers until approval, and prepare and submit claims "
              "through eClaimLink, checking patient, policy and service details for accuracy. I use Mediware "
              "hospital software every day for patient, insurance and billing records.")
    else:
        p2 = ("My 270-hour medical coding internship at Cigma Medical Coding Academy (A+ grade) gave me practice "
              "assigning ICD-10-CM, CPT and HCPCS Level II codes on real and simulated charts, abstracting medical "
              "records and validating code selection against the official manuals. Since October 2026 I have applied "
              "this at International Modern Hospital, where documentation and coding support pre-authorizations "
              "and claims submitted through eClaimLink, using Mediware daily.")
    p3 = (f"Your requirements around {skills_txt} match the work I do and trained for. My MSc in Zoology gives me "
          "a solid grounding in anatomy, physiology and medical terminology, and I bring accuracy and attention to "
          "detail to every record.")
    p4 = (f"I would welcome the opportunity to contribute to {company} and to discuss how I can support your team. "
          "Thank you for considering my application.")
    return [p1, p2, p3, p4]


def _ordered_skills(profile: dict, matched: list[str]) -> list[str]:
    all_lines = profile["skills"]["coding"] + profile["skills"]["rcm_insurance"]
    first = []
    for m in matched:
        line = SKILL_TO_CV.get(m)
        if line and line not in first:
            first.append(line)
    return first + [s for s in all_lines if s not in first]


def build_content(profile: dict, job: dict, matched: list[str], category: str, use_ai: bool = True) -> dict:
    ai_text = ai.write_with_ai(profile, job, matched) if use_ai else None
    if ai_text:
        summary, letter, source = ai_text["summary"], ai_text["cover_letter_paragraphs"], "ai"
    else:
        summary = template_summary(profile, category)
        letter = template_cover_letter(profile, job, matched, category)
        source = "template"
    problems = fact_guard(summary + "\n" + "\n".join(letter), profile, (job.get("company") or "",))
    if problems:  # templates must also pass; this catches template edits that break the rules
        raise ValueError("Generated text failed the fact check: " + "; ".join(problems))
    return {
        "summary": summary,
        "cover_letter": letter,
        "skills": _ordered_skills(profile, matched),
        "matched": matched,
        "source": source,
        "headline": profile.get("headline", ""),
    }


# ---------------- DOCX ----------------
def _docx_heading(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    r = p.add_run(text.upper())
    r.bold = True
    r.font.size = Pt(10.5)
    r.font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(2)


def _contact_line(profile: dict) -> str:
    c = profile.get("contact", {})
    parts = [c.get("email"), c.get("phone"), profile.get("location"), c.get("linkedin")]
    return " | ".join(p for p in parts if p)


def write_cv_docx(profile: dict, content: dict, out: Path) -> None:
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = "Calibri"
    st.font.size = Pt(10)
    for s in doc.sections:
        s.left_margin = s.right_margin = s.top_margin = s.bottom_margin = Pt(42)
    photo = find_photo()
    if photo:
        from docx.shared import Mm
        t = doc.add_table(rows=1, cols=2)
        left, right = t.rows[0].cells
        left.width, right.width = Mm(140), Mm(32)
        hp = left.paragraphs[0]
        r = hp.add_run(profile["name"].upper())
        r.bold = True
        r.font.size = Pt(18)
        left.add_paragraph(content["headline"])
        left.add_paragraph(_contact_line(profile))
        rp = right.paragraphs[0]
        rp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        rp.add_run().add_picture(str(photo), width=Mm(28))
    else:
        h = doc.add_paragraph()
        h.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = h.add_run(profile["name"].upper())
        r.bold = True
        r.font.size = Pt(18)
        sub = doc.add_paragraph(content["headline"])
        sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cl = doc.add_paragraph(_contact_line(profile))
        cl.alignment = WD_ALIGN_PARAGRAPH.CENTER

    _docx_heading(doc, "Professional Summary")
    doc.add_paragraph(content["summary"])

    _docx_heading(doc, "Certification")
    for c in profile["certifications"]:
        aapc = profile.get("contact", {}).get("aapc_id")
        doc.add_paragraph(f"{c['name']} | {c['date']} | {c['detail']}" + (f" | AAPC ID: {aapc}" if aapc else ""),
                          style="List Bullet")

    _docx_heading(doc, "Professional Experience")
    for e in profile["experience"]:
        p = doc.add_paragraph()
        p.add_run(e["title"]).bold = True
        p.add_run(f"    {e['start']} – {e['end']}")
        doc.add_paragraph(f"{e['employer']}, {e['location']}")
        for b in e["bullets"]:
            doc.add_paragraph(b, style="List Bullet")

    _docx_heading(doc, "Core Skills")
    for s in content["skills"]:
        doc.add_paragraph(s, style="List Bullet")

    _docx_heading(doc, "Training & Internships")
    for t in profile["training"]:
        p = doc.add_paragraph()
        p.add_run(t["title"]).bold = True
        p.add_run(f"    {t['duration']}")
        doc.add_paragraph(t["organisation"])
        for b in t["bullets"]:
            doc.add_paragraph(b, style="List Bullet")

    _docx_heading(doc, "Education")
    for ed in profile["education"]:
        p = doc.add_paragraph()
        p.add_run(f"{ed['degree']} — {ed['detail']}").bold = True
        p.add_run(f"    {ed['years']}")
        doc.add_paragraph(ed["institution"])

    _docx_heading(doc, "Personal Details")
    doc.add_paragraph(f"Nationality: {profile['nationality']} | Languages: {', '.join(profile['languages'])}"
                      f" | Visa Status: {profile['visa_status_on_cv']}")
    doc.save(out)


def write_letter_docx(profile: dict, job: dict, content: dict, out: Path) -> None:
    doc = Document()
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(11)
    doc.add_paragraph(profile["name"]).runs[0].bold = True
    doc.add_paragraph(_contact_line(profile))
    doc.add_paragraph(datetime.now(DUBAI).strftime("%d %B %Y"))
    doc.add_paragraph(f"Hiring Team\n{job.get('company') or ''}\n{job.get('location') or ''}".strip())
    doc.add_paragraph(f"Re: {job.get('title') or 'Application'}").runs[0].bold = True
    doc.add_paragraph("Dear Hiring Manager,")
    for para in content["cover_letter"]:
        doc.add_paragraph(para)
    doc.add_paragraph("Yours sincerely,")
    doc.add_paragraph(profile["name"])
    doc.save(out)


# ---------------- PDF ----------------
def _styles():
    ss = getSampleStyleSheet()
    return {
        "name": ParagraphStyle("name", parent=ss["Title"], fontSize=18, leading=22, spaceAfter=2),
        "sub": ParagraphStyle("sub", parent=ss["Normal"], fontSize=9.5, alignment=TA_CENTER, leading=12),
        "h": ParagraphStyle("h", parent=ss["Heading4"], fontSize=10.5, textColor=colors.HexColor("#1F3A5F"),
                            spaceBefore=5, spaceAfter=1.5),
        "body": ParagraphStyle("body", parent=ss["Normal"], fontSize=9.4, leading=12.2),
        "bold": ParagraphStyle("bold", parent=ss["Normal"], fontSize=9.4, leading=12.2, fontName="Helvetica-Bold"),
        "letter": ParagraphStyle("letter", parent=ss["Normal"], fontSize=10.5, leading=14.5, spaceAfter=8),
    }


def _bullets(items: list[str], st) -> ListFlowable:
    return ListFlowable([ListItem(Paragraph(escape(i), st), leftIndent=10) for i in items],
                        bulletType="bullet", start="•", leftIndent=10, bulletFontSize=7)


def write_cv_pdf(profile: dict, content: dict, out: Path) -> None:
    S = _styles()
    doc = SimpleDocTemplate(str(out), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=10 * mm, bottomMargin=9 * mm, title=f"{profile['name']} CV",
                            author=profile["name"])
    photo = find_photo()
    if photo:
        from reportlab.lib.styles import ParagraphStyle as PS
        from reportlab.platypus import Image, Table, TableStyle
        img = Image(str(photo))
        ratio = img.imageHeight / float(img.imageWidth or 1)
        img.drawWidth, img.drawHeight = 22 * mm, min(28 * mm, 22 * mm * ratio)
        left = [Paragraph(escape(profile["name"].upper()), PS("nl", parent=S["name"], alignment=0, spaceBefore=0)),
                Paragraph(escape(content["headline"]), PS("sl", parent=S["sub"], alignment=0, fontSize=9)),
                Paragraph(escape(_contact_line(profile)), PS("cl", parent=S["sub"], alignment=0, fontSize=9))]
        head = Table([[left, img]], colWidths=[156 * mm, 24 * mm])
        head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                                  ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
        f = [head]
    else:
        f = [Paragraph(escape(profile["name"].upper()), S["name"]),
             Paragraph(escape(content["headline"]), S["sub"]),
             Paragraph(escape(_contact_line(profile)), S["sub"])]
    f += [Paragraph("Professional Summary", S["h"]), Paragraph(escape(content["summary"]), S["body"]),
         Paragraph("Certification", S["h"])]
    aapc = profile.get("contact", {}).get("aapc_id")
    f.append(_bullets([f"{c['name']} | {c['date']} | {c['detail']}" + (f" | AAPC ID: {aapc}" if aapc else "")
                       for c in profile["certifications"]], S["body"]))
    f.append(Paragraph("Professional Experience", S["h"]))
    for e in profile["experience"]:
        f.append(Paragraph(f"{escape(e['title'])} &nbsp;&nbsp; <font name='Helvetica'>{e['start']} – {e['end']}</font>", S["bold"]))
        f.append(Paragraph(escape(f"{e['employer']}, {e['location']}"), S["body"]))
        f.append(_bullets(e["bullets"], S["body"]))
    f.append(Paragraph("Core Skills", S["h"]))
    f.append(_bullets(content["skills"], S["body"]))
    f.append(Paragraph("Training &amp; Internships", S["h"]))
    for t in profile["training"]:
        f.append(Paragraph(f"{escape(t['title'])} &nbsp;&nbsp; <font name='Helvetica'>{escape(t['duration'])}</font>", S["bold"]))
        f.append(Paragraph(escape(t["organisation"]), S["body"]))
        f.append(_bullets(t["bullets"], S["body"]))
    f.append(Paragraph("Education", S["h"]))
    for ed in profile["education"]:
        f.append(Paragraph(f"{escape(ed['degree'])} — {escape(ed['detail'])} &nbsp;&nbsp; <font name='Helvetica'>{ed['years']}</font>", S["bold"]))
        f.append(Paragraph(escape(ed["institution"]), S["body"]))
    f.append(Paragraph("Personal Details", S["h"]))
    f.append(Paragraph(escape(f"Nationality: {profile['nationality']} | Languages: {', '.join(profile['languages'])}"
                              f" | Visa Status: {profile['visa_status_on_cv']}"), S["body"]))
    doc.build(f)


def write_letter_pdf(profile: dict, job: dict, content: dict, out: Path) -> None:
    S = _styles()
    doc = SimpleDocTemplate(str(out), pagesize=A4, leftMargin=22 * mm, rightMargin=22 * mm,
                            topMargin=20 * mm, bottomMargin=20 * mm, title="Cover letter", author=profile["name"])
    f = [Paragraph(f"<b>{escape(profile['name'])}</b>", S["letter"]),
         Paragraph(escape(_contact_line(profile)), S["body"]), Spacer(1, 10),
         Paragraph(datetime.now(DUBAI).strftime("%d %B %Y"), S["letter"]),
         Paragraph(escape(f"Hiring Team, {job.get('company') or ''}"), S["letter"]),
         Paragraph(f"<b>Re: {escape(job.get('title') or 'Application')}</b>", S["letter"]),
         Paragraph("Dear Hiring Manager,", S["letter"])]
    f += [Paragraph(escape(p), S["letter"]) for p in content["cover_letter"]]
    f += [Paragraph("Yours sincerely,", S["letter"]), Paragraph(escape(profile["name"]), S["letter"])]
    doc.build(f)


def generate_application_documents(profile: dict, job: dict, matched: list[str], category: str,
                                   use_ai: bool = True) -> dict:
    """Write CV + cover letter for one job into its own folder. Returns paths and the CV version."""
    content = build_content(profile, job, matched, category, use_ai=use_ai)
    folder = paths().documents / (f"{datetime.now(DUBAI):%Y-%m-%d}_{job.get('id', 0)}_"
                                  f"{_slug(job.get('company'), 30)}_{_slug(job.get('title'), 40)}")
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(json.dumps([content["summary"], content["skills"]]).encode()).hexdigest()[:6]
    version = f"{datetime.now(DUBAI):%Y%m%d}-{category}-{content['source']}-{digest}"
    base = _slug(profile["name"], 20) + "_CV"
    out = {
        "cv_docx": folder / f"{base}.docx",
        "cv_pdf": folder / f"{base}.pdf",
        "cover_letter_docx": folder / "Cover_Letter.docx",
        "cover_letter_pdf": folder / "Cover_Letter.pdf",
    }
    write_cv_docx(profile, content, out["cv_docx"])
    write_cv_pdf(profile, content, out["cv_pdf"])
    write_letter_docx(profile, job, content, out["cover_letter_docx"])
    write_letter_pdf(profile, job, content, out["cover_letter_pdf"])
    (folder / "application.json").write_text(json.dumps({
        "job_id": job.get("id"), "company": job.get("company"), "title": job.get("title"), "url": job.get("url"),
        "cv_version": version, "text_source": content["source"], "matched_skills": matched,
        "summary": content["summary"], "cover_letter": content["cover_letter"],
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"folder": str(folder), "cv_version": version, "source": content["source"],
            **{k: str(v) for k, v in out.items()}}
