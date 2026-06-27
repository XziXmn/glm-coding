"""Optional ddddocr-based click captcha adapter.

This adapter mirrors the tencent click-captcha contract used by
``tenvision_adapter.analyze_image_bytes`` so it can be used as a fallback
when the primary RapidOCR pipeline fails or returns low confidence.

It is only loaded when ``ddddocr`` is installed in the environment.
Install it explicitly if you want this fallback:

    pip install ddddocr

The implementation is inspired by the standalone server in
``glm-coding-grabber/captcha/ddddocr_server_win.py`` but trimmed down to the
minimum viable pipeline:

1. ddddocr detection finds candidate character boxes.
2. ddddocr OCR classifies each candidate.
3. Match prompt characters to candidates using OCR + spatial scoring.
"""

from __future__ import annotations

import base64
import io
import math
from itertools import permutations
from typing import Any

import cv2
import numpy as np
from PIL import Image

_ddddocr = None

try:
    import ddddocr

    _ddddocr = ddddocr
except Exception:  # pragma: no cover - optional dependency
    _ddddocr = None


_DET_ENGINE: Any = None
_OCR_ENGINE: Any = None


def is_available() -> bool:
    return _ddddocr is not None


def _get_engines():
    global _DET_ENGINE, _OCR_ENGINE
    if _DET_ENGINE is None:
        _DET_ENGINE = _ddddocr.DdddOcr(det=True, ocr=False, show_ad=False)
    if _OCR_ENGINE is None:
        _OCR_ENGINE = _ddddocr.DdddOcr(det=False, ocr=True, show_ad=False)
    return _DET_ENGINE, _OCR_ENGINE


def _center(box: list) -> tuple[float, float]:
    x1, y1, x2, y2 = box
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _crop(pil_img: Image.Image, box: list, pad: int = 4) -> bytes:
    x1, y1, x2, y2 = box
    x1 = max(0, x1 - pad)
    y1 = max(0, y1 - pad)
    x2 = min(pil_img.width, x2 + pad)
    y2 = min(pil_img.height, y2 + pad)
    buf = io.BytesIO()
    pil_img.crop((x1, y1, x2, y2)).save(buf, format="PNG")
    return buf.getvalue()


def _ocr_ensemble(crop_bytes: bytes, ocr_engine: Any) -> tuple[str, float]:
    """Classify a single crop with a couple of pre-processing variants."""
    img = Image.open(io.BytesIO(crop_bytes))
    gray = np.array(img.convert("L"))

    variants: list[tuple[str, float]] = []
    base = ocr_engine.classification(crop_bytes)
    variants.append((base, 1.0))

    # Otsu binarization
    try:
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        variants.append((ocr_engine.classification(_arr_to_png(binary)), 0.9))
    except Exception:
        pass

    # Inverted
    try:
        variants.append((ocr_engine.classification(_arr_to_png(255 - gray)), 0.8))
    except Exception:
        pass

    # Pick the most common result, weighted by confidence.
    scores: dict[str, float] = {}
    counts: dict[str, int] = {}
    for text, weight in variants:
        counts[text] = counts.get(text, 0) + 1
        scores[text] = scores.get(text, 0.0) + weight

    best = max(counts, key=lambda k: (counts[k], scores[k]))
    confidence = scores[best] / sum(weight for _, weight in variants)
    return best, confidence


def _arr_to_png(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr.astype(np.uint8)).save(buf, format="PNG")
    return buf.getvalue()


def _extract_chinese(text: str) -> list[str]:
    return [ch for ch in (text or "") if "\u4e00" <= ch <= "\u9fff"]


