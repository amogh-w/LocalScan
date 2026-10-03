"""AI document names: "<letter date> <sender> - <subject in English>", from the letter's OCR text."""
import re
from datetime import date
from typing import Any

from ..config import settings
from ..translate.ollama import OllamaTranslator

MAX_TEXT_CHARS = 4000
MAX_NAME_CHARS = 90
SYSTEM_PROMPT = """You name scanned letters for a personal document archive.
You get the OCR text of a letter (usually German). Reply with JSON:
- "date": the date the letter was written, as YYYY-MM-DD. Use the date printed in the letter head or \
next to the place name, not deadlines, payment dates or periods mentioned in the text. Empty string if none.
- "sender": who sent it, in the short form people use: an abbreviation if the letter uses one \
(e.g. "LBV NRW", "AOK Rheinland", "Finanzamt Aachen", "Deutsche Bank"). Drop legal forms such as \
GmbH, AG, KG, e.V. Keep proper names in their original language. Never the recipient.
- "subject": what the letter is about, in English, 2 to 6 words, sentence case, no final period \
(e.g. "Repayment of overpaid benefits", "Change of monthly payment", "Tax assessment 2025"). \
If the letter has a subject line (Betreff, often bold above the salutation), base it on that. \
Say only what the text says; do not guess the kind of contract or service.

Never include the recipient's name, address, account or reference numbers. JSON only."""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "date": {"type": "string"},
        "sender": {"type": "string"},
        "subject": {"type": "string"},
    },
    "required": ["date", "sender", "subject"],
}


def _clean(value: str, limit: int) -> str:
    value = re.sub(r"\s+", " ", value or "").strip(" .-:\"'")
    return value[:limit].rstrip()


def _valid_date(value: str) -> str:
    try:
        d = date.fromisoformat((value or "").strip())
    except ValueError:
        return ""
    return d.isoformat() if 1990 <= d.year <= date.today().year + 1 else ""


def build_name(fields: dict[str, str]) -> str:
    when = _valid_date(fields.get("date", ""))
    sender = _clean(fields.get("sender", ""), 40)
    subject = _clean(fields.get("subject", ""), 60)
    head = " ".join(p for p in (when, sender) if p)
    name = f"{head} - {subject}" if head and subject else head or subject
    return name[:MAX_NAME_CHARS].rstrip(" -") or "Untitled letter"


def suggest_name(text: str) -> dict[str, str]:
    """Ask the local LLM for date, sender and subject, and build the name from them."""
    text = text.strip()
    if not text:
        raise ValueError("No text found on the pages yet")
    llm = OllamaTranslator(**settings.section("translator", "ollama"))
    reply = llm.chat_json(SYSTEM_PROMPT, "Letter text:\n\n" + text[:MAX_TEXT_CHARS], SCHEMA)
    fields = {k: str(reply.get(k, "")) for k in ("date", "sender", "subject")}
    return {**fields, "date": _valid_date(fields["date"]), "name": build_name(fields)}
