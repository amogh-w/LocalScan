"""Numbers, codes, rules and vertical margin text stay as photographed instead of being retyped."""
import numpy as np
import pymupdf as fitz

from app.ocr.blocks import group_blocks, is_kept, is_vertical
from app.render.pdf import RenderPage, build_scan_pdf, build_translated_pdf


def line(text, bbox):
    return {"text": text, "conf": 1.0, "bbox": bbox}


VERTICAL_CODE = line("0312169670", [20, 90, 35, 170])           # reads bottom to top in the left margin
RULE = line("________________________________", [80, 230, 680, 240])
VERTICAL_NOTE = line("Dokument zur Vorlage beim Finanzamt", [1170, 400, 1190, 900])
PROSE = line("Nachfolgend teile ich mit Ihnen die fehlenden Angaben mit", [80, 40, 640, 56])


def test_what_is_kept():
    assert is_vertical(VERTICAL_CODE) and is_kept(VERTICAL_CODE)
    assert is_vertical(VERTICAL_NOTE) and not is_kept(VERTICAL_NOTE)  # a vertical sentence is translated, not kept
    assert is_kept(line("04GKRU1970482843_P", [20, 450, 35, 590]))          # a vertical code
    assert is_kept(line("0312169670", [80, 100, 300, 120]))                  # a horizontal number: nothing to translate
    assert is_kept(RULE)                                                      # a form line read as underscores
    assert is_kept(line("04GKRU1970482843_P", [80, 100, 400, 120]))          # one code, no word in it
    assert not is_kept(PROSE)
    assert not is_kept(line("85,00 EUR", [80, 100, 200, 120]))               # EUR is a word
    assert not is_kept(line("Kundennummer: 4711", [80, 100, 300, 120]))
    assert not is_vertical(line("Nr.", [10, 10, 30, 22]))                     # short and wide: ordinary text


def test_kept_lines_are_their_own_blocks_in_reading_order():
    blocks = group_blocks([PROSE, VERTICAL_CODE, RULE])
    assert [b["text"].split()[0] for b in blocks] == ["Nachfolgend", "0312169670", "________________________________"] or \
        [b.get("keep", False) for b in blocks] == [False, True, True]
    assert [b["id"] for b in blocks] == ["p0b0", "p0b1", "p0b2"]
    prose = next(b for b in blocks if not b.get("keep"))
    assert prose["text"] == PROSE["text"]  # the margin code did not leak into the paragraph


def test_the_scan_pdf_places_vertical_text_inside_its_box(tmp_path):
    image = np.full((1754, 1240, 3), 255, np.uint8)
    block = group_blocks([VERTICAL_CODE])[0]
    out = tmp_path / "scan.pdf"
    build_scan_pdf([RenderPage(image, [block], [block["text"]])], out)
    page = fitz.open(out)[0]
    zoom = page.rect.width / 1240
    words = page.get_text("words")
    assert [w[4] for w in words] == ["0312169670"]
    x0, y0, x1, y1, *_ = words[0]
    bx0, by0, bx1, by1 = (v * zoom for v in VERTICAL_CODE["bbox"])
    assert bx0 - 6 <= x0 and x1 <= bx1 + 6 and by0 - 6 <= y0 and y1 <= by1 + 6  # in the margin, not spread across the page
    assert (y1 - y0) > 3 * (x1 - x0)                                              # and standing upright


def test_the_translated_pdf_leaves_kept_lines_alone(tmp_path):
    image = np.full((1754, 1240, 3), 255, np.uint8)
    x0, y0, x1, y1 = VERTICAL_CODE["bbox"]
    image[y0:y1, x0:x1] = 0  # the ink of the margin number
    blocks = group_blocks([PROSE, VERTICAL_CODE])
    translations = [b["text"] if b.get("keep") else "Below we send the missing details" for b in blocks]
    out = tmp_path / "tr.pdf"
    build_translated_pdf([RenderPage(image, blocks, translations)], out)
    doc = fitz.open(out)
    text = doc[0].get_text()
    assert "Below we send the missing details" in text.replace("\n", " ")
    assert "0312169670" not in text and "Nachfolgend" not in text  # nothing retyped, the German erased
    scale = 1240 / doc[0].rect.width
    pix = doc[0].get_pixmap(matrix=fitz.Matrix(scale, scale))
    region = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[y0 + 3:y1 - 3, x0 + 3:x1 - 3]
    assert region.mean() < 60  # the original ink is still there


def test_a_vertical_sentence_is_its_own_translatable_block():
    blocks = group_blocks([PROSE, VERTICAL_NOTE, VERTICAL_CODE])
    note = next(b for b in blocks if b.get("vertical"))
    assert note["text"] == VERTICAL_NOTE["text"] and not note.get("keep") and note["lines"] == [VERTICAL_NOTE]
    assert next(b for b in blocks if not b.get("vertical") and not b.get("keep"))["text"] == PROSE["text"]


def test_the_translated_pdf_draws_a_vertical_translation_rotated_in_place(tmp_path):
    image = np.full((1754, 1240, 3), 255, np.uint8)
    x0, y0, x1, y1 = (int(v) for v in VERTICAL_NOTE["bbox"])
    image[y0:y1, x0:x1] = 0  # the German ink
    blocks = group_blocks([VERTICAL_NOTE])
    out = tmp_path / "tr.pdf"
    build_translated_pdf([RenderPage(image, blocks, ["Document for submission to the tax office"])], out)
    page = fitz.open(out)[0]
    zoom = page.rect.width / 1240
    found = [ln for b in page.get_text("dict")["blocks"] for ln in b.get("lines", [])
             if "Document for submission" in "".join(sp["text"] for sp in ln["spans"])]
    assert found, page.get_text()
    line_ = found[0]
    assert tuple(round(v) for v in line_["dir"]) == (0, -1)  # reads from the bottom to the top
    bx0, by0, bx1, by1 = (v * zoom for v in VERTICAL_NOTE["bbox"])
    lx0, ly0, lx1, ly1 = line_["bbox"]
    assert bx0 - 10 <= lx0 and lx1 <= bx1 + 10 and by0 - 40 <= ly0 and ly1 <= by1 + 5  # in the margin, along the note
    scale = 1240 / page.rect.width
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
    rgb = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
    german_gone = rgb[y0 + 5:y1 - 5, x0 + 5:x1 - 5]
    assert (german_gone < 60).mean() < 0.3  # the black block was erased (a thin translation drawn on it is mostly white)
