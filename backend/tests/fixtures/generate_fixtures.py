"""Script to generate 3 realistic sample Terms of Service PDF fixtures using ReportLab.

Each PDF features:
- Realistic legal styling (title, section numbering, headings, body text)
- Multiple pages to verify multi-page span extraction
- Exact coordinate rendering so bounding boxes and page numbers can be asserted in tests
"""

from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib import colors

FIXTURES_DIR = Path(__file__).resolve().parent

PDF_SPECS = {
    "cloud_service_tos.pdf": {
        "title": "CloudScale Services Terms of Service",
        "sections_page_1": [
            ("1. Acceptance of Terms", "By accessing or using the CloudScale Services, you agree to be bound by these Terms of Service. If you do not agree to all terms, you must immediately discontinue use of the Services."),
            ("2. User Accounts and Security", "Users are responsible for maintaining the confidentiality of their credentials. You accept full liability for all activities that occur under your account."),
            ("3. Unilateral Modification of Terms", "CloudScale reserves the right to modify, amend, or replace these Terms at any time at its sole discretion without prior notice to you. Your continued use of the platform after any such modifications constitutes full acceptance of the revised Terms."),
        ],
        "sections_page_2": [
            ("4. Limitation of Liability", "To the maximum extent permitted by applicable law, in no event shall CloudScale, its affiliates, or directors be liable for any indirect, incidental, punitive, or consequential damages. In no event shall CloudScale's total aggregate liability exceed fifty US dollars ($50.00)."),
            ("5. Mandatory Binding Arbitration and Class Action Waiver", "Any dispute, controversy, or claim arising out of or relating to this agreement shall be settled exclusively by confidential binding arbitration in Wilmington, Delaware. You agree to waive any right to participate as a member in any class action lawsuit."),
            ("6. Termination", "CloudScale may suspend or terminate your access to the Services immediately, with or without cause, and without prior notice or liability."),
        ],
    },
    "streaming_platform_tos.pdf": {
        "title": "StreamVerse Media Terms of Use",
        "sections_page_1": [
            ("1. Grant of License", "StreamVerse grants you a limited, non-exclusive, non-transferable, revocable license to access digital media solely for your personal, non-commercial entertainment purposes."),
            ("2. Content Removal and Discretionary Termination", "StreamVerse reserves the absolute right to remove, edit, or block any content and terminate any user account at its sole discretion, at any time, for any reason or no reason, without notice or explanation."),
            ("3. Subscription Billing and Automatic Renewal", "Your subscription will automatically renew on a monthly basis unless cancelled. All subscription fees and charges are completely non-refundable under all circumstances, even upon early termination."),
        ],
        "sections_page_2": [
            ("4. Choice of Law and Jurisdiction", "These Terms of Use shall be governed by and construed in accordance with the laws of the State of New York, without giving effect to any principles of conflicts of law. Any legal action shall be instituted exclusively in state or federal courts in New York County."),
            ("5. Contract by Usage", "By browsing, downloading, streaming, or otherwise accessing any portion of the StreamVerse service, you acknowledge and agree that a binding legal contract is formed."),
            ("6. Disclaimer of Warranties", "The StreamVerse platform is provided on an 'as is' and 'as available' basis without warranties of any kind, whether express or implied."),
        ],
    },
    "social_network_tos.pdf": {
        "title": "Nexus Social Platform Terms of Service",
        "sections_page_1": [
            ("1. Eligibility and User Registration", "You must be at least 18 years of age to establish an account on Nexus. By creating an account, you represent and warrant that all registration information is truthful and accurate."),
            ("2. User Content and Intellectual Property License", "You retain ownership of the content you submit. However, by uploading content to Nexus, you grant Nexus a perpetual, irrevocable, worldwide, royalty-free, transferable, and sublicensable license to use, host, store, copy, modify, distribute, publish, and publicly display such content."),
            ("3. Content Moderation and Account Suspension", "Nexus may screen, monitor, or remove any user content without notice. Nexus reserves the right to disable any account immediately if it determines the user violates platform community standards."),
        ],
        "sections_page_2": [
            ("4. Limitation of Liability and Damages Cap", "Under no legal theory shall Nexus be liable for any lost profits, lost revenue, lost data, or incidental damages. Total liability of Nexus for any claim hereunder shall be capped at one hundred US dollars ($100.00)."),
            ("5. Dispute Resolution and Venue Selection", "You agree that any dispute between you and Nexus shall be resolved exclusively through individual binding arbitration in San Francisco, California. You expressly waive the right to trial by jury and class proceedings."),
            ("6. Severability and Complete Agreement", "If any provision of these Terms is found unenforceable, that provision will be severed and the remaining provisions will continue in full force and effect."),
        ],
    },
}


def generate_tos_pdf(filename: str, spec: dict) -> Path:
    out_path = FIXTURES_DIR / filename
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=letter,
        rightMargin=54,
        leftMargin=54,
        topMargin=54,
        bottomMargin=54,
    )
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "ToSTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#1e293b"),
        spaceAfter=14,
    )

    heading_style = ParagraphStyle(
        "ToSHeading",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#0f172a"),
        spaceBefore=10,
        spaceAfter=4,
    )

    body_style = ParagraphStyle(
        "ToSBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#334155"),
        spaceAfter=8,
    )

    story = []
    # Title
    story.append(Paragraph(spec["title"], title_style))
    story.append(Spacer(1, 8))

    # Page 1 Sections
    for heading, body in spec["sections_page_1"]:
        story.append(Paragraph(heading, heading_style))
        story.append(Paragraph(body, body_style))

    # Page Break to ensure multi-page fixture
    story.append(PageBreak())

    # Page 2 Sections
    for heading, body in spec["sections_page_2"]:
        story.append(Paragraph(heading, heading_style))
        story.append(Paragraph(body, body_style))

    doc.build(story)
    return out_path


def generate_all_fixtures() -> list[Path]:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    generated = []
    for filename, spec in PDF_SPECS.items():
        path = generate_tos_pdf(filename, spec)
        generated.append(path)
    return generated


if __name__ == "__main__":
    paths = generate_all_fixtures()
    for p in paths:
        print(f"Generated fixture: {p} ({p.stat().st_size} bytes)")
