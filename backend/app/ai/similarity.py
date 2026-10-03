"""Group and order the pages of a batch scan by keyword similarity. No model is involved.

Divide and conquer: every page becomes a weighted keyword vector (TF-IDF over words, plus word pieces so a
compound like "Rückforderung" still matches "Forderung"). Pages start as their own groups and the two most
similar groups are merged again and again (average linkage) until nothing similar enough is left. Hard
evidence steers the merging: a shared reference number pulls pages together; two pages that cannot share a
document (the same page number, different page totals, two letter openings) are never put together.

Each group is then ordered: complete page markers decide; otherwise the opening page first, the page with a
closing phrase last and the pages in between by how their text continues (pagesignals.boundary_score).
"""
import math
import re
from collections import Counter
from typing import Any

from .pagesignals import PageSignals, analyse, boundary_score

MERGE_AT = 0.03  # average similarity needed to merge two groups; chosen from synthetic batches
SURE_AT = 0.12  # a group whose weakest link is at least this similar is a High confidence group
PIECE = 5  # length of the word pieces used to match compound words
MIN_WORD = 4

STOPWORDS = set("""
also aber alle allem allen aller alles als and auch auf aus bei beim bin bis bitte dann das dass dem den der
des die dies diese diesem diesen dieser dieses doch dort durch eine einem einen einer eines einmal etwa für
gegen habe haben hat hatte hier ihnen ihr ihre ihrem ihren ihrer ihres immer ist jetzt kann kein keine
können machen mehr mein meine mit müssen nach nicht noch nur oder ohne sehr seid sein seine sich sie sind
soll sollen sondern über uns unser unsere unter very von vom vor war waren was weil wenn werden wie wieder
wir wird wollen wurde wurden zum zur zwischen the and for with that this from have your you are not
sehr geehrte geehrter damen herren grüße freundlichen freundliche seite page mfg
""".split())

_WORD = re.compile(r"[a-zäöüß]{%d,}|\d{4,}" % MIN_WORD)


def tokens(text: str) -> list[str]:
    """Keywords of a text: words and long numbers, stopwords removed, plus pieces of long words."""
    out = []
    for w in _WORD.findall(text.lower()):
        if w in STOPWORDS:
            continue
        out.append(w)
        if len(w) >= PIECE + 3 and not w.isdigit():
            out.extend("~" + w[i:i + PIECE] for i in range(0, len(w) - PIECE + 1, 2))
    return out


def vectors(texts: list[str]) -> list[dict[str, float]]:
    """Unit-length TF-IDF vectors; a term in every page weighs nothing."""
    counts = [Counter(tokens(t)) for t in texts]
    df = Counter(term for c in counts for term in c)
    n = len(texts)
    out = []
    for c in counts:
        vec = {}
        for term, tf in c.items():
            idf = math.log((1 + n) / (1 + df[term])) + 1 if n > 1 else 1.0
            piece = 0.5 if term.startswith("~") else 1.0  # a shared fragment is weaker evidence than a shared word
            vec[term] = (1 + math.log(tf)) * idf * piece
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        out.append({k: v / norm for k, v in vec.items()})
    return out


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


def keywords(vec: dict[str, float], count: int = 5) -> list[str]:
    return [k for k, _ in sorted(((k, v) for k, v in vec.items() if not k.startswith("~")), key=lambda kv: -kv[1])[:count]]


def opens_letter(s: PageSignals) -> bool:
    return s.salutation and (s.date_at_top or s.subject)


def cannot_share(a: PageSignals, b: PageSignals) -> bool:
    """True when the two pages cannot belong to the same document."""
    if a.page_no and b.page_no and a.page_total and a.page_total == b.page_total and a.page_no == b.page_no:
        return True  # both claim the same slot
    if a.page_total and b.page_total and a.page_total != b.page_total:
        return True
    if opens_letter(a) and opens_letter(b):
        return True  # a document has one opening
    if a.doc_refs and b.doc_refs and not set(a.doc_refs) & set(b.doc_refs):
        return True  # two different invoice or case numbers
    return False


def affinity(a: PageSignals, b: PageSignals, sim: float) -> float:
    if cannot_share(a, b):
        return -1.0
    bonus = 0.0
    if set(a.doc_refs) & set(b.doc_refs):
        bonus += 0.6
    if set(a.account_refs) & set(b.account_refs):
        bonus += 0.1
    if a.page_total and a.page_total == b.page_total:
        bonus += 0.1
    return sim + bonus


