"""Page previews render what their URL asks for, so a thumbnail never lags behind an edit that is still saving."""
import json

import cv2
import numpy as np
import pytest

from app import storage
from app.api import documents
from app.db import blobs
from app.db import connection as db

FULL = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]


@pytest.fixture
def page(tmp_path):
    storage.init(tmp_path)
    photo = np.full((300, 200, 3), 255, np.uint8)  # portrait: 200 wide, 300 tall
    ok, jpg = cv2.imencode(".jpg", photo)
    doc = storage.create_doc("Scan")
    with storage.editing(doc["id"]) as d:
        d["pages"] = [{"id": "p0", "original": blobs.put(jpg.tobytes(), "jpg"), "clean": None, "width": 200,
                       "height": 300, "corners": FULL, "rotation": 0, "filter": "original", "lines": []}]
    yield doc["id"]
    db.close()


def shape(response):
    return cv2.imdecode(np.frombuffer(response.body if hasattr(response, "body") else open(response.path, "rb").read(),
                                      np.uint8), cv2.IMREAD_COLOR).shape[:2]


def test_preview_follows_the_url_not_the_stored_page(page):
    stored = documents.page_preview(page, "p0", size=300, v=json.dumps([FULL, 0, "original"]))
    # The client rotated the page but its save has not landed yet: the URL already says 90.
    turned = documents.page_preview(page, "p0", size=300, v=json.dumps([FULL, 90, "original"]))
    h, w = shape(stored)
    assert h > w and shape(turned) == (w, h)


def test_only_a_preview_that_names_its_state_is_cached_for_good(page):
    named = documents.page_preview(page, "p0", size=300, v=json.dumps([FULL, 90, "original"]))
    stored = documents.page_preview(page, "p0", size=300, v="")
    assert "immutable" in named.headers["cache-control"] and stored.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("v",["", "nonsense", json.dumps([FULL, 45, "original"]), json.dumps([FULL, 0, "sepia"]),
                               json.dumps([[[0, 0]], 0, "original"])])
def test_a_missing_or_bad_v_falls_back_to_the_stored_page(page, v):
    assert documents._preview_state(v) is None
    h, w = shape(documents.page_preview(page, "p0", size=300, v=v))
    assert h > w
