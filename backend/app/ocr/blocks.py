"""Group OCR lines into blocks (paragraphs, address blocks, list items) in reading order."""
import re
from statistics import median

from .base import Block, Line

# Two boxes on one row are the same line only when separated by about a word space.
# PaddleOCR already returns whole lines, so anything wider is a column gap or a table cell.
SAME_LINE_GAP = 0.45
# Lines of one paragraph sit almost touching; paragraphs are separated by roughly a blank line.
PARAGRAPH_GAP = 0.4
# A line belongs to the block above only if its left edge lines up (indented bullets start new blocks).
ALIGN_TOLERANCE = 0.8
# A block "flows" (is reflowable prose) when its lines, except the last, fill the block width.
FLOW_FILL = 0.8


# A line with no real word in it (a number, a code, a rule of underscores) has nothing to translate and stays as
# it is in the photo. A "word" is 3 or more letters, not part of a code like "04GKRU197_P". Text that runs
# vertically (a margin note) is translated too, but as a block of its own that is drawn rotated.
WORD = re.compile(r"(?<!\w)[^\W\d_]{3,}(?!\w)")
VERTICAL_RATIO = 1.5


def is_vertical(line: Line) -> bool:
    x0, y0, x1, y1 = line["bbox"]
    return (y1 - y0) >= VERTICAL_RATIO * (x1 - x0) and len(line["text"].strip()) >= 3


def is_kept(line: Line) -> bool:
    """True when the line is left untouched by the translated PDF."""
    return not WORD.search(line["text"])


def thickness(line: Line) -> float:
    """How tall the letters are: the box height, or its width for vertical text."""
    x0, y0, x1, y1 = line["bbox"]
    return (x1 - x0) if is_vertical(line) else (y1 - y0)


def _height(line: Line) -> float:
    return line["bbox"][3] - line["bbox"][1]


def _cy(line: Line) -> float:
    return (line["bbox"][1] + line["bbox"][3]) / 2


def merge_same_row(lines: list[Line]) -> list[Line]:
    """Join fragments of one line that OCR split at a slightly wide space."""
    rows: list[list[Line]] = []
    for line in sorted(lines, key=_cy):
        for row in rows:
            if abs(_cy(line) - _cy(row[0])) < 0.35 * min(_height(row[0]), _height(line)):
                row.append(line)
                break
        else:
            rows.append([line])
    merged: list[Line] = []
    for row in rows:
        row.sort(key=lambda l: l["bbox"][0])
        cur = dict(row[0])
        for nxt in row[1:]:
            h = min(_height(cur), _height(nxt))
            if 0 <= nxt["bbox"][0] - cur["bbox"][2] < SAME_LINE_GAP * h:
                cur = {
                    "text": cur["text"] + " " + nxt["text"],
                    "conf": min(cur["conf"], nxt["conf"]),
                    "bbox": [cur["bbox"][0], min(cur["bbox"][1], nxt["bbox"][1]),
                             nxt["bbox"][2], max(cur["bbox"][3], nxt["bbox"][3])],
                }
            else:
                merged.append(cur)
                cur = dict(nxt)
        merged.append(cur)
    return merged


# "Kranken- und Pflegeversicherung": the hyphen is a German elision, not a line-break split.
KEEP_HYPHEN_BEFORE = {"und", "oder", "bzw.", "sowie", "bis", "als"}


def join_text(lines: list[Line]) -> str:
    text = ""
    for line in lines:
        t = line["text"].strip()
        if not text:
            text = t
        elif re.search(r"[a-zäöüß]-$", text) and t[:1].islower() and t.split()[0] not in KEEP_HYPHEN_BEFORE:
            text = text[:-1] + t  # de-hyphenate "Verein-" + "barung"
        else:
            text += " " + t
    return text


def _is_prose_line(text: str) -> bool:
    """At least 3 real words, or a hyphenated word split: not a date, time, label or code."""
    words = [w for w in text.split() if sum(c.isalpha() for c in w) >= 2]
    return len(words) >= 3 or text.rstrip().endswith("-")


def _flows(lines: list[Line]) -> bool:
    if len(lines) < 2:
        return True
    x0 = min(l["bbox"][0] for l in lines)
    x1 = max(l["bbox"][2] for l in lines)
    width = max(1.0, x1 - x0)
    return all((l["bbox"][2] - l["bbox"][0]) >= FLOW_FILL * width and _is_prose_line(l["text"])
               for l in lines[:-1])


def group_blocks(lines: list[Line], page_index: int = 0) -> list[Block]:
    lines = [l for l in merge_same_row(lines) if l["text"].strip()]
    kept = [l for l in lines if is_kept(l)]
    rest = [l for l in lines if not is_kept(l)]
    vertical = [l for l in rest if is_vertical(l)]  # each its own block, never merged with horizontal text
    lines = [l for l in rest if not is_vertical(l)]
    lines.sort(key=lambda l: (l["bbox"][1], l["bbox"][0]))
    groups: list[list[Line]] = []
    for line in lines:
        x0, y0, x1, _ = line["bbox"]
        h = _height(line)
        target = None
        for g in groups:
            last = g[-1]
            lh = _height(last)
            gap = y0 - last["bbox"][3]
            gx0 = min(l["bbox"][0] for l in g)
            gx1 = max(l["bbox"][2] for l in g)
            similar_height = max(h, lh) / max(1.0, min(h, lh)) < 1.45
            close_below = -0.5 * lh < gap < PARAGRAPH_GAP * max(h, lh)
            aligned = abs(x0 - gx0) < ALIGN_TOLERANCE * lh and x0 < gx1
            if similar_height and close_below and aligned:
                target = g
                break
        if target is None:
            groups.append([line])
        else:
            target.append(line)

    # Reading order: text blocks and kept lines (numbers, codes, vertical margin text) sorted together.
    ordered: list[tuple[tuple[float, float], Block]] = []
    for g in groups:
        flow = _flows(g)
        ordered.append(((g[0]["bbox"][1], g[0]["bbox"][0]), {
            "id": "",
            "bbox": [min(l["bbox"][0] for l in g), min(l["bbox"][1] for l in g),
                     max(l["bbox"][2] for l in g), max(l["bbox"][3] for l in g)],
            "lines": g,
            "flow": flow,
            # Prose is reflowed; addresses, tables and lists keep their line structure.
            "text": join_text(g) if flow else "\n".join(l["text"].strip() for l in g),
        }))
    for l in kept:
        ordered.append(((l["bbox"][1], l["bbox"][0]), {
            "id": "", "bbox": list(l["bbox"]), "lines": [l], "flow": False, "text": l["text"].strip(), "keep": True,
        }))
    for l in vertical:
        ordered.append(((l["bbox"][1], l["bbox"][0]), {
            "id": "", "bbox": list(l["bbox"]), "lines": [l], "flow": False, "text": l["text"].strip(), "vertical": True,
        }))
    blocks = [b for _, b in sorted(ordered, key=lambda t: t[0])]
    for i, b in enumerate(blocks):
        b["id"] = f"p{page_index}b{i}"
    return blocks


def median_line_height(block: Block) -> float:
    return median(_height(l) for l in block["lines"])
