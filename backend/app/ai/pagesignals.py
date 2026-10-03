"""Cheap, deterministic facts about the text of one page.

They are evidence for sorting pages into documents: the model sees them next to the text, and a complete
set of page markers ("Seite 2 von 4") decides the order of a document without asking the model.
"""
import re
from dataclasses import dataclass, field

# Page markers sit in the header or footer, so only the first and last lines are searched. A mention in the
# middle of the text ("see page 12 of the terms") must not count.
EDGE_LINES = 4
_WORD = r"(?:seite|page|blatt|bl\.|s\.)"
_OF = r"(?:von|of|/)"
_MARK_TOTAL = re.compile(rf"\b{_WORD}\s*(\d{{1,3}})\s*{_OF}\s*(\d{{1,3}})\b", re.I)
_MARK_NO = re.compile(rf"\b{_WORD}\s*(\d{{1,3}})\b", re.I)
_MARK_FRACTION = re.compile(r"^\s*(\d{1,3})\s*/\s*(\d{1,3})\s*$")
_MARK_DASHED = re.compile(r"^\s*[-–—]\s*(\d{1,3})\s*[-–—]\s*$")

# Reference numbers. "doc" ones identify one document (an invoice, a case); "account" ones are the same on
# every letter from a sender, so they only say "same sender and customer".
_DOC_LABELS = (r"aktenzeichen|geschäftszeichen|az\.|rechnungs-?(?:nummer|nr\.?)|rechnung\s*nr\.?|bescheid-?(?:nummer|nr\.?)"
               r"|vorgangs-?(?:nummer|nr\.?)|invoice\s*(?:no\.?|number)|case\s*(?:no\.?|number)|file\s*(?:no\.?|number)")
_ACCOUNT_LABELS = (r"kunden-?(?:nummer|nr\.?)|vertrags-?(?:nummer|nr\.?)|versicherungs-?(?:nummer|nr\.?)"
                   r"|mitglieds-?(?:nummer|nr\.?)|steuer-?(?:nummer|id|nr\.?)|customer\s*(?:no\.?|number)"
                   r"|contract\s*(?:no\.?|number)")
# The value may follow the label on the next line; groups of digits continue it only on the same line
# ("Q 70921154 5"), so a postcode on the following line is not swallowed.
_VALUE = r"([A-Za-z0-9][A-Za-z0-9/.\-]{0,24}(?:[ \t][0-9]{1,10}){0,2})"
_DOC_REF = re.compile(rf"(?:{_DOC_LABELS})\s*[:.#]?\s*{_VALUE}", re.I)
_ACCOUNT_REF = re.compile(rf"(?:{_ACCOUNT_LABELS})\s*[:.#]?\s*{_VALUE}", re.I)

_SALUTATION = re.compile(r"\b(sehr geehrte[rsn]?|liebe[rs]?|guten tag|dear)\b", re.I)
_CLOSING = re.compile(r"(mit freundlichen gr|freundliche gr|hochachtungsvoll|beste gr|viele gr|herzliche gr"
                      r"|yours (?:sincerely|faithfully)|kind regards|best regards)", re.I)
_SUBJECT = re.compile(r"\b(betreff|betr\.|subject)\b", re.I)
_ATTACHMENTS = re.compile(r"\b(anlagen?\b|enclosures?|anhang)", re.I)
_DATE = re.compile(r"\b\d{1,2}\.\s?(?:\d{1,2}\.|januar|februar|märz|maerz|april|mai|juni|juli|august|september"
                   r"|oktober|november|dezember)\s?\d{2,4}\b", re.I)


@dataclass
class PageSignals:
    chars: int = 0
    empty: bool = True
    page_no: int | None = None
    page_total: int | None = None
    doc_refs: list[str] = field(default_factory=list)
    account_refs: list[str] = field(default_factory=list)
    salutation: bool = False
    closing: bool = False
    subject: bool = False
    date_at_top: bool = False
    attachments: bool = False
    starts_lowercase: bool = False

    @property
    def marker(self) -> str:
        if self.page_no is None:
            return ""
        return f"Seite {self.page_no} von {self.page_total}" if self.page_total else f"Seite {self.page_no}"

    def describe(self) -> str:
        """One line for the model: only what was found."""
        parts = []
        if self.marker:
            parts.append(f"page marker: {self.marker}")
        if self.doc_refs:
            parts.append("document refs: " + ", ".join(self.doc_refs))
        if self.account_refs:
            parts.append("account refs: " + ", ".join(self.account_refs))
        tags = [name for name, on in (("date at top", self.date_at_top), ("subject line", self.subject),
                                      ("salutation", self.salutation), ("closing phrase", self.closing),
                                      ("attachments listed", self.attachments),
                                      ("starts mid-sentence", self.starts_lowercase)) if on]
        if tags:
            parts.append("has: " + ", ".join(tags))
        parts.append(f"{self.chars} chars")
        return " | ".join(parts)


