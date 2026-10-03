from app.ai.pagesignals import analyse, find_marker

BODY = "Ein langer Absatz mit genug Text, damit die Seite nicht als leer gilt. " * 2


def test_page_markers_in_header_and_footer():
    assert find_marker(f"Stadtwerke\n\nSeite 2 von 4\n\n{BODY}") == (2, 4)
    assert find_marker(f"{BODY}\n\nPage 3 of 5") == (3, 5)
    assert find_marker("17. September 2026\nSeite1\n\n" + BODY) == (1, None)  # OCR drops the space
    assert find_marker(f"{BODY}\n\n- 2 -") == (2, None)
    assert find_marker(f"{BODY}\n\n3/4") == (3, 4)
    assert find_marker(f"{BODY}\n\nBlatt 2/3") == (2, 3)


def test_a_mention_in_the_middle_of_the_text_is_not_a_marker():
    middle = "\n\n".join(["Zeile eins", "Zeile zwei", "Zeile drei", "Zeile vier", "Siehe Seite 12 unserer AGB",
                          "Zeile sechs", "Zeile sieben", "Zeile acht", "Zeile neun", "Zeile zehn"])
    assert find_marker(middle) == (None, None)
    assert find_marker("Rechnung vom 12/10/2026\n\n" + BODY) == (None, None)  # a date is not 12 of 10


def test_reference_numbers_are_split_into_document_and_account_level():
    s = analyse("Aktenzeichen:\nQ 70921154 5\nbei Antwort bitte angeben\n\nKundennummer: 4711-0815\n\n" + BODY)
    assert s.doc_refs == ["Q709211545"]
    assert s.account_refs == ["47110815"]
    s = analyse("Rechnungsnummer: RE-2026-0042  Datum 12.03.2026\n\n" + BODY)
    assert s.doc_refs == ["RE20260042"]
    assert analyse("Kundennummer: abc\n\n" + BODY).account_refs == []  # needs digits


def test_letter_structure_tags():
    first = analyse("Hausverwaltung Beispiel GmbH\nMusterstadt, 12. März 2026\nBetreff: Kündigung\n\n"
                    "Sehr geehrter Herr Mustermann,\n\n" + BODY)
    assert first.date_at_top and first.subject and first.salutation and not first.closing
    last = analyse(BODY + "\n\nMit freundlichen Grüßen\nAnlage: Zählerstand")
    assert last.closing and last.attachments and not last.salutation
    cont = analyse("und deshalb bitten wir Sie, die Frist einzuhalten. " + BODY)
    assert cont.starts_lowercase


def test_empty_pages():
    for text in ("", "   ", "ab"):
        assert analyse(text).empty
    assert analyse(BODY).empty is False
    assert analyse(f"Seite 2 von 4\n\n{BODY}").describe().startswith("page marker: Seite 2 von 4")


def test_text_cues_that_one_page_follows_another():
    from app.ai.pagesignals import boundary_score
    cut = "Der Beitrag wird zum nächsten Ersten angepasst, sofern Sie nicht widersprechen und der"
    assert boundary_score(f"Überschrift\n\n{cut}", "neue Betrag gilt ab Januar. Weitere Hinweise folgen.") >= 3  # cut sentence
    assert boundary_score("Fertig.\n\nSeite 1 von 2", "Neuer Abschnitt beginnt hier.\n\nSeite 2 von 2") == 0       # nothing links them
    first, second = "1 Steckdose: 12,00 EUR\n2 Leitung: 9,00 EUR", "3 Leuchte: 45,00 EUR\n4 Anfahrt: 30,00 EUR"
    assert boundary_score(first, second) == 3 and boundary_score(second, first) == -3                          # numbered items
    early, late = "02.05. Gehalt +2.850,00\n14.05. Miete -780,00", "19.05. Tankstelle -58,10\n30.05. Zinsen +3,14"
    assert boundary_score(early, late) == 2 and boundary_score(late, early) == -2                               # dates move forward
    assert boundary_score("14. Juli 2026 Rechnung vom", "28. Mai 2026 Beratung") == 0                           # month names are no items
