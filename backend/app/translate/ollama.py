"""Translate text blocks with a local Ollama model, whole document at a time for context."""
import hashlib
import json
import logging
import re
from collections.abc import Callable
from typing import Any

import httpx

from ..ocr.base import Block

log = logging.getLogger(__name__)

MAX_CHARS_PER_CHUNK = 2500  # a few chunks per letter, so the UI can show progress

SYSTEM_PROMPT = """You are a professional translator of official and business correspondence \
(letters from banks, insurers, landlords, employers, government offices, courts).
Translate each numbered text segment from {src} to {tgt}.

Rules:
- The segments come from one document, in reading order. Use the whole document as context \
so names, terms and tone stay consistent.
- Translate faithfully and naturally, the way a professional would; keep the formal register.
- Keep unchanged, exactly as written: personal names, company and brand names, street names \
(e.g. "Beispielweg 12" and "Hauptstraße 5" stay as they are, never "Example Street"), postcodes, \
city names, IBAN/BIC, account, customer, contract and reference numbers, phone numbers, emails, URLs.
- Amounts: keep the figures, write them the English way (85,00 EUR -> EUR 85.00).
- Salutations and titles are translated (Herrn -> Mr., Frau -> Ms.); the name after them is kept.
- Translate labels around them (e.g. "Kundennummer:" -> "Customer number:").
- Dates: translate month names, keep the day/month/year order of the source.
- A segment may be a fragment (a table cell, a heading, a line of an address). Translate just that fragment.
- Some segments contain line breaks ("\n"): an address, a contact box, a table or a list. Translate them line by line and keep exactly the same number of lines, in the same order.
- If a segment has nothing to translate (only numbers, a name, a code), return it unchanged.
- Never merge, split, drop or add segments. Never add notes or explanations.

Reply with a JSON object mapping every segment id to its translation, nothing else."""


def _chunks(blocks: list[Block]) -> list[list[Block]]:
    out, cur, size = [], [], 0
    for b in blocks:
        if cur and size + len(b["text"]) > MAX_CHARS_PER_CHUNK:
            out.append(cur)
            cur, size = [], 0
        cur.append(b)
        size += len(b["text"])
    if cur:
        out.append(cur)
    return out


def _parse_json(content: str) -> dict[str, Any]:
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
    m = re.search(r"\{.*\}", content, flags=re.S)
    if not m:
        raise ValueError("no JSON object in model reply")
    return json.loads(m.group(0))


class OllamaTranslator:
    name = "ollama"

    def __init__(self, url: str = "http://localhost:11434", model: str = "", temperature: float = 0.1,
                 timeout: float = 600, **_: Any) -> None:
        self.url = url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout

    def list_models(self) -> list[str]:
        r = httpx.get(f"{self.url}/api/tags", timeout=5)
        r.raise_for_status()
        return sorted(m["name"] for m in r.json().get("models", []))

    def _model(self) -> str:
        if not self.model:
            models = self.list_models()
            if not models:
                raise RuntimeError("Ollama has no models installed (run: ollama pull <model>)")
            self.model = models[0]
        return self.model

    def cache_key(self) -> str:
        prompt = hashlib.sha1(SYSTEM_PROMPT.encode()).hexdigest()[:8]
        return f"ollama:{self._model()}:{prompt}"

    def health(self) -> tuple[bool, str]:
        try:
            models = self.list_models()
            return True, f"{self.url} ({len(models)} models, using {self.model or (models[0] if models else 'none')})"
        except Exception as e:  # noqa: BLE001 - shown in the UI
            return False, f"{self.url}: {e}"

    def _chat(self, system: str, user: str, ids: list[str]) -> dict[str, Any]:
        schema = {"type": "object", "properties": {i: {"type": "string"} for i in ids}, "required": ids}
        return self.chat_json(system, user, schema)

    def chat_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        """One chat turn whose reply must match `schema` (Ollama structured outputs)."""
        body: dict[str, Any] = {
            "model": self._model(),
            "stream": False,
            "think": False,
            "format": schema,
            "options": {"temperature": self.temperature, "num_ctx": 16384},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        r = httpx.post(f"{self.url}/api/chat", json=body, timeout=self.timeout)
        if r.status_code == 400 and "think" in r.text:
            body.pop("think")  # model without a thinking switch
            r = httpx.post(f"{self.url}/api/chat", json=body, timeout=self.timeout)
        r.raise_for_status()
        return _parse_json(r.json()["message"]["content"])

    def _translate_chunk(self, chunk: list[Block], context: str, src: str, tgt: str) -> dict[str, str]:
        system = SYSTEM_PROMPT.format(src=src, tgt=tgt)
        result: dict[str, str] = {}
        todo = chunk
        for _attempt in range(3):
            segments = {b["id"]: b["text"] for b in todo}
            user = ""
            if context:
                user += f"Earlier part of the document, for context only (do not translate):\n{context}\n\n"
            user += "Segments to translate:\n" + json.dumps(segments, ensure_ascii=False, indent=1)
            try:
                reply = self._chat(system, user, list(segments))
            except (ValueError, json.JSONDecodeError) as e:
                log.warning("bad translation reply, retrying: %s", e)
                continue
            for b in todo:
                val = reply.get(b["id"])
                if isinstance(val, str) and val.strip():
                    result[b["id"]] = val.strip()
            todo = [b for b in todo if b["id"] not in result]
            if not todo:
                break
        for b in todo:  # give up: keep the source text rather than leave a hole
            log.warning("no translation for %s, keeping source", b["id"])
            result[b["id"]] = b["text"]
        return result

    def translate_blocks(self, blocks: list[Block], src: str = "German", tgt: str = "English",
                         on_progress: Callable[[int, int], None] | None = None) -> list[str]:
        out: dict[str, str] = {}
        context = ""
        chunks = _chunks(blocks)
        for i, chunk in enumerate(chunks):
            if on_progress:
                on_progress(i, len(chunks))
            out.update(self._translate_chunk(chunk, context, src, tgt))
            context = "\n".join(b["text"] for b in chunk)[-1500:]
        return [out[b["id"]] for b in blocks]
