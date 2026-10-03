"""AI document names: "<letter date> <sender> - <subject in English>", from the letter's OCR text."""
import re
from datetime import date
from typing import Any

from ..config import settings
from ..languages import scan_names, target_language
from ..translate.ollama import OllamaTranslator

# Characters of letter text sent to the model (about 6k tokens, well inside its 16k context). Longer
# documents are cut page by page, see prompt_text.
TEXT_BUDGET = 20000
MAX_NAME_CHARS = 90
SYSTEM_PROMPT = """You name scanned letters for a personal document archive.
You get the OCR text of a letter (usually {src}), page by page; it may have several pages. The first \
page usually carries the date, the sender and the subject line; later pages add detail, so use them when \
the first page does not make the subject clear. Reply with JSON:
- "date": the date the letter was written, as YYYY-MM-DD. Use the date printed in the letter head or \
next to the place name, not deadlines, payment dates or periods mentioned in the text. Empty string if none.
- "sender": who sent it, in the short form people use: an abbreviation if the letter uses one \
(e.g. "LBV NRW", "AOK Rheinland", "Finanzamt Aachen", "Deutsche Bank"). Drop legal forms such as \
GmbH, AG, KG, e.V. Keep proper names in their original language. Never the recipient.
- "subject": what the letter is about, in {tgt}, 2 to 6 words, sentence case, no final period \
(examples in English: "Repayment of overpaid benefits", "Change of monthly payment", "Tax assessment 2025"). \
If the letter has a subject line (e.g. German "Betreff", often bold above the salutation), base it on that. \
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


def _shares(lengths: list[int], budget: int) -> list[int]:
    """Characters each page may use. Pages that fit keep all their text; the rest split what is left,
    with the first page counting double (it has the letterhead, date and subject line)."""
    weights = [2.0] + [1.0] * (len(lengths) - 1)
    shares = [0] * len(lengths)
    pending = list(range(len(lengths)))
    left = budget
    while pending:
        total = sum(weights[i] for i in pending)
        fits = [i for i in pending if lengths[i] <= left * weights[i] / total]
        if not fits:
            for i in pending:
                shares[i] = int(left * weights[i] / total)
            break
        for i in fits:
            shares[i] = lengths[i]
            left -= lengths[i]
        pending = [i for i in pending if i not in fits]
    return shares


def prompt_text(pages: list[str], budget: int = TEXT_BUDGET) -> str:
    """The text of every page that has any, with page markers. A page is cut only when the whole
    document exceeds the budget, so no page is ever dropped."""
    texts = [(i, t.strip()) for i, t in enumerate(pages) if t and t.strip()]
    if not texts:
        return ""
    parts = []
    for (i, text), share in zip(texts, _shares([len(t) for _, t in texts], budget)):
        cut = text[:share].rstrip()
        parts.append(f"--- Page {i + 1} of {len(pages)} ---\n{cut}" + ("\n[text cut]" if share < len(text) else ""))
    return "Letter text:\n\n" + "\n\n".join(parts)


def suggest_name(pages: list[str] | str) -> dict[str, str]:
    """Ask the local LLM for date, sender and subject from the text of all pages, and build the name."""
    prompt = prompt_text([pages] if isinstance(pages, str) else pages)
    if not prompt:
        raise ValueError("No text found on the pages yet")
    llm = OllamaTranslator(**settings.section("translator", "ollama"))
    reply = llm.chat_json(SYSTEM_PROMPT.format(src=scan_names(), tgt=target_language().name), prompt, SCHEMA)
    fields = {k: str(reply.get(k, "")) for k in ("date", "sender", "subject")}
    return {**fields, "date": _valid_date(fields["date"]), "name": build_name(fields)}
