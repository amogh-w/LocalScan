import pytest

from app import library, storage
from app.db import connection as db


@pytest.fixture(autouse=True)
def data_dir(tmp_path):
    storage.init(tmp_path)
    yield tmp_path
    db.close()


def test_folder_tree_and_cycles():
    finance = library.create_folder("Finance")
    tax = library.create_folder("Tax", finance["id"])
    assert {f["name"]: f["parent_id"] for f in library.list_folders()} == {"Finance": None, "Tax": finance["id"]}
    with pytest.raises(library.LibraryError):
        library.update_folder(finance["id"], parent_id=tax["id"], move=True)  # into its own child
    library.update_folder(tax["id"], name="Taxes", parent_id=None, move=True)
    assert {f["name"]: f["parent_id"] for f in library.list_folders()} == {"Finance": None, "Taxes": None}
    with pytest.raises(library.LibraryError):
        library.create_folder("   ")


def test_deleting_a_folder_keeps_its_documents():
    home = library.create_folder("Home")
    rent = library.create_folder("Rent", home["id"])
    sub = library.create_folder("2026", rent["id"])
    doc = storage.create_doc("Letter")
    library.set_folder([doc["id"]], rent["id"])
    library.delete_folder(rent["id"])
    assert storage.load_doc(doc["id"])["folder_id"] == home["id"]          # moved up, not deleted
    assert {f["id"]: f["parent_id"] for f in library.list_folders()}[sub["id"]] == home["id"]
    assert [d["id"] for d in storage.list_docs(folder=home["id"])] == [doc["id"]]


def test_tags_are_case_insensitive_and_unique():
    a = library.create_tag("Tax")
    assert library.create_tag("tax")["id"] == a["id"]  # same tag
    b = library.create_tag("Insurance", "mauve")
    assert b["color"] == "mauve"
    with pytest.raises(library.LibraryError):
        library.update_tag(b["id"], name="TAX")
    with pytest.raises(library.LibraryError):
        library.create_tag("Bad colour", "#ff0000")


def test_tagging_filtering_and_bulk():
    tax, urgent = library.create_tag("Tax"), library.create_tag("Urgent")
    folder = library.create_folder("Inbox")
    d1, d2, d3 = (storage.create_doc(n) for n in ("one", "two", "three"))
    library.set_tags(d1["id"], [tax["id"], urgent["id"]])
    library.add_tag([d2["id"], d3["id"]], tax["id"])
    library.remove_tag([d3["id"]], tax["id"])
    library.set_folder([d1["id"], d2["id"]], folder["id"])
    assert [t["name"] for t in storage.load_doc(d1["id"])["tags"]] == ["Tax", "Urgent"]
    assert {d["name"] for d in storage.list_docs(tag=tax["id"])} == {"one", "two"}
    assert {d["name"] for d in storage.list_docs(folder="none")} == {"three"}
    assert {d["name"] for d in storage.list_docs(folder=folder["id"], tag=urgent["id"])} == {"one"}
    assert {t["name"]: t["count"] for t in library.list_tags()} == {"Tax": 2, "Urgent": 1}
    library.delete_tag(urgent["id"])
    assert [t["name"] for t in storage.load_doc(d1["id"])["tags"]] == ["Tax"]
    # Editing a document (e.g. a rename) keeps its folder.
    with storage.editing(d1["id"]) as d:
        d["name"] = "renamed"
    assert storage.load_doc(d1["id"])["folder_id"] == folder["id"]
