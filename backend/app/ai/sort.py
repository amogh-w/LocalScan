"""Propose which pages of a batch scan belong together and in what order.

Read-only: it returns a proposal and changes nothing. The user reviews it and applies it (see
storage.create_documents_from_pages). Anything that cannot be placed with confidence goes to `unplaced`
instead of being guessed.

Why it is built in steps: a 14B local model cannot group ten pages in one go. A benchmark
(scripts/sort_benchmark.py) showed it invents senders for continuation pages and mixes documents up, even
with page numbers on every page. It is good at small, local questions, so:
  1. Every page is described on its own (sender if the page names it, kind of document, key facts, and
     whether it looks like a first, middle or last page). Descriptions cannot contaminate each other.
  2. A page that starts a document is that document's anchor.
  3. Every other page is attached to an anchor: by rule when the evidence is hard (a shared reference
     number, a unique named sender), otherwise by a small multiple-choice question to the model.
  4. Each document is ordered: page markers if every page has one; else first page first, closing page last,
     and the model orders only the pages in between.
"""
import hashlib
import itertools
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .. import jobs
from ..config import settings
from ..translate.ollama import OllamaTranslator
from . import naming, similarity
from .pagesignals import PageSignals, analyse, boundary_score

log = logging.getLogger(__name__)

MAX_PAGES = 40  # keeps the number of model calls and the prompts bounded
HEAD, TAIL = 350, 250  # characters of a page's text the model sees from its start and its end
CONFIDENCE = ("high", "medium", "low")  # strongest first
ROLES = ("first", "middle", "last", "only", "unclear")

DESCRIBE_SYSTEM = """You look at ONE scanned page and describe it. Describe only what is on this page.

- sender: the organisation or person that sent the document, ONLY if this page names it (letterhead, \
signature, footer). Otherwise an empty string. Never guess it.
- document: what kind of document this page belongs to and what it is about, in 5 to 10 words, in English \
(for example "letter announcing a change of the monthly energy payment"). A page in the middle of a document \
belongs to the same kind of document as its first page, so infer it from the content.
- facts: the most distinctive details on this page (names, amounts, dates, reference numbers, product names), \
at most 12 words.
- role: "first" if this page starts a document (letterhead, date, recipient, salutation), "last" if it ends \
one (closing phrase, signature, enclosures), "only" if it is a complete one-page document, "middle" if it \
clearly continues from an earlier page and goes on to a later one, "unclear" otherwise.

Reply with JSON only."""

DESCRIBE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sender": {"type": "string"},
        "document": {"type": "string"},
        "facts": {"type": "string"},
        "role": {"type": "string", "enum": list(ROLES)},
    },
    "required": ["sender", "document", "facts", "role"],
}

ASSIGN_SYSTEM = """You decide which document a scanned page belongs to. You get the page and the documents \
found in the same batch, each shown by its first page and the pages already assigned to it. For EVERY \
document, rate how likely the page is part of it, from 0 (certainly not) to 10 (certainly), in the order the \
documents are listed.

Judge by the subject and the text: a continuation page picks up the topic, the numbers or the sentence of \
its document. A first page often announces what follows (an enclosure, a calculation, "see the next \
page"), and the later pages then hold those details. Later pages add NEW details (other figures, dates, \
sections) that the first page does not repeat, so rate a page low only when its subject, sender or numbers \
clearly belong to something else, not because it says more than the first page. The page may be one of \
several pages of a document, and the document's other pages may not be listed. Page markers are strong \
evidence: "Seite 2 von 2" belongs with the document whose first page says "Seite 1 von 2". Documents about \
similar topics are still \
different documents, and a page belongs to at most one of them. If the page fits none, rate every document \
low. Two documents from the same sender are told apart only by their content or reference numbers.

Give a short reason first. Reply with JSON only."""

# A page is attached to a document when the model's ratings (averaged over two candidate orders, which cancels
# the bias towards the first-listed document) are at least this high and clearly ahead of the runner-up.
# Chosen from data (115 decisions on random synthetic batches, scripts/sort_benchmark.py): the right document
# is rated 10 almost always and the best wrong one is rated 0 almost always (never above 4), so 5 / 2 keeps
# 110 of 115 and gets none wrong, while 6 would send 11 correct pages to the review tray.
MIN_RATING = 5.0
MIN_MARGIN = 2.0


