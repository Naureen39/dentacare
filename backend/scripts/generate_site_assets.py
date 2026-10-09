"""Create the original artwork and printable forms the public website uses.

    uv run python -m scripts.generate_site_assets

The sandbox this project is built in has no licensed photography, so the pictures are original
abstract illustrations drawn here: brand gradients with soft shapes, and a neutral silhouette
for each team member. They are WebP files in several widths for `srcset`, plus a manifest the
frontend reads for sizes. Replace them with real photographs (see CREDITS.md) without changing
any code: keep the file names, or update the manifest.

The forms are styled PDFs made from the same clinic details the site shows.
"""

import json
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.config import get_settings

ROOT = Path(__file__).resolve().parents[2] / "frontend"
IMAGES = ROOT / "src" / "assets" / "images"
FORMS = ROOT / "public" / "forms"

NAVY = (11, 37, 69)
TEAL = (19, 163, 161)
MINT = (232, 246, 245)
WHITE = (250, 251, 252)


def mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


def gradient(
    size: tuple[int, int], start: tuple[int, int, int], end: tuple[int, int, int], angle: float
) -> Image.Image:
    width, height = size
    image = Image.new("RGB", size)
    pixels = image.load()
    assert pixels is not None  # noqa: S101
    dx, dy = math.cos(angle), math.sin(angle)
    span = abs(width * dx) + abs(height * dy)
    for y in range(height):
        for x in range(width):
            t = ((x - width / 2) * dx + (y - height / 2) * dy) / span + 0.5
            pixels[x, y] = mix(start, end, max(0.0, min(1.0, t)))
    return image


