"""The page sorter, with a fake model: the logic is tested here, its accuracy by scripts/sort_benchmark.py."""
import random
import re

import pytest

from app.ai import sort
from app.ai.pagesignals import analyse

FILLER = "Dieser Satz füllt die Seite mit genug Text, damit sie nicht als leer gilt. " * 2
LABELS = ("Alpha", "Beta", "Gamma", "Delta")


def arrange_model(*a, **kw):
    return sort.arrange(*a, method="model", **kw)


def page(label: str, n: int, first: bool = False, last: bool = False, marker: str = "", extra: str = "") -> str:
    """A synthetic page of the document `label`; `[part n]` lets the fake model tell the order."""
    parts = [f"[part {n}]"]
    if first:
        parts += [f"{label} GmbH", "Musterstadt, 12. März 2026", f"Betreff: {label} Thema", "Sehr geehrter Herr Mustermann,"]
    parts.append(f"{label} {FILLER}")
    if extra:
        parts.append(extra)
    if last:
        parts.append("Mit freundlichen Grüßen")
    if marker:
        parts.append(marker)
    parts.append(f"[part {n}]")
    return "\n\n".join(parts)


class FakeModel:
    """Answers the sorter's questions from keywords in the text and records what was asked."""

    def __init__(self, ratings=None):
        self.calls: list[str] = []
        self.ratings = ratings  # optional override: function(page_about, docs) -> list[int]

    def __call__(self, system, user, schema):
        if system == sort.DESCRIBE_SYSTEM:
            self.calls.append("describe")
            label = next((l for l in LABELS if l in user), "Other")
            role = "only" if "Sehr geehrter" in user and "Mit freundlichen" in user else \
                "first" if "Sehr geehrter" in user else "last" if "Mit freundlichen" in user else "middle"
            return {"sender": f"{label} GmbH" if f"{label} GmbH" in user else "", "document": f"{label} letter",
                    "facts": "", "role": role}
        if system == sort.ASSIGN_SYSTEM:
            self.calls.append("assign")
            about = re.search(r"PAGE TO ASSIGN\nabout: (\w+)", user).group(1)
            docs = re.findall(r"^Document \d+ \|.*?about: (\w+)", user, re.M)
            ratings = self.ratings(about, docs) if self.ratings else [10 if about == d else 0 for d in docs]
            return {"reason": "r", "ratings": ratings}
        if system == sort.FOLLOW_SYSTEM:
            self.calls.append("follow")
            x_end, y_start = user.split("START OF PAGE Y:")
            x = int(re.findall(r"\[part (\d+)\]", x_end)[-1])
            y = int(re.findall(r"\[part (\d+)\]", y_start)[0])
            return {"reason": "r", "follows": y == x + 1}
        raise AssertionError("unexpected question")


@pytest.fixture(autouse=True)
def fresh_cache():
    sort._describe_cache.clear()


def arrange_shuffled(docs: dict[str, list[str]], seed: int = 1, model: FakeModel | None = None, **kw):
    """Shuffle the pages of several documents together; returns (result, labelled pages, model)."""
    model = model or FakeModel()
    items = [(f"{name}{i + 1}", text) for name, pages in docs.items() for i, text in enumerate(pages)]
    random.Random(seed).shuffle(items)
    result = arrange_model([t for _, t in items], chat=model, **kw)
    return result, [name for name, _ in items], model


def labelled(result, names):
    return [[names[i] for i in g["pages"]] for g in result["groups"]]


def test_groups_and_orders_documents_without_any_page_numbers():
    docs = {
        "Alpha": [page("Alpha", 1, first=True), page("Alpha", 2), page("Alpha", 3), page("Alpha", 4, last=True)],
        "Beta": [page("Beta", 1, first=True), page("Beta", 2), page("Beta", 3, last=True)],
        "Gamma": [page("Gamma", 1, first=True), page("Gamma", 2, last=True)],
    }
    result, names, model = arrange_shuffled(docs)
    assert sorted(labelled(result, names)) == sorted([[f"Alpha{i}" for i in range(1, 5)],
                                                      [f"Beta{i}" for i in range(1, 4)], ["Gamma1", "Gamma2"]])
    assert result["unplaced"] == []
    assert all(g["confidence"] in ("medium", "high") for g in result["groups"])
    assert model.calls.count("describe") == 9