def analyze_image_bytes(
    image_bytes: bytes,
    bg_offset: dict | None = None,
    prompt_text: str | None = None,
    use_deep_learning: bool | None = None,
    include_debug: bool = False,
) -> dict[str, Any]:
    """ddddocr-based click-captcha solver compatible with tenvision output."""
    if not is_available():
        raise RuntimeError("ddddocr is not installed")

    det_engine, ocr_engine = _get_engines()

    pil_img = Image.open(io.BytesIO(image_bytes))
    boxes = det_engine.detection(image_bytes)
    if not boxes:
        raise RuntimeError("ddddocr did not detect any target characters")

    # Detect and classify candidates.
    candidates = []
    for box in boxes:
        crop_bytes = _crop(pil_img, box)
        text, confidence = _ocr_ensemble(crop_bytes, ocr_engine)
        cx, cy = _center(box)
        candidates.append(
            {
                "box": box,
                "char": text,
                "confidence": confidence,
                "center": (cx, cy),
                "chinese_chars": _extract_chinese(text),
            }
        )

    # Resolve prompt characters from provided text or fallback to the first
    # candidate that looks like a prompt (best effort).
    prompt_chars = _extract_chinese(prompt_text or "")
    if not prompt_chars and candidates:
        # Fallback: assume the candidate with the most text is the prompt.
        prompt_candidate = max(candidates, key=lambda c: len(c["chinese_chars"]))
        prompt_chars = prompt_candidate["chinese_chars"]

    if not prompt_chars:
        raise RuntimeError("ddddocr could not resolve prompt characters")

    # Build score matrix and solve assignment with distance constraints.
    n_prompt = len(prompt_chars)
    n_cand = len(candidates)
    min_dist = min(pil_img.width, pil_img.height) * 0.08

    score = [[0.0] * n_cand for _ in range(n_prompt)]
    for pi, prompt_char in enumerate(prompt_chars):
        for ci, cand in enumerate(candidates):
            ocr_score = 0.0
            if prompt_char == cand["char"]:
                ocr_score = cand["confidence"]
            elif prompt_char in cand["chinese_chars"]:
                ocr_score = cand["confidence"] * 0.5
            # Boost slightly for candidates that only have this character.
            if len(cand["chinese_chars"]) == 1 and prompt_char in cand["chinese_chars"]:
                ocr_score += 0.2
            score[pi][ci] = ocr_score

    best_total = -float("inf")
    best_perm = None
    for perm in permutations(range(n_cand), n_prompt):
        ok = True
        for i in range(n_prompt):
            for j in range(i + 1, n_prompt):
                if _dist(candidates[perm[i]]["center"], candidates[perm[j]]["center"]) < min_dist:
                    ok = False
                    break
            if not ok:
                break
        if not ok:
            continue
        total = sum(score[i][perm[i]] for i in range(n_prompt))
        if total > best_total:
            best_total = total
            best_perm = perm

    if best_perm is None:
        # Relax distance constraint.
        for perm in permutations(range(n_cand), n_prompt):
            total = sum(score[i][perm[i]] for i in range(n_prompt))
            if total > best_total:
                best_total = total
                best_perm = perm

    points = []
    matched_scores = []
    fallback_method = "ddddocr_fallback"
    for i, ci in enumerate(best_perm or []):
        cand = candidates[ci]
        cx, cy = cand["center"]
        out_x = cx - float((bg_offset or {}).get("x", 0))
        out_y = cy - float((bg_offset or {}).get("y", 0))
        points.append(
            {
                "order": i + 1,
                "x": int(round(out_x)),
                "y": int(round(out_y)),
                "label": prompt_chars[i],
            }
        )
        matched_scores.append(score[i][ci])

    confidence = round(
        (sum(matched_scores) / len(matched_scores)) if matched_scores else 0.0,
        4,
    )

    debug_png = b""
    if include_debug:
        vis = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if vis is not None:
            for cand in candidates:
                x1, y1, x2, y2 = cand["box"]
                cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 255), 1)
            for pt in points:
                cv2.circle(vis, (pt["x"], pt["y"]), 12, (0, 255, 0), 2)
            success, encoded = cv2.imencode(".png", vis)
            debug_png = encoded.tobytes() if success else b""

    return {
        "width": pil_img.width,
        "height": pil_img.height,
        "points": points,
        "candidate_count": len(candidates),
        "confidence": confidence,
        "debug_png": debug_png,
        "target_chars": prompt_chars,
        "prompt_text": prompt_text or "".join(prompt_chars),
        "prompt_bbox": None,
        "candidate_boxes": [c["box"] for c in candidates],
        "click_boxes": [candidates[ci]["box"] for ci in (best_perm or [])],
        "click_chars": prompt_chars,
        "fallback_method": fallback_method,
        "recognized_text": prompt_text or "".join(prompt_chars),
        "algorithm": "ddddocr",
        "use_deep_learning": bool(use_deep_learning) if use_deep_learning is not None else True,
    }
