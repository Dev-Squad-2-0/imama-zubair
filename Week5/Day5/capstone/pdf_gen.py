"""
Turns the proposal crew's text output into a client-ready PDF.
Uses reportlab (per the project's pdf skill guidance) rather than trying
to convert markdown -> PDF with a heavier toolchain.
"""
import os
import re
import uuid

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output_pdfs")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def _clean(text: str) -> str:
    # strip stray markdown bold/asterisks that don't map to reportlab tags cleanly
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    return text.strip()


def generate_proposal_pdf(company_name: str, proposal_text: str) -> str:
    """Writes a PDF to OUTPUT_DIR and returns its filepath."""
    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    heading_style = ParagraphStyle("Heading", parent=styles["Heading2"], spaceBefore=14, spaceAfter=6)
    body_style = ParagraphStyle("Body", parent=styles["Normal"], spaceAfter=8, leading=15)
    bullet_style = ParagraphStyle("Bullet", parent=styles["Normal"], leading=14)

    filename = f"proposal_{company_name.strip().lower().replace(' ', '_')}_{uuid.uuid4().hex[:8]}.pdf"
    filepath = os.path.join(OUTPUT_DIR, filename)

    doc = SimpleDocTemplate(filepath, pagesize=letter, topMargin=54, bottomMargin=54)
    story = [
        Paragraph(f"Proposal for {company_name}", title_style),
        Spacer(1, 16),
    ]

    lines = proposal_text.splitlines()
    bullet_buffer = []

    def flush_bullets():
        nonlocal bullet_buffer
        if bullet_buffer:
            story.append(
                ListFlowable(
                    [ListItem(Paragraph(_clean(b), bullet_style)) for b in bullet_buffer],
                    bulletType="bullet",
                )
            )
            bullet_buffer = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("## "):
            flush_bullets()
            story.append(Paragraph(_clean(stripped[3:]), heading_style))
        elif stripped.startswith(("- ", "* ")):
            bullet_buffer.append(stripped[2:])
        else:
            flush_bullets()
            story.append(Paragraph(_clean(stripped), body_style))

    flush_bullets()
    doc.build(story)
    return filepath
