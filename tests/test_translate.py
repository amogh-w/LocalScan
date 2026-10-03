import json

import httpx

from app.translate.ollama import OllamaTranslator, _parse_json


def _blocks(*texts):
    return [{"id": f"p0b{i}", "bbox": [0, 0, 1, 1], "lines": [], "text": t} for i, t in enumerate(texts)]


def test_parse_json_strips_think_tags():
    assert _parse_json('<think>hmm {"x": 1}</think>\n{"p0b0": "Hello"}') == {"p0b0": "Hello"}


def test_retries_missing_ids_and_keeps_order(monkeypatch):
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append(json)
        segments = __import__("json").loads(json["messages"][1]["content"].split("translate:\n", 1)[1])
        # First call "forgets" the second segment.
        reply = {k: f"EN({v})" for k, v in segments.items()}
        if len(calls) == 1:
            reply.pop("p0b1")
        return httpx.Response(200, json={"message": {"content": __import__("json").dumps(reply)}},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    t = OllamaTranslator(model="test-model")
    out = t.translate_blocks(_blocks("Hallo", "Welt", "Tschüss"))
    assert out == ["EN(Hallo)", "EN(Welt)", "EN(Tschüss)"]
    assert len(calls) == 2
    assert list(json.loads(calls[1]["messages"][1]["content"].split("translate:\n", 1)[1])) == ["p0b1"]
    assert calls[0]["format"]["required"] == ["p0b0", "p0b1", "p0b2"]


def test_falls_back_to_source_after_repeated_failure(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        return httpx.Response(200, json={"message": {"content": "{}"}}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    assert OllamaTranslator(model="m").translate_blocks(_blocks("Hallo")) == ["Hallo"]