def find_marker(text: str) -> tuple[int | None, int | None]:
    """(page number, page total) from the header or footer lines, or (None, None)."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    edge = lines[:EDGE_LINES] + [ln for ln in lines[-EDGE_LINES:] if ln not in lines[:EDGE_LINES]]
    for ln in edge:
        for pattern in (_MARK_TOTAL, _MARK_NO, _MARK_FRACTION, _MARK_DASHED):
            m = pattern.search(ln)
            if not m:
                continue
            no = int(m.group(1))
            total = int(m.group(2)) if m.lastindex and m.lastindex >= 2 else None
            if 1 <= no <= 200 and (total is None or 1 <= total <= 200):
                return no, total
    return None, None


_MARKER_ONLY = re.compile(
    r"(?:seite|page|blatt)\s*\d{1,3}(?:\s*(?:von|of|/)\s*\d{1,3})?|[-–—]\s*\d{1,3}\s*[-–—]|\d{1,3}\s*/\s*\d{1,3}",
    re.I)
_DATE_NUMERIC = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(?:\d{2,4})?(?!\d)")
_MONTHS = r"januar|februar|märz|maerz|april|mai|juni|juli|august|september|oktober|november|dezember"
_ITEM_NUMBER = re.compile(rf"^\s*(\d{{1,2}})[.)]?\s+(?!(?:{_MONTHS})\b)[A-Za-zÄÖÜäöü]", re.I | re.M)


def body_lines(text: str) -> list[str]:
    """The non-empty lines of a page without lines that only hold a page marker ("Seite 2 von 4")."""
    return [ln.strip() for ln in text.splitlines() if ln.strip() and not _MARKER_ONLY.fullmatch(ln.strip())]


def boundary_score(x: str, y: str) -> int:
    """Evidence from the text itself that page y directly follows page x (negative: y comes before x).

    Three cues, each strong on its own: a sentence cut off at the bottom of x that carries on in lower case
    at the top of y; numbered items that continue (1, 2 on x then 3, 4 on y); and dates that only move
    forward (the transactions of a statement). Page markers are handled elsewhere.
    """
    score = 0
    xl, yl = body_lines(x), body_lines(y)
    if xl and yl:
        head = next((c for c in yl[0] if c.isalpha()), "")
        if len(xl[-1]) > 15 and xl[-1][-1] not in ".!?:;)" and head.islower():
            score += 3
    xd = sorted((int(m), int(d)) for d, m in _DATE_NUMERIC.findall(x))
    yd = sorted((int(m), int(d)) for d, m in _DATE_NUMERIC.findall(y))
    if xd and yd:
        if xd[-1] <= yd[0]:
            score += 2
        elif xd[0] >= yd[-1]:
            score -= 2
    xn = [int(n) for n in _ITEM_NUMBER.findall(x)]
    yn = [int(n) for n in _ITEM_NUMBER.findall(y)]
    if xn and yn:
        if yn[0] == xn[-1] + 1:
            score += 3
        elif xn[0] == yn[-1] + 1:
            score -= 3
    return score


def _refs(pattern: re.Pattern, text: str) -> list[str]:
    found: list[str] = []
    for m in pattern.finditer(text):
        value = re.sub(r"[^A-Z0-9]", "", m.group(1).upper())
        if len(value) >= 4 and sum(c.isdigit() for c in value) >= 2 and value not in found:
            found.append(value)
    return found[:3]


def analyse(text: str) -> PageSignals:
    text = (text or "").strip()
    if len(text) < 40:  # a photo, a blank page or noise
        return PageSignals(chars=len(text), empty=True)
    no, total = find_marker(text)
    first_line = next((ln for ln in text.splitlines() if ln.strip()), "")
    first_letter = next((c for c in first_line if c.isalpha()), "")
    return PageSignals(
        chars=len(text), empty=False, page_no=no, page_total=total,
        doc_refs=_refs(_DOC_REF, text), account_refs=_refs(_ACCOUNT_REF, text),
        salutation=bool(_SALUTATION.search(text)), closing=bool(_CLOSING.search(text[-800:])),
        subject=bool(_SUBJECT.search(text)), date_at_top=bool(_DATE.search(text[:700])),
        attachments=bool(_ATTACHMENTS.search(text)),
        starts_lowercase=bool(first_letter) and first_letter.islower() and no is None,
    )
