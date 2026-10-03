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
