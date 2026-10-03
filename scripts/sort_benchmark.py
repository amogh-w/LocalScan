"""Benchmark the page sorter on SYNTHETIC batches (never real letters), with the real local model.

    uv run python scripts/sort_benchmark.py [seeds] [scenario-number ...]    (SEED_START=100 for fresh batches)

Each scenario builds a batch of pages from made-up documents, shuffles it with several seeds, runs
`sort.arrange` and checks the result against the known truth. Reported per scenario:
  grouping: the pages were split into exactly the right documents
  order:    ... and every document's pages are in the right order
  wrong+high: groups the sorter marked "high" confidence that are wrong (this should stay at 0)
"""
import os
import random
import string
import sys
import time
from dataclasses import dataclass

sys.path[:0] = ["backend"]
from app.ai import sort  # noqa: E402

# --- made-up documents ------------------------------------------------------------------------------

STADTWERKE = [
    "Stadtwerke Musterstadt GmbH\nMusterweg 1 · 12345 Musterstadt\n\nHerrn\nMax Mustermann\nBeispielweg 12\n12345 Musterstadt\n\n"
    "Musterstadt, 12. März 2026\nKundennummer: 4711-0815\nRechnungsnummer: SW-2026-0457\n\n"
    "Betreff: Anpassung Ihres monatlichen Abschlags\n\nSehr geehrter Herr Mustermann,\n\n"
    "vielen Dank für Ihr Vertrauen in unsere Energieversorgung. Auf Grundlage Ihres Verbrauchs im vergangenen "
    "Abrechnungszeitraum passen wir Ihren monatlichen Abschlag an. Die Einzelheiten der Berechnung finden Sie auf "
    "den folgenden Seiten.",
    "Berechnung Ihres neuen Abschlags\n\nVerbrauch im Abrechnungszeitraum: 3.200 kWh\nArbeitspreis: 32,10 ct/kWh\n"
    "Grundpreis: 14,50 EUR pro Monat\nBisheriger Abschlag: 75,00 EUR\nNeuer Abschlag: 85,00 EUR\n\n"
    "Die Anpassung ist notwendig, weil Ihr Verbrauch und die gestiegenen Beschaffungskosten dazu geführt haben, dass "
    "die bisherigen Abschläge die voraussichtlichen Kosten nicht mehr decken. Der neue Abschlag gilt",
    "ab dem 1. November 2026 und wird jeweils zum 15. eines Monats von Ihrem Konto abgebucht. Sollten Sie mit der "
    "Anpassung nicht einverstanden sein, können Sie uns Ihren Wunsch nach einem anderen Abschlag mitteilen.\n\n"
    "Zahlungshinweise\n\nBitte beachten Sie, dass Ihr SEPA-Lastschriftmandat weiterhin gültig bleibt. Ein Tätigwerden "
    "Ihrerseits ist nicht erforderlich. Die Abbuchung erfolgt automatisch.",
    "Ihre Rechte und Ansprechpartner\n\nBei Fragen erreichen Sie unseren Kundenservice montags bis freitags von 8 bis "
    "16 Uhr unter der Telefonnummer 01234 567890. Sie können auch jederzeit schriftlich Einspruch gegen die Anpassung "
    "einlegen.\n\nMit freundlichen Grüßen\nStadtwerke Musterstadt GmbH\n\nAnlage: Preisblatt Strom 2026",
]

