import cv2
import pymupdf as fitz
import numpy as np
import pytest

LETTER = [
    ("Stadtwerke Musterstadt GmbH", 14, 60),
    ("Herrn Max Mustermann, Beispielweg 12, 12345 Musterstadt", 10, 140),
    ("Musterstadt, 3. Oktober 2026", 10, 200),
    ("Kundennummer: 4711-0815", 10, 230),
    ("Sehr geehrter Herr Mustermann,", 10, 290),
    ("hiermit teilen wir Ihnen mit, dass sich Ihr monatlicher Abschlag", 10, 320),
    ("ab dem 1. November 2026 auf 85,00 EUR erhöht.", 10, 334),
    ("Mit freundlichen Grüßen", 10, 400),
]


def project_page(W: int, H: int, tilt_x: float = 22, tilt_y: float = -12, roll: float = 4) -> np.ndarray:
    """Image corners (TL, TR, BR, BL) of an A4 sheet seen by a pinhole camera tilted in 3D."""
    a, b, c = np.radians([tilt_x, tilt_y, roll])
    rx = np.array([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]])
    ry = np.array([[np.cos(b), 0, np.sin(b)], [0, 1, 0], [-np.sin(b), 0, np.cos(b)]])
    rz = np.array([[np.cos(c), -np.sin(c), 0], [np.sin(c), np.cos(c), 0], [0, 0, 1]])
    pw, ph = 0.210, 0.297
    pts = np.array([[-pw / 2, -ph / 2, 0], [pw / 2, -ph / 2, 0], [pw / 2, ph / 2, 0], [-pw / 2, ph / 2, 0]])
    cam = pts @ (rz @ ry @ rx).T + np.array([0, 0, 0.42])
    f = 1.2 * max(W, H)
    return np.array([[f * x / z + W / 2, f * y / z + H / 2] for x, y, z in cam], dtype=np.float32)


@pytest.fixture
def letter_pdf() -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=595.28, height=841.89)
    for text, size, y in LETTER:
        page.insert_text((60, y), text, fontsize=size, fontname="helv")
    page.draw_rect(fitz.Rect(450, 30, 540, 80), color=(0.1, 0.3, 0.8), fill=(0.1, 0.3, 0.8))  # "logo"
    return doc


@pytest.fixture
def letter_image(letter_pdf) -> np.ndarray:
    zoom = 2.0
    pix = letter_pdf[0].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    return cv2.cvtColor(np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, 3), cv2.COLOR_RGB2BGR)


@pytest.fixture
def photo(letter_image):
    """The letter photographed at an angle on a dark wooden-ish table. Returns (img, true corners)."""
    h, w = letter_image.shape[:2]
    W, H = 1600, 2000
    rng = np.random.default_rng(0)
    bg = (rng.normal(60, 12, (H, W, 3))).clip(0, 255).astype(np.uint8)
    bg = cv2.GaussianBlur(bg, (7, 7), 0)
    dst = project_page(W, H)
    src = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32)
    m = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(letter_image, m, (W, H))
    mask = cv2.warpPerspective(np.full((h, w), 255, np.uint8), m, (W, H))
    img = np.where(mask[..., None] > 0, warped, bg)
    return img, dst / np.array([W, H], dtype=np.float32)
