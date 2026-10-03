"""Perspective correction, rotation and Adobe-Scan-like filters."""
import cv2
import numpy as np

from .detect import Corners, order_points

FILTERS = ("enhanced", "original", "grayscale", "bw")
MAX_LONG_EDGE = 3508  # A4 at 300 dpi
EDGE_TRIM = 0.004


A4_RATIO = 2 ** 0.5


# Focal length in units of the photo's long side. Phone main cameras (24-28 mm equivalent) are ~1.0;
# anything outside the plausible range comes from an ill-conditioned estimate, not a real lens.
TYPICAL_FOCAL = 1.0
PLAUSIBLE_FOCAL = (0.5, 2.5)


def true_aspect(src: np.ndarray, img_w: int, img_h: int) -> float | None:
    """Estimate the real width/height ratio of a photographed rectangle.

    Zhang & He, "Whiteboard scanning and image enhancement" (2007), assuming square pixels and the
    principal point at the image centre. The method can also estimate the focal length from the
    quad, but that estimate is unstable when the photo is taken nearly straight on: a real letter
    gave 8.8x the long side and squeezed A4 to 0.54. So the estimate is used only when it is
    physically plausible; otherwise a typical phone focal length is assumed. The ratio barely
    depends on the exact focal length within the plausible range (0.709-0.714 for that letter).
    """
    u0, v0 = img_w / 2, img_h / 2
    tl, tr, br, bl = src
    m1, m2, m3, m4 = (np.array([p[0] - u0, p[1] - v0, 1.0]) for p in (tl, tr, bl, br))
    k2 = np.dot(np.cross(m1, m4), m3) / np.dot(np.cross(m2, m4), m3)
    k3 = np.dot(np.cross(m1, m4), m2) / np.dot(np.cross(m3, m4), m2)
    n2, n3 = k2 * m2 - m1, k3 * m3 - m1
    long_side = max(img_w, img_h)
    f2 = (TYPICAL_FOCAL * long_side) ** 2
    if abs(n2[2] * n3[2]) > 1e-12:
        est = -(n2[0] * n3[0] + n2[1] * n3[1]) / (n2[2] * n3[2])
        if (PLAUSIBLE_FOCAL[0] * long_side) ** 2 <= est <= (PLAUSIBLE_FOCAL[1] * long_side) ** 2:
            f2 = est
    w2 = (n2[0] ** 2 + n2[1] ** 2) / f2 + n2[2] ** 2
    h2 = (n3[0] ** 2 + n3[1] ** 2) / f2 + n3[2] ** 2
    ratio = float(np.sqrt(w2 / h2))
    return ratio if 0.2 < ratio < 5 else None


def warp(img: np.ndarray, corners: Corners, max_long_edge: int = MAX_LONG_EDGE) -> np.ndarray:
    h, w = img.shape[:2]
    src = order_points(np.array([[x * w, y * h] for x, y in corners], dtype=np.float32))
    tl, tr, br, bl = src
    out_w = max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))
    out_h = max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))
    ratio = true_aspect(src, w, h)
    if ratio is not None:
        # Snap to A4 when close: almost every letter is A4, and it hides small estimation errors.
        for a4 in (1 / A4_RATIO, A4_RATIO):
            if abs(ratio / a4 - 1) < 0.07:
                ratio = a4
        # Keep the measured size, correct the proportions.
        out_h = np.sqrt(out_w * out_h / ratio)
        out_w = out_h * ratio
    scale = min(1.0, max_long_edge / max(out_w, out_h))
    out_w, out_h = max(1, round(out_w * scale)), max(1, round(out_h * scale))
    dst = np.array([[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]], dtype=np.float32)
    m = cv2.getPerspectiveTransform(src, dst)
    out = cv2.warpPerspective(img, m, (out_w, out_h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    # Trim a sliver: the detected edge usually carries a line of table or shadow.
    t = round(EDGE_TRIM * min(out_w, out_h))
    return out[t:out_h - t, t:out_w - t] if t and min(out_w, out_h) > 20 * t else out


def rotate(img: np.ndarray, degrees: int) -> np.ndarray:
    k = (degrees // 90) % 4
    codes = {1: cv2.ROTATE_90_CLOCKWISE, 2: cv2.ROTATE_180, 3: cv2.ROTATE_90_COUNTERCLOCKWISE}
    return cv2.rotate(img, codes[k]) if k else img


def _remove_shadows(img: np.ndarray) -> np.ndarray:
    """Divide each channel by its estimated background so the paper becomes evenly white.

    The background is the local maximum over a window wider than typical logos and stamps, so
    solid coloured areas keep their colour; lighting changes slowly enough to survive that scale.
    """
    h, w = img.shape[:2]
    small = cv2.resize(img, (max(1, w // 4), max(1, h // 4)), interpolation=cv2.INTER_AREA)
    k = max(9, (min(small.shape[:2]) // 4) | 1)
    bg = cv2.dilate(small, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    bg = cv2.GaussianBlur(bg, (0, 0), k / 2)
    bg = cv2.resize(bg, (w, h), interpolation=cv2.INTER_LINEAR)
    flat = cv2.divide(img, np.maximum(bg, 1), scale=255)
    return cv2.LUT(flat, _levels(paper_white_point(flat)))  # paper texture and noise -> clean white


def paper_white_point(img: np.ndarray) -> int:
    """Brightness at which this photo's paper should become pure white.

    Measured per page: the darker end of the paper pixels (above the ink/paper Otsu split), so speckle
    from low light or a phone camera's noise reduction disappears instead of showing as grey texture.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    small = gray[::4, ::4]
    split, _ = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    paper = small[small > split]
    if paper.size < 100:
        return 228
    return int(np.clip(np.percentile(paper, 3), 150, 245))


def _levels(white: int) -> np.ndarray:
    """Levels curve: 0..white maps to 0..255, anything brighter is pure white.

    Values that end up nearly white snap to white too, so stray paper speckles vanish.
    """
    lut = np.clip(np.arange(256) * 255.0 / white, 0, 255)
    lut[lut >= 226] = 255
    return lut.astype(np.uint8)


def apply_filter(img: np.ndarray, name: str) -> np.ndarray:
    if name == "original":
        return img
    if name == "grayscale":
        gray = cv2.cvtColor(_remove_shadows(img), cv2.COLOR_BGR2GRAY)
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    if name == "bw":
        gray = cv2.cvtColor(_remove_shadows(img), cv2.COLOR_BGR2GRAY)
        bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15)
        return cv2.cvtColor(bw, cv2.COLOR_GRAY2BGR)
    # enhanced: flat white paper, crisper text, colours kept for logos and stamps.
    flat = _remove_shadows(img)
    lab = cv2.cvtColor(flat, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8)).apply(l)
    out = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)
    return cv2.convertScaleAbs(out, alpha=1.08, beta=-12)


def process_page(img: np.ndarray, corners: Corners, rotation: int, filter_name: str,
                 max_long_edge: int = MAX_LONG_EDGE) -> np.ndarray:
    return apply_filter(rotate(warp(img, corners, max_long_edge), rotation), filter_name)