HAUSVERWALTUNG = [
    "Hausverwaltung Beispiel GmbH\nBeispielstraße 5 · 12345 Musterstadt\n\nFrau\nErika Musterfrau\nBeispielweg 12\n"
    "12345 Musterstadt\n\nMusterstadt, 20. April 2026\nAktenzeichen: NK-2025-118\nMieternummer: 0042\n\n"
    "Betreff: Nebenkostenabrechnung für das Jahr 2025\n\nSehr geehrte Frau Musterfrau,\n\nanbei erhalten Sie die "
    "Betriebskostenabrechnung für Ihre Wohnung im Beispielweg 12 für den Zeitraum vom 1. Januar bis 31. Dezember 2025. "
    "Die Abrechnung gliedert sich in eine Übersicht der Kosten, die Verteilung auf die Mietparteien und Ihr Ergebnis.",
    "Übersicht der umlagefähigen Kosten\n\nGrundsteuer: 1.240,00 EUR\nWasserversorgung: 2.180,00 EUR\n"
    "Müllabfuhr: 960,00 EUR\nHausreinigung: 1.450,00 EUR\nGebäudeversicherung: 1.120,00 EUR\n"
    "Summe der Gesamtkosten: 6.950,00 EUR\n\nDie Verteilung der Kosten erfolgt nach dem Anteil Ihrer Wohnfläche an der "
    "Gesamtfläche des Hauses, soweit nicht ein anderer",
    "Verteilerschlüssel vereinbart ist. Ihre Wohnfläche beträgt 68 Quadratmeter bei einer Gesamtfläche von 540 "
    "Quadratmetern. Daraus ergibt sich Ihr Anteil von 12,6 Prozent.\n\nIhr Ergebnis\n\nIhr Anteil an den Gesamtkosten: "
    "875,70 EUR\nGeleistete Vorauszahlungen: 780,00 EUR\nNachzahlung: 95,70 EUR",
    "Hinweise zur Zahlung und zu Einwendungen\n\nBitte überweisen Sie den Nachzahlungsbetrag innerhalb von vier Wochen "
    "auf das unten genannte Konto. Einwendungen gegen die Abrechnung müssen Sie innerhalb von zwölf Monaten nach "
    "Zugang schriftlich geltend machen.\n\nMit freundlichen Grüßen\nHausverwaltung Beispiel GmbH\n\nAnlage: Belegliste",
]

FINANZAMT = [
    "Finanzamt Beispielstadt\nAmtsstraße 3 · 12345 Beispielstadt\n\nHerrn\nMax Mustermann\nBeispielweg 12\n"
    "12345 Musterstadt\n\nBeispielstadt, 3. Juni 2026\nSteuernummer: 123/456/78901\nBescheid-Nr.: ESt-2025-9981\n\n"
    "Einkommensteuerbescheid für 2025\n\nSehr geehrter Herr Mustermann,\n\naufgrund Ihrer Steuererklärung wird die "
    "Einkommensteuer für das Jahr 2025 wie folgt festgesetzt. Die Berechnung entnehmen Sie bitte der Anlage auf der "
    "Rückseite dieses Bescheids.",
    "Berechnung der festgesetzten Steuer\n\nZu versteuerndes Einkommen: 38.420,00 EUR\nFestgesetzte Einkommensteuer: "
    "6.215,00 EUR\nBereits geleistete Vorauszahlungen: 6.800,00 EUR\nErstattungsbetrag: 585,00 EUR\n\nDer "
    "Erstattungsbetrag wird auf Ihr Konto überwiesen.\n\nRechtsbehelfsbelehrung\n\nGegen diesen Bescheid können Sie "
    "innerhalb eines Monats nach Bekanntgabe Einspruch einlegen.\n\nMit freundlichen Grüßen\nIm Auftrag",
]


def invoice(number: int, date: str, room: str, items: list[tuple[str, int]], header: bool) -> list[str]:
    """A 2-page invoice from the same sender with the same customer number as every other one."""
    net = sum(price for _, price in items)
    head = f"Elektro Meier GmbH · Rechnungsnummer: {number}\n\n" if header else ""
    p1 = (f"{head}Elektro Meier GmbH\nGewerbestraße 7 · 12345 Musterstadt\n\nHerrn\nMax Mustermann\nBeispielweg 12\n\n"
          f"Musterstadt, {date}\nKundennummer: 5503\n" + (f"Rechnungsnummer: {number}\n" if header else "") +
          f"\nRechnung für Elektroarbeiten {room}\n\nSehr geehrter Herr Mustermann,\n\nfür die ausgeführten Arbeiten "
          "stellen wir Ihnen folgende Positionen in Rechnung:\n\n"
          + "\n".join(f"{i} {text}: {price},00 EUR" for i, (text, price) in enumerate(items[:2], 1)))
    p2 = (f"{head}" + "\n".join(f"{i} {text}: {price},00 EUR" for i, (text, price) in enumerate(items[2:], 3)) +
          f"\n\nSumme netto: {net},00 EUR\nUmsatzsteuer 19 Prozent: {net * 19 // 100},00 EUR\n"
          f"Rechnungsbetrag: {net + net * 19 // 100},00 EUR\n\nBitte überweisen Sie den Betrag innerhalb von 14 Tagen.\n\n"
          "Mit freundlichen Grüßen\nElektro Meier GmbH")
    return [p1, p2]


