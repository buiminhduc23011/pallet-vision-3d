"""Assignment and independent acceptance checks in a common pallet-local frame."""

import math

import numpy as np
from scipy.optimize import linear_sum_assignment

from app.schemas.config import MatchingConfig


def compare_rolls(reference: list[dict], current: list[dict], config: MatchingConfig, unit: str) -> dict:
    n, m = len(reference), len(current)
    result = {
        "reference_count": n,
        "current_count": m,
        "matched_count": 0,
        "mismatch_count": 0,
        "missing_count": 0,
        "extra_count": 0,
        "pairs": [],
        "missing": [],
        "extra": [],
        "reasons": [],
        "verdict": "INCOMPLETE",
    }
    if n < config.minimum_reference_count:
        result["reasons"].append("EMPTY_REFERENCE")
        return result
    required = ("x_local", "y_local", "width", "height")
    for roll in reference + current:
        if (
            any(roll.get(k) is None or not math.isfinite(roll[k]) for k in required)
            or min(roll["width"], roll["height"]) <= 0
        ):
            result["reasons"].append("INVALID_ROLL_GEOMETRY")
            return result
        if roll.get("unit", unit) != unit:
            result["reasons"].append("INCOMPATIBLE_UNITS")
            return result
        if config.check_orientation and roll.get("orientation") not in ("STANDING", "LYING"):
            result["reasons"].append("UNKNOWN_ORIENTATION")
            return result
    tolerance = config.position_tolerance_mm if unit == "mm" else config.position_tolerance_px
    # Each real reference has its own missing column; each detection its own extra row.
    cost = np.full((n + m, n + m), np.inf)
    cost[n:, m:] = 0
    for i in range(n):
        cost[i, m + i] = config.unmatched_cost
    for j in range(m):
        cost[n + j, j] = config.unmatched_cost
    errors = {}
    for i, old in enumerate(reference):
        for j, new in enumerate(current):
            dx, dy = new["x_local"] - old["x_local"], new["y_local"] - old["y_local"]
            position = math.hypot(dx, dy)
            size = max(abs(new[k] - old[k]) / old[k] * 100 for k in ("width", "height"))
            orientation = config.check_orientation and old["orientation"] != new["orientation"]
            errors[i, j] = {
                "dx": dx,
                "dy": dy,
                "distance": position,
                "size_percent": size,
                "orientation_mismatch": orientation,
                "unit": unit,
            }
            if position <= tolerance * config.candidate_gate_multiplier:
                cost[i, j] = (
                    config.position_weight * position / tolerance
                    + config.size_weight * size / config.size_tolerance_percent
                    + config.orientation_weight * int(orientation)
                )
    rows, cols = linear_sum_assignment(cost)
    assigned_old, assigned_new = set(), set()
    for i, j in zip(rows.tolist(), cols.tolist()):
        if i >= n or j >= m:
            continue
        assigned_old.add(i)
        assigned_new.add(j)
        error = errors[i, j]
        reasons = []
        if error["distance"] > tolerance:
            reasons.append("MISPLACED")
        if error["size_percent"] > config.size_tolerance_percent:
            reasons.append("WRONG_SIZE")
        if error["orientation_mismatch"]:
            reasons.append("WRONG_ORIENTATION")
        result["pairs"].append(
            {
                "reference_roll_id": reference[i]["id"],
                "current_roll_id": current[j]["id"],
                "errors": error,
                "reasons": reasons,
                "status": "MISMATCH" if reasons else "MATCHED",
            }
        )
    result["missing"] = [r for i, r in enumerate(reference) if i not in assigned_old]
    result["extra"] = [r for j, r in enumerate(current) if j not in assigned_new]
    result["matched_count"] = sum(not p["reasons"] for p in result["pairs"])
    result["mismatch_count"] = sum(bool(p["reasons"]) for p in result["pairs"])
    result["missing_count"], result["extra_count"] = len(result["missing"]), len(result["extra"])
    result["verdict"] = "PASS" if n == m == result["matched_count"] else "FAIL"
    if n != m:
        result["reasons"].append("COUNT_MISMATCH")
    return result
