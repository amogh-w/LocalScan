from app.ocr.blocks import group_blocks, join_text
from app.ocr.paddle_http import parse_response

BOX = [[10, 10], [110, 10], [110, 30], [10, 30]]


def test_parse_paddlex_serving():
    payload = {"errorCode": 0, "result": {"ocrResults": [{"prunedResult": {
        "rec_texts": ["Hallo", ""], "rec_scores": [0.9, 0.5], "rec_polys": [BOX, BOX]}}]}}
    lines = parse_response(payload)
    assert lines == [{"text": "Hallo", "conf": 0.9, "bbox": [10.0, 10.0, 110.0, 30.0]}]


def test_parse_paddlex_rec_boxes():
    payload = {"result": {"ocrResults": [{"prunedResult": {
        "rec_texts": ["Hallo"], "rec_scores": [0.9], "rec_boxes": [[10, 10, 110, 30]]}}]}}
    assert parse_response(payload)[0]["bbox"] == [10.0, 10.0, 110.0, 30.0]


def test_parse_paddlehub_serving():
    payload = {"status": "000", "results": [[{"text": "Hallo", "confidence": 0.8, "text_region": BOX}]]}
    assert parse_response(payload)[0]["text"] == "Hallo"


def test_parse_raw_paddleocr_output():
    assert parse_response([[[BOX, ["Hallo", 0.7]]]])[0]["conf"] == 0.7


def _line(text, x0, y0, x1, h=20):
    return {"text": text, "conf": 1.0, "bbox": [x0, y0, x1, y0 + h]}


def test_groups_paragraphs_and_keeps_separate_blocks():
    lines = [
        _line("Sehr geehrter Herr Muster,", 100, 100, 500),
        _line("hiermit teilen wir Ihnen mit, dass die Verein-", 100, 200, 900),
        _line("barung endet.", 100, 225, 400),
        _line("Musterstadt, 3. Oktober", 1200, 100, 1600),
    ]
    blocks = group_blocks(lines)
    texts = [b["text"] for b in blocks]
    assert "hiermit teilen wir Ihnen mit, dass die Vereinbarung endet." in texts
    assert "Sehr geehrter Herr Muster," in texts
    assert "Musterstadt, 3. Oktober" in texts
    assert len(blocks) == 3


def test_merges_word_gap_but_not_column_gap():
    blocks = group_blocks([_line("Kunden-", 100, 100, 240), _line("nummer: 4711", 246, 101, 500)])
    assert len(blocks) == 1 and blocks[0]["text"] == "Kunden- nummer: 4711"
    # Body text ending close to a sidebar: two columns, never one line.
    blocks = group_blocks([_line("eine Nachzah-", 369, 1595, 1516, 52), _line("Telefonische Sprechzeiten", 1554, 1597, 1831, 29)])
    assert len(blocks) == 2


def test_paragraphs_lists_and_addresses():
    lines = [
        _line("Zusammensetzung des Gesamtbetrages", 367, 1732, 1145, 49),
        _line("Von der Bruttozahlung in Höhe von 120,00 EUR wurden folgende Beträge", 369, 1818, 1513, 53),
        _line("abgezogen:", 371, 1874, 554, 40),
        _line("Beiträge zur Krankenversicherung in einer Gesamthöhe von 10,00 EUR", 417, 1951, 1407, 55),
        _line("Einkommensteuer in Höhe von 20,00 EUR", 417, 2002, 1109, 47),
        _line("Verwaltungsgebühr in einer Gesamthöhe von 5,00 EUR", 415, 2046, 1239, 51),
        _line("Bearbeitungsgebühr in Höhe von 2,50 EUR", 415, 2094, 1150, 45),
        _line("Herrn", 391, 2400, 465, 30),
        _line("Max Mustermann", 391, 2434, 648, 30),
        _line("12345 Musterstadt", 387, 2468, 565, 27),
    ]
    blocks = group_blocks(lines)
    assert [b["flow"] for b in blocks] == [True, True, False, False]
    assert blocks[1]["text"] == "Von der Bruttozahlung in Höhe von 120,00 EUR wurden folgende Beträge abgezogen:"
    assert blocks[2]["text"].count("\n") == 3
    assert blocks[3]["text"] == "Herrn\nMax Mustermann\n12345 Musterstadt"


def test_join_text_keeps_hyphen_before_capital():
    assert join_text([_line("Kranken-", 0, 0, 1), _line("und Pflegeversicherung", 0, 25, 1)]) == \
        "Kranken- und Pflegeversicherung"
