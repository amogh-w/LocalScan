"""Deleting moves a document to the trash; only purging deletes it for good."""
import pytest

from app import library, storage
from app.api import documents
from app.db import blobs
from app.db import connection as db


@pytest.fixture
def doc(tmp_path):
    storage.init(tmp_path)
    d = storage.create_doc("Letter")
    sha = blobs.put(b"photo", "jpg")
    with storage.editing(d["id"]) as x:
        x["pages"] = [{"id": storage.new_id(), "original": sha, "clean": None, "width": 10, "height": 10,
                       "corners": [[0, 0], [1, 0], [1, 1], [0, 1]]}]
    yield d["id"]
    db.close()


def test_delete_goes_to_the_trash_and_can_be_restored(doc):
    documents.delete_doc(doc)
    assert storage.list_docs() == [] and [d["id"] for d in storage.list_docs(trashed=True)] == [doc]
    assert storage.load_doc(doc)["pages"]  # nothing was removed
    storage.collect_garbage()
    blob = storage.load_doc(doc)["pages"][0]["original"]
    assert blobs.path(blob).exists()
    documents.bulk(documents.BulkAction(ids=[doc], action="restore"))
    assert [d["id"] for d in storage.list_docs()] == [doc] and storage.list_docs(trashed=True) == []


def test_purge_and_empty_trash_delete_for_good(doc):
    documents.bulk(documents.BulkAction(ids=[doc], action="delete"))
    assert documents.empty_trash() == {"deleted": 1}
    assert storage.list_docs(trashed=True) == []
    with pytest.raises(KeyError):
        storage.load_doc(doc)
    other = storage.create_doc("Other")["id"]
    documents.delete_doc(other, permanent=True)
    with pytest.raises(KeyError):
        storage.load_doc(other)


def test_old_trash_is_purged_on_startup_but_recent_trash_is_kept(doc, tmp_path):
    fresh = storage.create_doc("Fresh")["id"]
    storage.trash_doc([doc, fresh])
    with db.transaction() as c:
        c.execute("UPDATE documents SET deleted_at = deleted_at - ? WHERE id = ?", ((storage.TRASH_DAYS + 1) * 86400, doc))
    assert storage.purge_trash(storage.TRASH_DAYS * 86400) == 1
    assert [d["id"] for d in storage.list_docs(trashed=True)] == [fresh]


def test_trashed_documents_do_not_count_in_folders_or_tags(doc):
    folder = library.create_folder("Inbox")
    tag = library.create_tag("Tax")
    library.set_folder([doc], folder["id"])
    library.set_tags(doc, [tag["id"]])
    storage.trash_doc([doc])
    assert library.list_tags()[0]["count"] == 0
    assert [f["count"] for f in library.list_folders()] == [0]


def test_deleted_pages_are_kept_in_the_trash(doc):
    page = storage.load_doc(doc)["pages"][0]
    documents.delete_page(doc, page["id"])
    assert storage.load_doc(doc)["pages"] == []
    (kept,) = storage.list_docs(trashed=True)
    assert kept["name"] == "Letter (deleted page)" and len(kept["pages"]) == 1
    assert blobs.path(kept["pages"][0]["original"]).exists()  # the file survived the garbage collection