def test_page_numbers_attach_pages_without_asking_which_document():
    docs = {
        "Alpha": [page("Alpha", 1, first=True, marker="Seite 1 von 2"), page("Alpha", 2, last=True, marker="Seite 2 von 2")],
        "Beta": [page("Beta", 1, first=True, marker="Seite 1 von 3"), page("Beta", 2, marker="Seite 2 von 3"),
                 page("Beta", 3, last=True, marker="Seite 3 von 3")],
    }
    result, names, model = arrange_shuffled(docs)
    assert sorted(labelled(result, names)) == [["Alpha1", "Alpha2"], ["Beta1", "Beta2", "Beta3"]]
    assert "assign" not in model.calls and "follow" not in model.calls  # page numbers decided everything
    assert all(g["order_from_markers"] for g in result["groups"])


def test_a_shared_reference_number_attaches_pages_without_asking():
    ref = "Aktenzeichen: AZ-1111/26"
    docs = {
        "Alpha": [page("Alpha", 1, first=True, extra=ref), page("Alpha", 2, last=True, extra="Az. AZ-1111/26")],
        "Beta": [page("Beta", 1, first=True, extra="Aktenzeichen: AZ-2222/26"),
                 page("Beta", 2, last=True, extra="Az. AZ-2222/26")],
    }
    result, names, model = arrange_shuffled(docs)
    assert sorted(labelled(result, names)) == [["Alpha1", "Alpha2"], ["Beta1", "Beta2"]]
    assert "assign" not in model.calls
    assert all(g["confidence"] == "high" for g in result["groups"])


def test_numbered_items_and_dates_order_the_middle_pages_without_the_model():
    items = lambda a, b: "\n".join(f"{i} Position {i}: {i * 10},00 EUR" for i in range(a, b))  # noqa: E731
    docs = {"Alpha": [page("Alpha", 1, first=True), page("Alpha", 2, extra=items(1, 3)),
                      page("Alpha", 3, extra=items(3, 5)), page("Alpha", 4, last=True)],
            "Beta": [page("Beta", 1, first=True), page("Beta", 2, last=True)]}
    for seed in range(4):
        result, names, model = arrange_shuffled(docs, seed)
        assert ["Alpha1", "Alpha2", "Alpha3", "Alpha4"] in labelled(result, names)
        assert "follow" not in model.calls


def test_when_the_text_does_not_decide_the_model_is_asked_whether_a_page_follows():
    docs = {"Alpha": [page("Alpha", 1, first=True), page("Alpha", 2), page("Alpha", 3), page("Alpha", 4, last=True)],
            "Beta": [page("Beta", 1, first=True), page("Beta", 2, last=True)]}
    result, names, model = arrange_shuffled(docs, seed=3)
    assert ["Alpha1", "Alpha2", "Alpha3", "Alpha4"] in labelled(result, names)
    assert "follow" in model.calls
    alpha = next(g for g, n in zip(result["groups"], labelled(result, names)) if n[0] == "Alpha1")
    assert alpha["confidence"] == "medium"  # the order rests on the model's judgement


def test_pages_that_fit_nothing_or_hold_no_text_go_to_the_tray_with_a_reason():
    texts = [page("Alpha", 1, first=True), page("Beta", 1, first=True), "", page("Delta", 2)]
    result = arrange_model(texts, chat=FakeModel())
    assert [g["pages"] for g in result["groups"]] == [[0], [1]]
    assert result["unplaced"] == [2, 3]
    assert result["why"][2] == "No text found" and "clearly fit" in result["why"][3]


def test_a_first_page_with_nothing_attached_is_low_confidence():
    result = arrange_model([page("Alpha", 1, first=True), page("Beta", 1, first=True)], chat=FakeModel())
    assert [g["confidence"] for g in result["groups"]] == ["low", "low"]
    assert "first page of a longer document" in result["groups"][0]["reason"]


def test_a_model_that_always_picks_the_first_listed_document_cannot_decide_alone():
    """Position bias: the two opposite orders cancel out, so the page goes to the tray instead of a coin flip."""
    texts = [page("Alpha", 1, first=True), page("Beta", 1, first=True), page("Gamma", 2)]
    result = arrange_model(texts, chat=FakeModel(ratings=lambda about, docs: [10] + [0] * (len(docs) - 1)))
    assert result["unplaced"] == [2] and "more than one" in result["why"][2]


