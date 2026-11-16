import json

import pdfplumber
import pytest

from jobbot.ai import fact_guard
from jobbot.config import load_profile
from jobbot.documents import generate_application_documents


@pytest.mark.parametrize("category", ["medical_coding", "medical_insurance", "billing_rcm"])
def test_documents_are_generated_and_truthful(sample_jobs, category):
    prof = load_profile()
    job = dict(sample_jobs[3], id=7)
    out = generate_application_documents(prof, job, ["ICD-10-CM", "eClaimLink"], category, use_ai=False)
    for k in ("cv_docx", "cv_pdf", "cover_letter_docx", "cover_letter_pdf"):
        assert out[k] and open(out[k], "rb").read(4) in (b"%PDF", b"PK\x03\x04")
    with pdfplumber.open(out["cv_pdf"]) as pdf:
        text = "\n".join(p.extract_text() for p in pdf.pages)
        assert len(pdf.pages) <= 2
    for fact in ("Oct 2026", "International Modern Hospital", "90%", "270", "MSc Zoology", "eClaimLink", "Mediware"):
        assert fact in text
    with pdfplumber.open(out["cover_letter_pdf"]) as pdf:
        letter = "\n".join(p.extract_text() for p in pdf.pages)
    assert job["company"] in letter
    meta = json.loads(open(out["folder"] + "/application.json").read())
    assert meta["text_source"] == "template"


def test_fact_guard_catches_inventions():
    prof = load_profile()
    assert fact_guard("I have 3 years of coding experience", prof)
    assert fact_guard("I hold a CCS certification and DRG expertise", prof)
    assert fact_guard("I scored 95% in the CPC exam", prof)
    assert fact_guard("Worked at Mediclinic Hospital", prof)
    assert not fact_guard("AAPC Certified Professional Coder (CPC) with a 90% score, working at International Modern Hospital.", prof)


def test_ai_text_rejected_falls_back_to_template(monkeypatch, sample_jobs):
    import types
    import anthropic
    from jobbot import ai
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    bad = json.dumps({"summary": "Coder with 4 years of experience and CCS", "cover_letter_paragraphs": ["x"]})

    class Client:
        def __init__(self, *a, **k):
            blk = types.SimpleNamespace(type="text", text=bad)
            resp = types.SimpleNamespace(stop_reason="end_turn", content=[blk])
            self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=lambda **kw: resp))
    monkeypatch.setattr(anthropic, "Anthropic", Client)
    out = generate_application_documents(load_profile(), dict(sample_jobs[3], id=8), [], "medical_coding", use_ai=True)
    assert out["source"] == "template"


def test_photo_from_cv_appears_on_tailored_cv(sample_jobs, tmp_path):
    from pathlib import Path
    from PIL import Image
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from jobbot.cli import extract_photo_from_cv
    src = tmp_path / "face.png"
    Image.new("RGB", (300, 380), (200, 180, 160)).save(src)
    cv = tmp_path / "cv.pdf"
    c = canvas.Canvas(str(cv), pagesize=A4)
    c.drawImage(str(src), 480, 720, 60, 76)
    c.drawString(40, 800, "ANAGHA P")
    c.save()
    photo = extract_photo_from_cv(str(cv))
    assert photo and Path(photo).exists()
    out = generate_application_documents(load_profile(), dict(sample_jobs[3], id=9), [], "medical_coding", use_ai=False)
    with pdfplumber.open(out["cv_pdf"]) as pdf:
        assert pdf.pages[0].images
    from docx import Document
    assert Document(out["cv_docx"]).inline_shapes