def cluster(texts: list[str], signals: list[PageSignals], vecs: list[dict[str, float]]) -> list[list[int]]:
    """Agglomerative clustering with average linkage and cannot-link constraints."""
    n = len(texts)
    sim = [[affinity(signals[i], signals[j], cosine(vecs[i], vecs[j])) if i != j else 1.0 for j in range(n)] for i in range(n)]
    groups = [[i] for i in range(n)]

    def link(g: list[int], h: list[int]) -> float | None:
        values = [sim[i][j] for i in g for j in h]
        if any(v < 0 for v in values):  # one forbidden pair keeps the groups apart
            return None
        total = max(signals[i].page_total or 0 for i in g + h)
        if total and len(g) + len(h) > total:
            return None  # more pages than the document has
        return sum(values) / len(values)

    while True:
        best, pair = MERGE_AT, None
        for a in range(len(groups)):
            for b in range(a + 1, len(groups)):
                v = link(groups[a], groups[b])
                if v is not None and v >= best:
                    best, pair = v, (a, b)
        if pair is None:
            return groups
        a, b = pair
        groups[a] = groups[a] + groups[b]
        del groups[b]


def order(group: list[int], texts: list[str], signals: list[PageSignals]) -> tuple[list[int], str]:
    """Order one group. Returns (pages, how): "markers", "cues" or "kept" (the order the photos were taken in)."""
    if len(group) == 1:
        return group, "markers"
    numbered = [i for i in group if signals[i].page_no]
    if len(numbered) == len(group) and len({signals[i].page_no for i in group}) == len(group):
        return sorted(group, key=lambda i: signals[i].page_no or 0), "markers"
    first = [i for i in group if opens_letter(signals[i])]
    last = [i for i in group if signals[i].closing or signals[i].attachments]
    start = first[0] if first else None
    end = last[-1] if last and last[-1] != start else None
    middle = [i for i in group if i not in (start, end)]
    if start is None and end is None and all(boundary_score(texts[i], texts[j]) == 0 for i in group for j in group if i != j):
        return sorted(group), "kept"
    out = [start] if start is not None else []
    while middle:
        prev = out[-1] if out else None
        nxt = max(middle, key=lambda c: (boundary_score(texts[prev], texts[c]) if prev is not None else 0, -c))
        middle.remove(nxt)
        out.append(nxt)
    if end is not None:
        out.append(end)
    return out, "cues"


def arrange(texts: list[str], split: bool = True, on_progress=None) -> dict[str, Any]:
    """Same result shape as sort.arrange: {groups, unplaced, why, message}. Indices are positions in `texts`."""
    n = len(texts)
    signals = [analyse(t) for t in texts]
    readable = [i for i in range(n) if not signals[i].empty]
    why = {i: "No text found" for i in range(n) if signals[i].empty}
    vecs = vectors([texts[i] for i in readable])
    sub = [signals[i] for i in readable]
    parts = cluster([texts[i] for i in readable], sub, vecs) if split else [list(range(len(readable)))]
    if on_progress:
        on_progress(1, 2)

    groups = []
    for part in parts:
        pages = [readable[i] for i in part]
        links = [affinity(signals[a], signals[b], cosine(vecs[readable.index(a)], vecs[readable.index(b)]))
                 for a in pages for b in pages if a < b]
        weakest = min(links, default=1.0)
        ordered, how = order(pages, texts, signals)
        reason, conf = "", "high"
        if len(pages) == 1:
            if not split:
                pass
            elif opens_letter(signals[pages[0]]) and signals[pages[0]].closing:
                reason, conf = "A complete one-page letter.", "medium"
            else:
                why[pages[0]] = "Nothing else in this scan resembles it"
                continue
        else:
            shared = sorted(set(sum((keywords(vecs[readable.index(p)], 8) for p in pages), [])),
                            key=lambda k: -sum(vecs[readable.index(p)].get(k, 0) for p in pages))
            common = [k for k in shared if all(vecs[readable.index(p)].get(k) for p in pages)][:4]
            reason = ("Pages share: " + ", ".join(common) + ".") if common else "Pages are linked by similar wording."
            if split and weakest < SURE_AT:
                conf = "medium" if weakest >= MERGE_AT * 1.5 else "low"
            if any(set(signals[a].doc_refs) & set(signals[b].doc_refs) for a in pages for b in pages if a < b):
                reason += " Same reference number."
                conf = "high" if how == "markers" else "medium"
        if how == "kept":
            conf = "low" if conf == "high" else conf
            reason += " The order is the one you photographed them in."
        elif how == "cues":
            conf = "medium" if conf == "high" else conf
            reason += " Order follows the letter structure and how the text continues."
        group = {"pages": ordered, "confidence": conf, "reason": reason.strip()}
        group["order_from_markers"] = how == "markers" and len(pages) > 1
        groups.append(group)
    if on_progress:
        on_progress(2, 2)
    groups.sort(key=lambda g: min(g["pages"]))
    if not split and groups:
        groups[0]["pages"] += [i for i in why]  # pages without text keep a place at the end
        why = {}
    placed = {i for g in groups for i in g["pages"]}
    unplaced = [i for i in range(n) if i not in placed]
    return {"groups": groups, "unplaced": unplaced, "why": {i: why.get(i, "Could not be placed") for i in unplaced},
            "message": None if groups else "No pages could be grouped."}