def test_a_lone_candidate_gets_a_continuation_page_even_if_the_model_is_harsh():
    harsh = FakeModel(ratings=lambda about, docs: [0] * len(docs))
    # One document in the whole batch: attached, but only as a low-confidence guess.
    result = arrange_model([page("Alpha", 1, first=True), page("Alpha", 2)], chat=harsh)
    assert result["groups"][0]["pages"] == [0, 1] and result["groups"][0]["confidence"] == "low"
    # The other document is complete (page numbers), so this page can only be the first document's: medium.
    texts = [page("Alpha", 1, first=True), page("Beta", 1, first=True, marker="Seite 1 von 2"),
             page("Beta", 2, last=True, marker="Seite 2 von 2"), page("Alpha", 2)]
    result = arrange_model(texts, chat=harsh)
    assert sorted(g["pages"] for g in result["groups"]) == [[0, 3], [1, 2]]
    assert next(g for g in result["groups"] if 3 in g["pages"])["confidence"] == "medium"


def test_page_numbers_confirm_the_order_but_never_raise_the_confidence():
    group = {"pages": [1, 0, 2], "confidence": "medium", "reason": ""}
    sig = [analyse(page("Alpha", n, marker=f"Seite {n} von 3")) for n in (1, 2, 3)]
    sort._check_markers(group, sig)
    assert group["pages"] == [0, 1, 2] and group["order_from_markers"] and group["markers_complete"]
    assert group["confidence"] == "medium"  # two documents can both have three pages


def test_page_numbers_that_contradict_a_group_lower_its_confidence():
    def check(markers, pages, confidence="high"):
        group = {"pages": pages, "confidence": confidence, "reason": ""}
        sort._check_markers(group, [analyse(page("Alpha", i, marker=m)) for i, m in enumerate(markers)])
        return group

    assert check(["Seite 1 von 4", "Seite 2 von 4", "Seite 3 von 4"], [0, 1, 2])["confidence"] == "medium"  # one missing
    assert check(["Seite 1 von 2", "Seite 1 von 2"], [0, 1])["confidence"] == "low"                         # same number twice
    assert check(["Seite 2", "", "Seite 1"], [0, 1, 2])["confidence"] == "low"                              # order disagrees
    assert check(["Seite 1 von 2", "Seite 2 von 3"], [0, 1])["confidence"] == "low"                         # totals differ


def test_order_only_mode_returns_one_document_with_every_page():
    texts = [page("Alpha", 3, last=True, marker="Seite 3 von 3"), page("Alpha", 1, first=True, marker="Seite 1 von 3"),
             page("Alpha", 2, marker="Seite 2 von 3"), ""]
    result = arrange_model(texts, split=False, chat=FakeModel())
    assert result["unplaced"] == [] and len(result["groups"]) == 1
    assert result["groups"][0]["pages"] == [1, 2, 0, 3]  # by page number, the page without text last
    assert result["groups"][0]["confidence"] == "high"


def test_a_page_is_described_once_even_if_the_batch_is_sorted_again():
    model = FakeModel()
    texts = [page("Alpha", 1, first=True), page("Alpha", 2, last=True)]
    arrange_model(texts, chat=model)
    arrange_model(texts, chat=model)
    assert model.calls.count("describe") == 2


def test_input_is_checked():
    with pytest.raises(ValueError, match="at least two"):
        arrange_model([page("Alpha", 1)])
    with pytest.raises(ValueError, match="up to 40"):
        arrange_model([page("Alpha", 1)] * 41)
    with pytest.raises(ValueError, match="No text"):
        arrange_model(["", ""])


def test_no_first_page_means_nothing_is_guessed():
    result = arrange_model([page("Alpha", 2), page("Alpha", 3)], chat=FakeModel())
    assert result["groups"] == [] and result["unplaced"] == [0, 1] and "first page" in result["message"]


def test_progress_is_reported():
    seen = []
    arrange_model([page("Alpha", 1, first=True), page("Alpha", 2, last=True)], chat=FakeModel(),
                 on_progress=lambda done, total: seen.append((done, total)))
    assert seen[-1][0] == seen[-1][1] and seen == sorted(seen)