BANK = [
    "Deutsche Beispielbank AG\nBankplatz 1 · 12345 Beispielstadt\n\nHerrn\nMax Mustermann\nBeispielweg 12\n12345 Musterstadt\n\n"
    "Kontoauszug Nr. 5 / 2026\nKontonummer: 0123456789\nDatum: 31. Mai 2026\n\nAlter Kontostand: 2.140,55 EUR\n\n"
    "02.05. Gehalt Firma Beispiel GmbH +2.850,00\n03.05. Miete Hausverwaltung Beispiel GmbH -780,00",
    "05.05. Stadtwerke Musterstadt Abschlag -85,00\n07.05. Supermarkt Einkauf -64,32\n11.05. Tankstelle Muster -58,10\n"
    "14.05. Versicherung Beitrag -39,90\n19.05. Restaurant Zur Linde -41,50\n22.05. Online-Shop Bestellung -129,99\n"
    "25.05. Geldautomat -100,00",
    "28.05. Zinsen Sparkonto +3,14\n30.05. Telefon Rechnung -29,99\n\nNeuer Kontostand: 3.512,19 EUR\n\nBitte prüfen Sie "
    "diesen Kontoauszug auf Richtigkeit. Einwendungen sind unverzüglich zu erheben.\n\nDeutsche Beispielbank AG\n"
    "Ihr Kundenservice",
]

VERSICHERUNG = [
    "Musterversicherung AG\nVersicherungsallee 9 · 12345 Beispielstadt\n\nHerrn\nMax Mustermann\nBeispielweg 12\n12345 Musterstadt\n\n"
    "Beispielstadt, 2. November 2026\nVersicherungsnummer: HV-778812-3\n\nBetreff: Beitragsanpassung Ihrer "
    "Privathaftpflichtversicherung\n\nSehr geehrter Herr Mustermann,\n\nzum 1. Januar 2027 passen wir den Beitrag Ihrer "
    "Privathaftpflichtversicherung an. Der Jahresbeitrag steigt von 54,00 EUR auf 61,20 EUR.",
    "Warum wir den Beitrag anpassen\n\nDie Schadenaufwendungen in der Privathaftpflicht sind in den vergangenen Jahren "
    "deutlich gestiegen. Um Ihren Versicherungsschutz weiterhin sicherzustellen, ist eine Anpassung erforderlich.\n\n"
    "Ihr Sonderkündigungsrecht\n\nSie können den Vertrag innerhalb eines Monats nach Zugang dieses Schreibens kündigen.\n\n"
    "Mit freundlichen Grüßen\nMusterversicherung AG",
]

GEHALT = [
    "Beispiel Maschinenbau GmbH\nGehaltsabrechnung für Mai 2026\n\nPersonalnummer: 20417\nMitarbeiter: Max Mustermann\n\n"
    "Brutto: 3.850,00 EUR\nLohnsteuer: 612,40 EUR\nSolidaritätszuschlag: 0,00 EUR\nKrankenversicherung: 312,90 EUR\n"
    "Rentenversicherung: 358,05 EUR\nArbeitslosenversicherung: 50,05 EUR\nPflegeversicherung: 65,45 EUR\n"
    "Netto: 2.451,15 EUR\n\nAuszahlung auf das Konto bei der Deutschen Beispielbank AG.",
]

ARZT = [
    "Praxis Dr. med. Beispiel\nGesundheitsweg 4 · 12345 Beispielstadt\n\nHerrn\nMax Mustermann\nBeispielweg 12\n12345 Musterstadt\n\n"
    "Beispielstadt, 14. Juli 2026\nRechnungsnummer: 2026-4471\nPatientennummer: 33901\n\nPrivatliquidation über ärztliche "
    "Leistungen\n\nSehr geehrter Herr Mustermann,\n\nfür die Behandlung am 9. Juli 2026 erlaube ich mir, Ihnen folgende "
    "Leistungen in Rechnung zu stellen:\n\nBeratung, ausführlich: 21,86 EUR\nUntersuchung des Bewegungsapparates: 29,14 EUR",
    "Blutentnahme: 4,66 EUR\nLaboruntersuchung Blutbild: 17,49 EUR\nBeratung, kurz: 10,72 EUR\n\nGesamtbetrag: 83,87 EUR\n\n"
    "Bitte überweisen Sie den Betrag innerhalb von 30 Tagen. Reichen Sie die Rechnung bei Ihrer Krankenversicherung ein.\n\n"
    "Mit freundlichen Grüßen\nDr. med. Beispiel",
]

