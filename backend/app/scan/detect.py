"""Find the four corners of a document in a photo."""
import cv2
import numpy as np

Corners = list[list[float]]  # [[x, y] * 4] normalised 0..1, order TL, TR, BR, BL

FULL_IMAGE: Corners = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]


def order_points(pts: np.ndarray) -> np.ndarray:
    """Order 4 points as TL, TR, BR, BL."""
    pts = pts.reshape(4, 2).astype(np.float32)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array(
        [pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]],
        dtype=np.float32,
    )


def _candidate_quads(gray: np.ndarray):
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
    # Edge-based: works for paper on a contrasting background.
    edges = cv2.Canny(blurred, 50, 150)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)
    yield edges
    # Threshold-based: works when the paper is much brighter than the table.
    _, th = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    yield cv2.morphologyEx(th, cv2.MORPH_CLOSE, kernel)


def detect_corners(img: np.ndarray) -> Corners:
    """Return normalised corners of the largest plausible document quad, or the full image."""
    h, w = img.shape[:2]
    scale = 800 / max(h, w)
    small = cv2.resize(img, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if small.ndim == 3 else small
    sh, sw = gray.shape[:2]
    area_total = sh * sw

    best, best_area = None, 0.0
    for mask in _candidate_quads(gray):
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
            area = cv2.contourArea(c)
            if area < 0.2 * area_total or area > 0.995 * area_total:
                continue
            peri = cv2.arcLength(c, True)
            for eps in (0.02, 0.03, 0.05):
                approx = cv2.approxPolyDP(c, eps * peri, True)
                if len(approx) == 4 and cv2.isContourConvex(approx):
                    break
            else:
                # Fall back to the minimum-area rectangle of the contour.
                approx = cv2.boxPoints(cv2.minAreaRect(c))
                if cv2.contourArea(approx) > 1.25 * area:
                    continue
            if area > best_area:
                best, best_area = approx, area
    if best is None:
        return [p[:] for p in FULL_IMAGE]
    pts = order_points(np.asarray(best))
    pts[:, 0] = np.clip(pts[:, 0] / sw, 0, 1)
    pts[:, 1] = np.clip(pts[:, 1] / sh, 0, 1)
    return [[round(float(x), 5), round(float(y), 5)] for x, y in pts]
