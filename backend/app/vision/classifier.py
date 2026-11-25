import cv2
import numpy as np

from app.schemas.config import ClassifierConfig


def classify(rgb: np.ndarray, mask: np.ndarray, config: ClassifierConfig) -> dict:
    hsv = cv2.cvtColor(rgb, cv2.COLOR_BGR2HSV)
    count = int(np.count_nonzero(mask))
    if count < config.minimum_pixels:
        return {
            "material": "UNKNOWN",
            "confidence": 0.0,
            "evidence": {"reason": "INSUFFICIENT_VISIBLE_PALLET"},
        }
    hist = cv2.calcHist([hsv], [0], mask, [config.histogram_bins], [0, 180]).flatten()
    hist /= max(hist.sum(), 1)
    scores, coverage = {}, {}
    for label, ranges, template in (
        ("WOOD", config.wood, config.wood_histogram),
        ("PLASTIC", config.plastic, config.plastic_histogram),
    ):
        selected = np.zeros(mask.shape, np.uint8)
        for band in ranges:
            selected |= cv2.inRange(hsv, np.array(band.low), np.array(band.high))
        fraction = np.count_nonzero(selected & mask) / count
        coverage[label] = float(fraction)
        score = fraction
        if template is not None:
            target = np.asarray(template, np.float32)
            target /= target.sum()
            similarity = float(np.minimum(hist, target).sum())
            score = (1 - config.histogram_weight) * fraction + config.histogram_weight * similarity
        scores[label] = float(score)
    winner = max(scores, key=scores.get)
    margin = abs(scores["WOOD"] - scores["PLASTIC"])
    known = coverage[winner] >= config.minimum_coverage and margin >= config.minimum_margin
    return {
        "material": winner if known else "UNKNOWN",
        "confidence": scores[winner] if known else 0.0,
        "evidence": {
            "scores": scores,
            "coverage": coverage,
            "margin": margin,
            "hue_histogram": hist.tolist(),
            "visible_pixels": count,
            "confidence_kind": "heuristic_not_calibrated_probability",
        },
    }