def assign_schema(candidates: int) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "reason": {"type": "string"},
            "ratings": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 10},
                        "minItems": candidates, "maxItems": candidates},
        },
        "required": ["reason", "ratings"],
    }

FOLLOW_SYSTEM = """You decide whether page Y comes directly after page X in the same document. You get the \
end of page X and the start of page Y. Answer true when Y plausibly follows X directly: a sentence, list, \
table or numbered sequence is cut off at the end of X and carries on at the start of Y, or Y clearly \
introduces what X announced. Answer false when Y looks like it comes before X, belongs to a different part \
of the document, or X is complete and Y starts something unrelated. Give a short reason first. Reply with \
JSON only."""

FOLLOW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"reason": {"type": "string"}, "follows": {"type": "boolean"}},
    "required": ["reason", "follows"],
}

ORDER_NOTES = {"sure": "", "model": "The order of the middle pages rests on how their text continues.",
               "guess": "The order of the middle pages is a guess: check it."}

Chat = Callable[[str, str, dict[str, Any]], dict[str, Any]]
Progress = Callable[[int, int], None]


def _ollama_chat(system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
    return OllamaTranslator(**settings.section("translator", "ollama")).chat_json(system, user, schema)


@dataclass
class Page:
    index: int
    text: str
    signals: PageSignals
    desc: dict[str, str] = field(default_factory=lambda: {"sender": "", "document": "", "facts": "", "role": "unclear"})


def digest(i: int, text: str, s: PageSignals) -> str:
    """What the model sees of one page: its number, the rule-based facts, and the start and end of the text."""
    if s.empty:
        return f"Page {i + 1} | NO TEXT"
    flat = re.sub(r"\s*\n+\s*", " / ", text.strip())
    if len(flat) <= HEAD + TAIL + 40:
        body = f"TEXT: {flat}"
    else:
        body = f"START: {flat[:HEAD].rstrip()}\nEND: {flat[-TAIL:].lstrip()}"
    return f"Page {i + 1} | {s.describe()}\n{body}"


_describe_cache: dict[str, dict[str, str]] = {}


def describe(page: Page, chat: Chat) -> dict[str, str]:
    """Step 1: describe one page on its own. Cached by text, so sorting a batch twice is cheap."""
    key = hashlib.sha1((DESCRIBE_SYSTEM + page.text).encode()).hexdigest()
    if key in _describe_cache:
        return _describe_cache[key]
    text = page.text.strip()
    if len(text) > 1400:
        text = text[:900] + "\n[...]\n" + text[-450:]
    for _ in range(2):
        try:
            raw = chat(DESCRIBE_SYSTEM, "Page text:\n\n" + text, DESCRIBE_SCHEMA)
            desc = {k: str(raw.get(k) or "").strip() for k in ("sender", "document", "facts", "role")}
            if desc["role"] not in ROLES:
                desc["role"] = "unclear"
            if len(_describe_cache) > 2000:
                _describe_cache.clear()
            _describe_cache[key] = desc
            return desc
        except (ValueError, KeyError, TypeError) as e:
            log.warning("could not describe page %d: %s", page.index + 1, e)
    return page.desc  # unclear: the page is then placed by other evidence or not at all


def _norm_sender(name: str) -> str:
    name = re.sub(r"\b(gmbh|ag|kg|ohg|ug|e\.?\s?v\.?|mbh|co\.?|inc\.?|ltd\.?)\b", " ", name.lower())
    return re.sub(r"[^a-zäöüß0-9]+", "", name)


def _is_anchor(p: Page) -> bool:
    """Does this page start a document?"""
    s = p.signals
    if s.empty or (s.page_no or 1) > 1:
        return False
    return p.desc["role"] in ("first", "only") or (s.salutation and s.date_at_top and s.subject)


def _lower(confidence: str) -> str:
    return CONFIDENCE[min(CONFIDENCE.index(confidence) + 1, len(CONFIDENCE) - 1)]


def _weakest(confidences: list[str]) -> str:
    return max(confidences, key=CONFIDENCE.index) if confidences else "low"


@dataclass
class Cluster:
    anchor: int
    pages: list[int]
    confidence: dict[int, str] = field(default_factory=dict)  # per attached page
    notes: list[str] = field(default_factory=list)


def _fits(page: Page, cluster: Cluster, pages: list[Page]) -> bool:
    """Hard rules from page markers: totals must agree, and a page number can only be taken once."""
    s = page.signals
    for m in cluster.pages:
        o = pages[m].signals
        if s.page_total and o.page_total and s.page_total != o.page_total:
            return False
        if s.page_no and o.page_no and s.page_no == o.page_no and s.page_total == o.page_total:
            return False
    totals = {pages[m].signals.page_total for m in cluster.pages if pages[m].signals.page_total}
    return not totals or len(cluster.pages) < max(totals)


def _rate(page: Page, candidates: list[Cluster], pages: list[Page], chat: Chat) -> list[float] | None:
    """Ask the model to rate how likely the page belongs to each candidate document (0-10, in order)."""
    lines = []
    for n, c in enumerate(candidates, 1):
        a = pages[c.anchor]
        others = "; ".join(pages[m].desc["document"] for m in c.pages if m != c.anchor) or "none yet"
        lines.append(f"Document {n} | sender: {a.desc['sender'] or '(not stated)'} | about: {a.desc['document']}"
                     f" | facts: {a.desc['facts']}\nother pages so far: {others}\n"
                     f"first page: {digest(a.index, a.text, a.signals)}")
    d = page.desc
    user = (f"PAGE TO ASSIGN\nabout: {d['document']} | facts: {d['facts']}\n{digest(page.index, page.text, page.signals)}"
            "\n\nDOCUMENTS\n\n" + "\n\n".join(lines))
    try:
        ratings = chat(ASSIGN_SYSTEM, user, assign_schema(len(candidates))).get("ratings")
        if not isinstance(ratings, list) or len(ratings) != len(candidates):
            raise ValueError("wrong number of ratings")
        return [min(10.0, max(0.0, float(r))) for r in ratings]
    except (ValueError, KeyError, TypeError) as e:
        log.warning("could not rate page %d: %s", page.index + 1, e)
        return None


def _assign(page: Page, candidates: list[Cluster], pages: list[Page], chat: Chat,
            unassigned: list[Page], total_documents: int) -> tuple[Cluster | None, str, str]:
    """Step 3: attach one page to a document. Returns (cluster or None, confidence, why)."""
    s = page.signals
    if s.page_no and s.page_total:
        # "Seite 2 von 2" fits only a document that says "Seite 1 von 2", has no page 2 yet, and has no rival
        # page claiming the same slot: then the page number alone settles it.
        same_total = [c for c in candidates if pages[c.anchor].signals.page_total == s.page_total]
        rivals = [q for q in unassigned if q is not page and (q.signals.page_no, q.signals.page_total) == (s.page_no, s.page_total)]
        if len(same_total) == 1 and not rivals:
            return same_total[0], "medium", "its page number fits only this document"
    refs = set(page.signals.doc_refs)
    if refs:
        same_ref = [c for c in candidates if refs & {r for m in c.pages for r in pages[m].signals.doc_refs}]
        if len(same_ref) == 1:
            return same_ref[0], "high", "shares a document reference number"
    sender = _norm_sender(page.desc["sender"])
    anchors_by_sender = [c for c in candidates if sender and _norm_sender(pages[c.anchor].desc["sender"]) == sender]
    if len(anchors_by_sender) == 1:
        return anchors_by_sender[0], "high", "names the same sender"

    # One answer between look-alike documents is unreliable and depends on the order they are listed in. So
    # ask twice, in opposite orders, and average the ratings.
    forward = _rate(page, candidates, pages, chat)
    backward = _rate(page, candidates[::-1], pages, chat)
    answers = [r for r in (forward, backward[::-1] if backward else None) if r is not None]
    if not answers:
        return None, "low", "the model gave no usable answer"
    scores = [sum(col) / len(col) for col in zip(*answers)]
    ranked = sorted(range(len(candidates)), key=lambda i: -scores[i])
    best = scores[ranked[0]]
    runner_up = scores[ranked[1]] if len(ranked) > 1 else 0.0
    log.debug("page %d ratings %s", page.index + 1, [round(s, 1) for s in scores])
    if best < MIN_RATING:
        if len(candidates) == 1 and page.desc["role"] in ("middle", "last"):
            # A lone candidate gets no comparison, and the model then nitpicks (it rates a genuine continuation
            # 0-2 because the first page does not repeat its details). The page says it continues an earlier
            # page and no other document can take it, so it very probably belongs here. Say so, modestly.
            return candidates[0], ("medium" if total_documents > 1 else "low"), \
                "continues an earlier page and fits no other document"
        return None, "low", "does not clearly fit any document"
    if best - runner_up < MIN_MARGIN:
        return None, "low", "could belong to more than one document"
    chosen = candidates[ranked[0]]
    # Two documents from one sender are only distinguishable by content, so be modest about it.
    twins = [c for c in candidates if c is not chosen and sender
             and _norm_sender(pages[c.anchor].desc["sender"]) == _norm_sender(pages[chosen.anchor].desc["sender"])]
    return chosen, ("low" if twins else "medium"), ("chosen by content; another document has the same sender"
                                                    if twins else "matches the content")


def _follows(x: Page, y: Page, chat: Chat) -> bool:
    """Ask the model one narrow question: does page y directly continue page x?"""
    user = f"END OF PAGE X:\n{x.text.strip()[-300:]}\n\nSTART OF PAGE Y:\n{y.text.strip()[:300]}"
    try:
        return bool(chat(FOLLOW_SYSTEM, user, FOLLOW_SCHEMA).get("follows"))
    except (ValueError, KeyError, TypeError) as e:
        log.warning("could not compare pages %d and %d: %s", x.index + 1, y.index + 1, e)
        return False


def _order(cluster: Cluster, pages: list[Page], chat: Chat) -> str:
    """Step 4: put the cluster's pages in reading order. Returns how sure it is: sure, model or guess.

    The first page goes first and a closing page last. The pages in between are ordered by the text cues in
    `boundary_score`; only when those do not decide, the model is asked whether one page continues another.
    """
    anchor = cluster.anchor
    rest = [m for m in cluster.pages if m != anchor]
    lasts = [m for m in rest if pages[m].desc["role"] == "last" or pages[m].signals.closing]
    last = max(lasts, key=lambda m: (pages[m].desc["role"] == "last", pages[m].signals.closing), default=None)
    middles = [m for m in rest if m != last]
    tail = [] if last is None else [last]
    if len(middles) <= 1:
        cluster.pages = [anchor, *middles, *tail]
        return "sure"
    if len(middles) > 5:  # too many orders to try; keep the order the pages came in
        cluster.pages = [anchor, *middles, *tail]
        return "guess"

    orders = list(itertools.permutations(middles))
    cues: dict[tuple[int, int], int] = {}

    def total(perm: tuple[int, ...], extra: dict[tuple[int, int], int]) -> int:
        chain = [anchor, *perm, *tail]
        return sum(cues.setdefault((a, b), boundary_score(pages[a].text, pages[b].text)) + extra.get((a, b), 0)
                   for a, b in zip(chain, chain[1:]))

    def best(extra: dict[tuple[int, int], int]) -> tuple[tuple[int, ...], int]:
        ranked = sorted(range(len(orders)), key=lambda k: (-total(orders[k], extra), k))  # ties: order of appearance
        return orders[ranked[0]], total(orders[ranked[0]], extra) - total(orders[ranked[1]], extra)

    choice, margin = best({})
    status = "sure"
    if margin < 3:  # the text cues do not decide: ask about each pair that could be neighbours
        extra = {(x, y): 4 for x in (anchor, *middles) for y in (*middles, *tail) if x != y
                 and _follows(pages[x], pages[y], chat)}
        choice, margin = best(extra)
        status = "model" if margin >= 3 else "guess"
    cluster.pages = [anchor, *choice, *tail]
    return status


def _check_markers(group: dict[str, Any], signals: list[PageSignals]) -> None:
    """Let page markers decide the order of a group, and lower the confidence when they contradict it."""
    pages = group["pages"]
    numbers = [signals[i].page_no for i in pages]
    present = [n for n in numbers if n is not None]
    totals = {signals[i].page_total for i in pages if signals[i].page_total}

    def note(text: str) -> None:
        group["reason"] = (group["reason"] + " " + text).strip()

    if len(set(present)) != len(present):
        group["confidence"] = "low"
        note("Two pages carry the same page number.")
    elif len(pages) > 1 and len(present) == len(pages):
        pages.sort(key=lambda i: signals[i].page_no)  # the markers decide, not the model
        group["order_from_markers"] = True
        if totals == {len(pages)} and sorted(present) == list(range(1, len(pages) + 1)):
            # This confirms the ORDER, not who belongs to the group: two documents can both have four pages,
            # so it must not raise the confidence.
            group["markers_complete"] = True
            note(f"Page numbers 1 to {len(pages)} are all present.")
    elif len(present) >= 2 and present != sorted(present):
        group["confidence"] = "low"
        note("The page numbers on the pages disagree with this order.")
    if len(totals) > 1:
        group["confidence"] = "low"
        note("The pages disagree on how many pages the document has.")
    elif len(totals) == 1 and next(iter(totals)) != len(pages):
        group["confidence"] = _lower(group["confidence"])
        note(f"The pages say {next(iter(totals))} pages but {len(pages)} were found.")
    if any(signals[i].page_no and signals[i].page_total and signals[i].page_no > signals[i].page_total for i in pages):
        group["confidence"] = "low"


def arrange(texts: list[str], split: bool = True, chat: Chat | None = None,
            on_progress: Progress | None = None, method: str = "similarity") -> dict[str, Any]:
    """Group and order pages from their texts. Indices are 0-based positions in `texts`.

    Returns {groups: [{pages, confidence, reason, order_from_markers?}], unplaced: [index],
    why: {index: reason}, message}. `chat(system, user, schema)` is the model call; tests replace it.
    """
    n = len(texts)
    if n < 2:
        raise ValueError("Add at least two pages to sort")
    if n > MAX_PAGES:
        raise ValueError(f"Sorting handles up to {MAX_PAGES} pages at once; sort the batch in two parts")
    pages = [Page(i, t, analyse(t)) for i, t in enumerate(texts)]
    if all(p.signals.empty for p in pages):
        raise ValueError("No text found on the pages yet")
    if method == "similarity":  # keyword similarity, no model (similarity.py)
        return similarity.arrange(texts, split, on_progress)
    chat = chat or _ollama_chat
    readable = [p for p in pages if not p.signals.empty]
    why = {p.index: "No text found" for p in pages if p.signals.empty}
    steps = len(readable) * 2
    done = 0

    def tick() -> None:
        nonlocal done
        done += 1
        if on_progress:
            on_progress(done, steps)

    for p in readable:  # step 1
        p.desc = describe(p, chat)
        tick()

    if not split:  # one document: just put the pages in order
        anchors = [p for p in readable if _is_anchor(p)]
        first = (anchors or sorted(readable, key=lambda p: -(p.signals.date_at_top + p.signals.salutation
                                                              + p.signals.subject)))[0]
        cluster = Cluster(first.index, [p.index for p in readable])
        status = _order(cluster, pages, chat)
        group = {"pages": cluster.pages, "confidence": {"sure": "high", "model": "medium", "guess": "low"}[status],
                 "reason": ORDER_NOTES[status]}
        _check_markers(group, [p.signals for p in pages])
        if group.get("markers_complete"):  # the pages are given as one document, so complete page numbers settle it
            group["confidence"] = "high"
        group["pages"] = group["pages"] + [i for i in why]  # pages without text keep their place at the end
        return {"groups": [group], "unplaced": [], "why": {}, "message": None}

    anchors = [p for p in readable if _is_anchor(p)]  # step 2
    if not anchors:
        return {"groups": [], "unplaced": list(range(n)), "why": {**{i: "Could not tell where a document starts" for i in range(n)}, **why},
                "message": "No first page of a document was found, so the pages could not be grouped."}
    clusters = [Cluster(p.index, [p.index], {p.index: "high"}) for p in anchors]

    # Pages with a page number go first: their slot in a document is a hard constraint, so a wrong guess on an
    # unnumbered page must not be able to use it up.
    decided = {c.anchor for c in clusters}
    for p in sorted(readable, key=lambda p: (p.signals.page_no is None, p.signals.page_no or 0, p.index)):  # step 3
        if p.index in decided:
            tick()
            continue
        decided.add(p.index)
        candidates = [c for c in clusters if _fits(p, c, pages)]
        if not candidates:
            why[p.index] = "Fits none of the documents"
        else:
            chosen, conf, reason = _assign(p, candidates, pages, chat, [q for q in readable if q.index not in decided],
                                           len(clusters))
            if chosen is None:
                why[p.index] = reason[0].upper() + reason[1:]
            else:
                chosen.pages.append(p.index)
                chosen.confidence[p.index] = conf
                chosen.notes.append(f"Page {p.index + 1} {reason}.")
        tick()

    groups = []
    for c in clusters:  # step 4
        status = _order(c, pages, chat)
        conf = _weakest(list(c.confidence.values()))
        if status != "sure":
            conf = _weakest([conf, "low" if status == "guess" else "medium"])
        reason = " ".join(c.notes + ([ORDER_NOTES[status]] if ORDER_NOTES[status] else []))
        group = {"pages": c.pages, "confidence": conf, "reason": reason if len(c.pages) > 1 else "A single page."}
        if len(c.pages) == 1 and pages[c.anchor].desc["role"] == "first":
            # A first page implies more pages. Finding none is a warning sign, not a confident one-pager.
            group["confidence"] = "low"
            group["reason"] = "This looks like the first page of a longer document, but no other page was found for it."
        _check_markers(group, [p.signals for p in pages])
        groups.append(group)
    groups.sort(key=lambda g: min(g["pages"]))
    placed = {i for g in groups for i in g["pages"]}
    unplaced = [i for i in range(n) if i not in placed]
    return {"groups": groups, "unplaced": unplaced, "why": {i: why.get(i, "Could not be placed") for i in unplaced},
            "message": None}


_progress: dict[str, dict[str, Any]] = {}


def progress(doc_id: str) -> dict[str, Any] | None:
    """What a running proposal is doing: {stage, done, total}, or None when none is running."""
    return _progress.get(doc_id)


def propose(doc_id: str, split: bool = True, with_names: bool = True,
            on_progress: Progress | None = None) -> dict[str, Any]:
    """The full proposal for a document: reads the pages (OCR is cached), arranges them, suggests names."""
    try:
        return _propose(doc_id, split, with_names, on_progress)
    finally:
        _progress.pop(doc_id, None)


def _propose(doc_id: str, split: bool, with_names: bool, on_progress: Progress | None) -> dict[str, Any]:
    def report(stage: str, done: int = 0, total: int = 0) -> None:
        _progress[doc_id] = {"stage": stage, "done": done, "total": total}

    report("Reading the pages")
    pages = jobs.read_pages(doc_id)
    texts = jobs.page_texts(pages)

    def step(done: int, total: int) -> None:
        report("Comparing the pages", done, total)
        if on_progress:
            on_progress(done, total)

    report("Comparing the pages")
    arrangement = arrange(texts, split, on_progress=step)
    ids = [p["id"] for p in pages]
    groups = []
    for n, g in enumerate(arrangement["groups"]):
        if split and with_names:
            report("Naming the documents", n, len(arrangement["groups"]))
        name = ""
        if split and with_names:
            try:
                name = naming.suggest_name([texts[i] for i in g["pages"]])["name"]
            except Exception:  # noqa: BLE001 - a missing name must not lose the proposal
                log.warning("could not suggest a name for a group", exc_info=True)
        groups.append({
            "page_ids": [ids[i] for i in g["pages"]], "positions": [i + 1 for i in g["pages"]],
            "confidence": g["confidence"], "reason": g["reason"], "name": name,
            "order_from_markers": bool(g.get("order_from_markers")),
        })
    unplaced = [{"page_id": ids[i], "position": i + 1, "why": arrangement["why"].get(i, "Could not be placed")}
                for i in arrangement["unplaced"]]
    return {"groups": groups, "unplaced": unplaced, "message": arrangement["message"], "split": split}