MOBILFUNK = [
    "Musterfon AG\nTelefonstraße 8 · 12345 Beispielstadt\n\nHerrn\nMax Mustermann\nBeispielweg 12\n12345 Musterstadt\n\n"
    "Beispielstadt, 4. Juni 2026\nKundennummer: 9928-1177\nRechnungsnummer: MF-2026-06-88213\n\nIhre Rechnung für den "
    "Mobilfunkvertrag\n\nSehr geehrter Herr Mustermann,\n\nanbei erhalten Sie Ihre Rechnung für den Monat Mai 2026. Den "
    "Rechnungsbetrag buchen wir von Ihrem Konto ab.\n\nGrundpreis Tarif Mobil M: 19,99 EUR\nOptionen: 4,99 EUR",
    "Einzelverbindungsnachweis\n\n03.05. 09:14 Mobilfunk national 2 Min 0,00 EUR\n05.05. 18:40 Mobilfunk national 11 Min "
    "0,00 EUR\n09.05. 12:02 Festnetz national 4 Min 0,00 EUR\n12.05. 20:31 Ausland Österreich 6 Min 1,20 EUR\n"
    "17.05. 08:55 Mobilfunk national 3 Min 0,00 EUR\n21.05. 19:10 Mobilfunk national 18 Min 0,00 EUR\n"
    "26.05. 13:47 Festnetz national 7 Min 0,00 EUR",
    "Datenverbrauch\n\nVerbrauchtes Datenvolumen im Mai: 7,3 GB von 10 GB\n\nRechnungsbetrag netto: 26,18 EUR\n"
    "Umsatzsteuer 19 Prozent: 4,97 EUR\nRechnungsbetrag brutto: 31,15 EUR\n\nMit freundlichen Grüßen\nMusterfon AG\n"
    "Ihr Kundenservice",
]

ALL_DOCS = [STADTWERKE, HAUSVERWALTUNG, FINANZAMT, BANK, VERSICHERUNG, GEHALT, ARZT, MOBILFUNK]

PHOTO = "ab"  # what OCR returns for a photo without text


@dataclass
class Item:
    doc: int | None  # which document the page belongs to (None: a page that has no place)
    no: int          # position inside that document
    text: str


def with_markers(doc: int, pages: list[str], at_top: bool) -> list[Item]:
    n = len(pages)
    return [Item(doc, k, (f"Seite {k + 1} von {n}\n\n{t}" if at_top else f"{t}\n\nSeite {k + 1} von {n}"))
            for k, t in enumerate(pages)]


def plain(doc: int, pages: list[str]) -> list[Item]:
    return [Item(doc, k, t) for k, t in enumerate(pages)]


SCENARIOS = {
    1: ("4+4+2 pages, with page markers",
        lambda: with_markers(0, STADTWERKE, False) + with_markers(1, HAUSVERWALTUNG, False)
        + with_markers(2, FINANZAMT, True)),
    2: ("4+4+2 pages, NO page markers",
        lambda: plain(0, STADTWERKE) + plain(1, HAUSVERWALTUNG) + plain(2, FINANZAMT)),
    3: ("two similar invoices, invoice number on every page",
        lambda: plain(0, invoice(1001, "8. Mai 2026", "im Wohnzimmer",
                                 [("Steckdose setzen, 4 Stück", 120), ("Leitung verlegen, 12 Meter", 96),
                                  ("Deckenleuchte montieren", 45), ("Anfahrt", 30)], True))
        + plain(1, invoice(1002, "15. Mai 2026", "in der Küche",
                           [("Herdanschluss herstellen", 140), ("Unterputzdose setzen, 2 Stück", 60),
                            ("Sicherung austauschen", 85), ("Anfahrt", 30)], True))),
    4: ("two similar invoices, NO invoice number on page 2 (genuinely ambiguous)",
        lambda: plain(0, invoice(1001, "8. Mai 2026", "im Wohnzimmer",
                                 [("Steckdose setzen, 4 Stück", 120), ("Leitung verlegen, 12 Meter", 96),
                                  ("Deckenleuchte montieren", 45), ("Anfahrt", 30)], False))
        + plain(1, invoice(1002, "15. Mai 2026", "in der Küche",
                           [("Herdanschluss herstellen", 140), ("Unterputzdose setzen, 2 Stück", 60),
                            ("Sicherung austauschen", 85), ("Anfahrt", 30)], False))),
    5: ("4+2 pages with markers, plus a blank page and a photo",
        lambda: with_markers(0, STADTWERKE, False) + with_markers(1, FINANZAMT, True)
        + [Item(None, 0, ""), Item(None, 0, PHOTO)]),
}


