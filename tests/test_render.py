import pymupdf as fitz

from app.ocr.blocks import group_blocks
from app.ocr.pdf_text import page_lines
from app.render.pdf import RenderPage, build_scan_pdf, build_side_by_side_pdf, build_translated_pdf


def test_builds_all_three_pdfs(tmp_path, letter_pdf, letter_image):
    # Stand-in for OCR: the letter's own text layer, scaled to image pixels.
    lines = page_lines(letter_pdf[0], zoom=2.0)
    blocks = group_blocks(lines)
    translations = [f"EN {b['text'][:20]}" for b in blocks]
    pages = [RenderPage(letter_image, blocks, translations)]

    scan, tr, sbs = tmp_path / "scan.pdf", tmp_path / "tr.pdf", tmp_path / "sbs.pdf"
    build_scan_pdf(pages, scan)
    build_translated_pdf(pages, tr)
    build_side_by_side_pdf(scan, tr, sbs)

    s = fitz.open(scan)
    assert len(s) == 1 and abs(s[0].rect.width - 595.28) < 1
    assert "Kundennummer" in s[0].get_text()  # searchable text layer

    t = fitz.open(tr)
    text = t[0].get_text()
    for tr_text in translations:
        assert tr_text in text.replace("\n", " ")
    # Each translation was placed where its source block was.
    zoom = t[0].rect.width / letter_image.shape[1]
    for block, tr_text in zip(blocks, translations):
        hits = t[0].search_for(tr_text)
        block_h = (block["bbox"][3] - block["bbox"][1]) * zoom
        assert any(abs(h.y0 - block["bbox"][1] * zoom) < block_h for h in hits), tr_text

    b = fitz.open(sbs)
    assert len(b) == 1 and b[0].rect.width > 2 * 595


def test_grow_boxes_respects_neighbours():
    from app.render.pdf import grow_boxes
    boxes = [[50, 100, 200, 112], [300, 100, 450, 112], [50, 115, 400, 127]]
    a, b, c = grow_boxes(boxes, 595, 842)
    assert a[2] < 300 and a[3] <= 115  # stops before the box to its right and the box below
    assert b[2] > 450                   # free to grow to the margin
    assert c[2] > 400 and c[3] > 127
