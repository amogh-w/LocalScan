import numpy as np
import pytest

from app.scan.detect import FULL_IMAGE, detect_corners
from app.scan.warp import FILTERS, apply_filter, process_page, rotate, warp


def test_detects_document_corners(photo):
    img, truth = photo
    corners = np.array(detect_corners(img))
    assert np.abs(corners - truth).max() < 0.02


def test_falls_back_to_full_image_on_blank_photo():
    assert detect_corners(np.full((600, 400, 3), 128, np.uint8)) == FULL_IMAGE


def test_warp_produces_upright_page(photo):
    img, truth = photo
    out = warp(img, truth.tolist())
    h, w = out.shape[:2]
    assert h > w and abs(h / w - 1.414) < 0.08


@pytest.mark.parametrize("tilt", [(0.5, -0.3, 0.2), (2, 1, 0), (4, -3, 1), (12, 6, 2), (25, -10, 5)])
def test_true_aspect_is_a4_from_straight_on_to_steep(tilt):
    """Near straight-on shots used to blow up the focal estimate and squeeze A4 (regression)."""
    from conftest import project_page
    from app.scan.warp import true_aspect
    from app.scan.detect import order_points
    quad = order_points(project_page(3000, 4000, *tilt))
    assert abs(true_aspect(quad, 3000, 4000) - 0.7071) < 0.02


def test_rotate_and_filters(photo):
    img, truth = photo
    base = warp(img, truth.tolist(), max_long_edge=800)
    assert rotate(base, 90).shape[:2] == base.shape[1::-1]
    for f in FILTERS:
        out = process_page(img, truth.tolist(), 0, f, max_long_edge=800)
        assert out.shape == base.shape


def test_enhanced_filter_keeps_solid_logos():
    import cv2
    page = np.full((1400, 1000, 3), 235, np.uint8)
    page[:, :500] = (page[:, :500] * 0.7).astype(np.uint8)  # shadow over the left half
    page[100:300, 600:900] = (200, 80, 20)  # solid blue logo (BGR)
    cv2.putText(page, "Text", (100, 700), cv2.FONT_HERSHEY_SIMPLEX, 3, (30, 30, 30), 6)
    out = apply_filter(page, "enhanced")
    logo = out[150:250, 650:850].reshape(-1, 3).mean(axis=0)
    assert logo[0] > logo[2] + 80, f"logo lost its colour: {logo}"
    assert abs(int(out[1200, 200].mean()) - int(out[1200, 800].mean())) < 20, "shadow not removed"