def random_batch(seed: int) -> list[Item]:
    """A random mix of 3-4 of the eight documents (at most 14 pages); page numbers on some of them, and
    sometimes a blank page."""
    rng = random.Random(1000 + seed)
    while True:
        picked = rng.sample(range(len(ALL_DOCS)), rng.choice([3, 4]))
        if sum(len(ALL_DOCS[d]) for d in picked) <= 14:
            break
    items: list[Item] = []
    for d in picked:
        if len(ALL_DOCS[d]) > 1 and rng.random() < 0.6:
            items += with_markers(d, ALL_DOCS[d], rng.random() < 0.3)
        else:
            items += plain(d, ALL_DOCS[d])
    if rng.random() < 0.25:
        items.append(Item(None, 0, ""))
    return items


SCENARIOS[6] = ("random mix of 3-4 of eight different documents (page numbers on some)", None)


def evaluate(batch: list[Item], result: dict) -> tuple[bool, bool, int]:
    truth: dict[frozenset[int], list[int]] = {}
    for doc in {it.doc for it in batch if it.doc is not None}:
        members = sorted((i for i, it in enumerate(batch) if it.doc == doc), key=lambda i: batch[i].no)
        truth[frozenset(members)] = members
    orphans = {i for i, it in enumerate(batch) if it.doc is None}
    got = {frozenset(g["pages"]): g for g in result["groups"]}
    grouping = set(got) == set(truth) and set(result["unplaced"]) == orphans
    order = grouping and all(g["pages"] == truth[k] for k, g in got.items())
    # "Confidently wrong" means a high-confidence group that holds a page which does not belong in it, or has
    # its pages in the wrong order. A group that is only missing pages is not wrong: the missing pages show up
    # in the review tray, where the user sees them.
    def wrong(pages: list[int]) -> bool:
        owner = next((t for k, t in truth.items() if set(pages) & k), None)
        if owner is None or not set(pages) <= set(owner):
            return True
        return [i for i in owner if i in pages] != pages

    wrong_high = sum(1 for g in got.values() if g["confidence"] == "high" and wrong(g["pages"]))
    return grouping, order, wrong_high


def describe(batch: list[Item], result: dict) -> str:
    def label(i: int) -> str:
        it = batch[i]
        return f"{string.ascii_uppercase[it.doc] if it.doc is not None else '-'}{it.no + 1}"
    groups = "  ".join("[" + " ".join(label(i) for i in g["pages"]) + f"]{g['confidence'][0]}" for g in result["groups"])
    tray = " ".join(label(i) for i in result["unplaced"])
    return f"{groups}   tray: {tray or 'none'}"


def main() -> None:
    args = [int(a) for a in sys.argv[1:]]
    seeds = args[0] if args else 5
    chosen = args[1:] or list(SCENARIOS)
    first_seed = int(os.environ.get("SEED_START", 0))  # use a fresh range to test on batches never tuned on
    calls = {"n": 0}

    def counting_chat(system, user, schema):
        calls["n"] += 1
        return sort._ollama_chat(system, user, schema)

    for number in chosen:
        title, build = SCENARIOS[number]
        base = build() if build else []
        n_ok = o_ok = bad = 0
        spent = 0.0
        misses: list[str] = []
        calls["n"] = 0
        for seed in range(first_seed, first_seed + seeds):
            if build is None:  # the random scenario draws a different mix for every seed
                base = random_batch(seed)
            order = list(range(len(base)))
            random.Random(seed).shuffle(order)
            batch = [base[i] for i in order]
            t0 = time.time()
            result = sort.arrange([it.text for it in batch], chat=counting_chat, method=os.environ.get("METHOD", "similarity"))
            spent += time.time() - t0
            grouping, ordered, wrong_high = evaluate(batch, result)
            n_ok += grouping
            o_ok += ordered
            bad += wrong_high
            if not ordered:
                misses.append(f"seed {seed}: {describe(batch, result)}")
        print(f"\n{number}. {title}\n   grouping {n_ok}/{seeds}   order {o_ok}/{seeds}   wrong+high {bad}   "
              f"{spent / seeds:.1f}s/run   model calls {calls['n']} for {seeds} runs")
        for miss in misses[:6]:
            print(f"   miss, {miss}")


if __name__ == "__main__":
    main()
