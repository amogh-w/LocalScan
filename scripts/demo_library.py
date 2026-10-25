"""Fill a running Local Scan with made-up letters, for README screenshots (never real documents).

    $env:LOCALSCAN_DATA_DIR = "$env:TEMP\\localscan-demo"
    uv run --extra paddle --directory backend uvicorn app.main:app --port 8011
    uv run python scripts/demo_library.py http://localhost:8011

Each letter is drawn as a PDF page, then photographed at an angle on a table, like a phone would.
"""
import sys

import cv2
import httpx
import numpy as np
import pymupdf as fitz

sys.path.insert(0, "tests")
from conftest import project_page  # noqa: E402  (the same pinhole camera the tests use)

LETTERS = [
    ("Stadtwerke Musterstadt GmbH", "Kundenservice, Hauptstraße 1, 12345 Musterstadt",
     "Herrn Max Mustermann", "Beispielweg 12", "12345 Musterstadt",
     "Musterstadt, 3. Oktober 2026", "Ihre Kundennummer 4711-0815",
     "Anpassung Ihres monatlichen Abschlags",
     ["Sehr geehrter Herr Mustermann,", "",
      "aufgrund gestiegener Beschaffungskosten erhöht sich Ihr monatlicher Abschlag",
      "ab dem 1. November 2026 von 72,00 EUR auf 85,00 EUR.", "",
      "Den neuen Betrag buchen wir wie gewohnt von Ihrem Konto ab. Sie müssen nichts tun.",
      "Bei Fragen erreichen Sie uns montags bis freitags von 8 bis 16 Uhr.", "",
      "Mit freundlichen Grüßen", "Ihre Stadtwerke Musterstadt"]),
    ("Beispiel Versicherung AG", "Postfach 100, 54321 Beispielburg",
     "Frau Erika Musterfrau", "Probeallee 7", "54321 Beispielburg",
     "Beispielburg, 18. September 2026", "Versicherungsschein 99-123456",
     "Ihre Hausratversicherung: Beitragsrechnung",
     ["Sehr geehrte Frau Musterfrau,", "",
      "anbei erhalten Sie die Beitragsrechnung für das Jahr 2027.",
      "Der Jahresbeitrag beträgt 96,40 EUR und wird am 1. Januar 2027 eingezogen.", "",
      "Ihr Versicherungsschutz bleibt unverändert bestehen. Eine Übersicht der",
      "Leistungen finden Sie auf der Rückseite dieses Schreibens.", "",
      "Freundliche Grüße", "Ihre Beispiel Versicherung AG"]),
    ("Gemeinde Musterhausen", "Bürgerbüro, Rathausplatz 2, 11111 Musterhausen",
     "Herrn Max Mustermann", "Beispielweg 12", "12345 Musterstadt",
     "Musterhausen, 9. August 2026", "Aktenzeichen 2026/0815",
     "Terminbestätigung Ihres Anliegens",
     ["Sehr geehrter Herr Mustermann,", "",
      "wir bestätigen Ihren Termin im Bürgerbüro am 24. August 2026 um 10:30 Uhr.", "",
      "Bitte bringen Sie Ihren Personalausweis und diese Terminbestätigung mit.",
      "Sollten Sie verhindert sein, sagen Sie den Termin bitte rechtzeitig ab.", "",
      "Mit freundlichen Grüßen", "Ihre Gemeinde Musterhausen"]),
]


def letter_page(sender, sender_line, name, street, city, dateline, ref, subject, body) -> fitz.Document:
    doc = fitz.open()
    p = doc.new_page(width=595.28, height=841.89)
    p.draw_rect(fitz.Rect(60, 40, 82, 62), color=None, fill=(0.1, 0.3, 0.8))  # a made-up logo
    p.insert_text((90, 57), sender, fontsize=15, fontname="hebo")
    p.insert_text((60, 82), sender_line, fontsize=8, fontname="helv")
    for i, line in enumerate((name, street, city)):
        p.insert_text((60, 150 + i * 14), line, fontsize=10.5, fontname="helv")
    p.insert_text((330, 150), dateline, fontsize=10, fontname="helv")
    p.insert_text((330, 165), ref, fontsize=10, fontname="helv")
    p.insert_text((60, 250), subject, fontsize=12, fontname="hebo")
    for i, line in enumerate(body):
        p.insert_text((60, 285 + i * 16), line, fontsize=10.5, fontname="helv")
    return doc


def photograph(doc: fitz.Document, seed: int) -> bytes:
    pix = doc[0].get_pixmap(matrix=fitz.Matrix(2.6, 2.6), alpha=False)
    page = cv2.cvtColor(np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, 3), cv2.COLOR_RGB2BGR)
    h, w = page.shape[:2]
    W, H = 1800, 2300
    rng = np.random.default_rng(seed)
    table = cv2.GaussianBlur(rng.normal(70, 10, (H, W, 3)).clip(0, 255).astype(np.uint8), (9, 9), 0)
    dst = project_page(W, H, 14 + seed * 4, -8 + seed * 5, 2 - seed * 2)
    m = cv2.getPerspectiveTransform(np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], np.float32), dst)
    warped = cv2.warpPerspective(page, m, (W, H))
    mask = cv2.warpPerspective(np.full((h, w), 255, np.uint8), m, (W, H))
    img = np.where(mask[..., None] > 0, warped, table)
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes()


def main(base: str) -> None:
    c = httpx.Client(base_url=base, timeout=120)
    folders = {n: c.post("/api/folders", json={"name": n}).json()["id"] for n in ("Home", "Insurance")}
    tags = {n: c.post("/api/tags", json={"name": n, "color": col}).json()["id"]
            for n, col in (("bills", "peach"), ("to do", "red"))}
    plan = [  # (letter, name, folder, tags)
        (0, "2026-10-03 Stadtwerke Musterstadt - Monthly payment increase", "Home", ["bills", "to do"]),
        (1, "2026-09-18 Beispiel Versicherung - Contents insurance invoice", "Insurance", ["bills"]),
        (2, "2026-08-09 Gemeinde Musterhausen - Appointment confirmation", None, []),
    ]
    for n, (i, name, folder, tag_names) in enumerate(plan):
        doc = c.post("/api/docs", json={"name": name}).json()
        files = [("files", (f"p{p}.jpg", photograph(letter_page(*LETTERS[i]), n * 3 + p), "image/jpeg")) for p in (0,)]
        c.post(f"/api/docs/{doc['id']}/pages", files=files).raise_for_status()
        c.patch(f"/api/docs/{doc['id']}", json={"folder_id": folders[folder] if folder else None,
                                                "tags": [tags[t] for t in tag_names]}).raise_for_status()
        print(doc["id"], name)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8011")