def scene(
    seed: int,
    size: tuple[int, int],
    palette: tuple[tuple[int, int, int], tuple[int, int, int]],
    angle: float,
) -> Image.Image:
    """Brand gradient with large translucent circles and rounded rectangles."""
    rng = random.Random(seed)  # noqa: S311
    base = 320  # drawn small, then scaled up: smooth shapes and a small cost
    ratio = size[0] / size[1]
    small = (int(base * ratio), base)
    image = gradient(small, palette[0], palette[1], angle).convert("RGBA")
    layer = Image.new("RGBA", small, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for _ in range(7):
        radius = rng.randint(base // 8, base // 2)
        cx, cy = rng.randint(0, small[0]), rng.randint(0, small[1])
        tint = rng.choice([MINT, TEAL, WHITE])
        draw.ellipse(
            (cx - radius, cy - radius, cx + radius, cy + radius), fill=(*tint, rng.randint(18, 48))
        )
    for _ in range(3):
        w, h = rng.randint(base // 4, base // 2), rng.randint(base // 6, base // 3)
        x, y = rng.randint(0, small[0] - w), rng.randint(0, small[1] - h)
        draw.rounded_rectangle(
            (x, y, x + w, y + h), radius=h // 3, fill=(*WHITE, rng.randint(14, 30))
        )
    layer = layer.filter(ImageFilter.GaussianBlur(1.2))
    return Image.alpha_composite(image, layer).convert("RGB").resize(size, Image.Resampling.LANCZOS)


def portrait(seed: int, size: tuple[int, int]) -> Image.Image:
    """A neutral head and shoulders silhouette on a soft brand background."""
    rng = random.Random(seed)  # noqa: S311
    palettes = [
        (MINT, TEAL),
        (MINT, (120, 190, 200)),
        ((214, 232, 240), NAVY),
        (MINT, (80, 150, 170)),
    ]
    start, end = palettes[seed % len(palettes)]
    image = gradient(size, start, mix(start, end, 0.55), 1.0 + rng.random())
    draw = ImageDraw.Draw(image)
    w, h = size
    body = mix(NAVY, TEAL, 0.25)
    draw.ellipse((w * 0.14, h * 0.66, w * 0.86, h * 1.5), fill=body)
    draw.rectangle((w * 0.43, h * 0.5, w * 0.57, h * 0.72), fill=mix(MINT, TEAL, 0.35))
    draw.ellipse((w * 0.32, h * 0.17, w * 0.68, h * 0.58), fill=mix(MINT, TEAL, 0.35))
    return image


# name -> (kind, aspect width, aspect height, widths, seed, palette, angle)
SPECS: dict[
    str,
    tuple[
        str,
        int,
        int,
        tuple[int, ...],
        int,
        tuple[tuple[int, int, int], tuple[int, int, int]],
        float,
    ],
] = {
    "hero": ("scene", 16, 9, (640, 1024, 1600), 1, (NAVY, mix(NAVY, TEAL, 0.75)), 0.4),
    "interior": ("scene", 4, 3, (480, 800, 1200), 2, (mix(NAVY, TEAL, 0.3), TEAL), 0.9),
    "technology": ("scene", 4, 3, (480, 800, 1200), 3, (mix(TEAL, NAVY, 0.4), NAVY), 2.2),
    "about": ("scene", 4, 3, (480, 800, 1200), 4, (TEAL, mix(NAVY, TEAL, 0.5)), 0.2),
    "gallery-1": ("scene", 3, 2, (400, 800), 5, (mix(NAVY, TEAL, 0.5), MINT), 0.5),
    "gallery-2": ("scene", 3, 2, (400, 800), 6, (MINT, TEAL), 1.4),
    "gallery-3": ("scene", 3, 2, (400, 800), 7, (NAVY, TEAL), 2.6),
    "gallery-4": ("scene", 3, 2, (400, 800), 8, (mix(MINT, TEAL, 0.4), NAVY), 0.1),
    "service-preventive": ("scene", 3, 2, (400, 800), 11, (MINT, TEAL), 0.6),
    "service-restorative": ("scene", 3, 2, (400, 800), 12, (mix(NAVY, TEAL, 0.4), TEAL), 1.1),
    "service-cosmetic": (
        "scene",
        3,
        2,
        (400, 800),
        13,
        ((214, 240, 238), mix(TEAL, NAVY, 0.3)),
        2.0,
    ),
    "service-surgical": ("scene", 3, 2, (400, 800), 14, (NAVY, mix(NAVY, TEAL, 0.6)), 0.8),
    "service-orthodontic": ("scene", 3, 2, (400, 800), 15, (TEAL, MINT), 2.4),
    "article-1": ("scene", 16, 9, (480, 960), 21, (MINT, TEAL), 0.3),
    "article-2": ("scene", 16, 9, (480, 960), 22, (mix(NAVY, TEAL, 0.5), MINT), 1.2),
    "article-3": ("scene", 16, 9, (480, 960), 23, (TEAL, NAVY), 2.0),
    "article-4": ("scene", 16, 9, (480, 960), 24, (NAVY, MINT), 0.7),
}
for index in range(1, 8):
    SPECS[f"dentist-{index}"] = ("portrait", 1, 1, (160, 320), index, (NAVY, TEAL), 0.0)


def make_images() -> None:
    IMAGES.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict[str, object]] = {}
    for name, (kind, aw, ah, widths, seed, palette, angle) in SPECS.items():
        for width in widths:
            height = round(width * ah / aw)
            image = (
                portrait(seed, (width, height))
                if kind == "portrait"
                else scene(seed, (width, height), palette, angle)
            )
            image.save(IMAGES / f"{name}-{width}.webp", "WEBP", quality=72, method=6)
        manifest[name] = {"aspect": [aw, ah], "widths": list(widths)}
    (IMAGES / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


# --- forms -------------------------------------------------------------------------------------------


def make_forms() -> None:
    settings = get_settings()
    FORMS.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "t", parent=styles["Title"], textColor=colors.HexColor("#0B2545"), fontSize=20, spaceAfter=4
    )
    note = ParagraphStyle(
        "n", parent=styles["BodyText"], textColor=colors.HexColor("#475569"), fontSize=9
    )
    body = ParagraphStyle("b", parent=styles["BodyText"], fontSize=10, leading=14)
    head = ParagraphStyle(
        "h",
        parent=styles["Heading3"],
        textColor=colors.HexColor("#0B7371"),
        fontSize=11,
        spaceBefore=10,
    )

    def field_table(labels: list[str], columns: int = 2) -> Table:
        rows = []
        for i in range(0, len(labels), columns):
            chunk = labels[i : i + columns]
            rows.append(
                [Paragraph(f"<b>{label}</b><br/><br/>", body) for label in chunk]
                + [""] * (columns - len(chunk))
            )
        table = Table(rows, colWidths=[3.4 * inch] * columns)
        table.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#94A3B8")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        return table

    def build(
        filename: str,
        heading: str,
        intro: str,
        sections: list[tuple[str, list[str]]],
        closing: str | None = None,
    ) -> None:
        story = [
            Paragraph(settings.clinic_name, note),
            Paragraph(heading, title),
            Paragraph(intro, body),
            Paragraph(f"{settings.clinic_address} | {settings.clinic_phone}", note),
            Spacer(1, 6),
        ]
        for name, labels in sections:
            story += [Paragraph(name, head), field_table(labels)]
        if closing:
            story += [Spacer(1, 10), Paragraph(closing, body)]
        story += [
            Spacer(1, 14),
            Paragraph("Signature ______________________________ Date ________________", body),
        ]
        story += [
            Spacer(1, 10),
            Paragraph(
                "Sample form for a demonstration clinic. Not for real patient information.", note
            ),
        ]
        SimpleDocTemplate(
            str(FORMS / filename),
            pagesize=letter,
            title=heading,
            author=settings.clinic_name,
            leftMargin=0.7 * inch,
            rightMargin=0.7 * inch,
            topMargin=0.7 * inch,
            bottomMargin=0.7 * inch,
        ).build(story)

    build(
        "new-patient-registration.pdf",
        "New patient registration",
        "Please complete this form before your first visit, or arrive 15 minutes early to complete it at the front desk.",
        [
            (
                "About you",
                [
                    "Full legal name",
                    "Preferred name",
                    "Date of birth",
                    "Phone",
                    "Email address",
                    "Home address",
                ],
            ),
            ("Emergency contact", ["Name", "Relationship", "Phone"]),
            (
                "Insurance",
                [
                    "Insurance company",
                    "Member ID",
                    "Group number",
                    "Policy holder and date of birth",
                ],
            ),
        ],
    )
    build(
        "medical-history.pdf",
        "Medical and dental history",
        "Your answers help us keep you safe. Please list anything that applies and tell us about any change at every visit.",
        [
            (
                "Health",
                [
                    "Current medicines (name and dose)",
                    "Allergies (medicines, latex, other)",
                    "Conditions (heart, diabetes, blood pressure, other)",
                    "Pregnant or breastfeeding?",
                ],
            ),
            (
                "Dental",
                [
                    "Reason for your visit",
                    "Date of last dental visit",
                    "Any pain, bleeding or swelling now?",
                    "Anxiety or past difficult experiences",
                ],
            ),
        ],
    )
    build(
        "consent-to-treatment.pdf",
        "Consent to examination and treatment",
        "I agree to an examination and the x-rays my dentist advises. I understand that I will be told about any treatment, its cost and its alternatives before it begins, and that I may ask questions or decline at any time.",
        [("Patient or guardian", ["Full name", "Relationship to patient (if a guardian)"])],
    )
    build(
        "insurance-information.pdf",
        "Insurance and payment information",
        "Tell us how you plan to pay so we can explain costs before treatment. Bring your insurance card to each visit.",
        [
            (
                "Coverage",
                [
                    "Insurance company",
                    "Plan type (PPO, HMO, other)",
                    "Member ID",
                    "Group number",
                    "Policy holder name",
                    "Policy holder date of birth",
                ],
            ),
            ("Payment", ["Preferred payment method", "Interested in a payment plan? (yes or no)"]),
        ],
    )


if __name__ == "__main__":
    make_images()
    make_forms()
    print(f"Wrote images to {IMAGES} and forms to {FORMS}")
