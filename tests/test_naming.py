import json

import httpx
import pytest

from app.ai import naming


def test_build_name_format():
    assert naming.build_name({"date": "2026-03-01", "sender": "Stadtwerke Musterstadt",
                              "subject": "Monthly instalment increase"}) == \
        "2026-03-01 Stadtwerke Musterstadt - Monthly instalment increase"


def test_build_name_drops_bad_or_missing_parts():
    assert naming.build_name({"date": "01.03.2026", "sender": "Finanzamt", "subject": "Tax assessment"}) == \
        "Finanzamt - Tax assessment"
    assert naming.build_name({"date": "", "sender": "", "subject": "Rent increase."}) == "Rent increase"
    assert naming.build_name({"date": "", "sender": "", "subject": ""}) == "Untitled letter"
    assert naming.build_name({"date": "1850-01-01", "sender": "X", "subject": "Y"}) == "X - Y"


def test_suggest_name_uses_llm_reply(monkeypatch):
    seen = {}

    def fake_post(url, json=None, timeout=None):
        seen.update(json)
        reply = {"date": "2026-03-01", "sender": "  Stadtwerke Musterstadt ", "subject": "Monthly instalment increase."}
        return httpx.Response(200, json={"message": {"content": __import__("json").dumps(reply)}},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(naming.OllamaTranslator, "_model", lambda self: "test-model")
    out = naming.suggest_name("Stadtwerke Musterstadt GmbH\n\nMusterstadt, 1. März 2026\n\nIhr Abschlag ...")
    assert out["name"] == "2026-03-01 Stadtwerke Musterstadt - Monthly instalment increase"
    assert seen["format"]["required"] == ["date", "sender", "subject"]
    assert "Letter text:" in seen["messages"][1]["content"]


def test_suggest_name_needs_text():
    with pytest.raises(ValueError):
        naming.suggest_name("   ")
    with pytest.raises(ValueError):
        naming.suggest_name(["", "  "])


def test_prompt_text_has_every_page_with_markers():
    text = naming.prompt_text(["page one", "", "page three"])
    assert "--- Page 1 of 3 ---\npage one" in text
    assert "Page 2" not in text  # a page without text is skipped
    assert "--- Page 3 of 3 ---\npage three" in text
    assert "[text cut]" not in text  # everything fits, so nothing is cut
    assert naming.prompt_text(["", "  "]) == ""


def test_prompt_text_gives_every_page_a_share_when_too_long():
    text = naming.prompt_text(["A" * 5000, "B" * 5000, "C" * 100, "D" * 5000], budget=3000)
    assert all(f"--- Page {n} of 4 ---" in text for n in range(1, 5))  # no page is dropped
    assert "[text cut]" in text
    assert text.count("C") == 100                                    # a short page keeps all its text
    assert text.count("A") == 1450                                   # page 1 counts double ...
    assert text.count("B") == text.count("D") == 725                 # ... and the rest split what is left


def test_suggest_name_sends_all_pages(monkeypatch):
    seen = {}

    def fake_post(url, json=None, timeout=None):
        seen.update(json)
        reply = {"date": "2026-03-01", "sender": "Hausverwaltung Beispiel", "subject": "Termination of rental agreement"}
        return httpx.Response(200, json={"message": {"content": __import__("json").dumps(reply)}},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(naming.OllamaTranslator, "_model", lambda self: "test-model")
    out = naming.suggest_name([f"Seite {n} Text" for n in range(1, 6)])
    content = seen["messages"][1]["content"]
    assert all(f"--- Page {n} of 5 ---\nSeite {n} Text" in content for n in range(1, 6))
    assert out["name"] == "2026-03-01 Hausverwaltung Beispiel - Termination of rental agreement"
