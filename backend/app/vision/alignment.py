import cv2
import numpy as np

from app.schemas.config import AppConfig
from app.sources.base import FrameBundle
from app.vision.calibration import floor_plane
from app.vision.geometry import canonical_rect, deproject, roi_mask
from app.vision.teaching import acceptance_polygon, orient_pallet, target_geometry, validate_teaching_frame


def detect_pallet(frame: FrameBundle, config: AppConfig, origin=None) -> tuple[dict | None, dict]:
    rgb, cfg = frame.rgb, config.alignment
    teaching = config.teaching
    validate_teaching_frame(teaching, frame)
    taught = target_geometry(teaching) if teaching else None
    zone = roi_mask(rgb.shape, config.roi)
    plane = floor_plane(config, frame)
    method = "rgb_contour"
    candidates = None
    if frame.depth is not None and frame.metadata and plane is not None:
        z = frame.depth.astype(float) * frame.metadata.depth_scale_m * 1000
        y, x = np.nonzero(
            (zone > 0) & (z > config.detector.minimum_depth_mm) & (z < config.detector.maximum_depth_mm)
        )
        points = deproject(np.column_stack((x, y)), z[y, x], frame.metadata.intrinsics)
        heights = points @ plane[:3] + plane[3]
        band = np.abs(heights - config.calibration.pallet_height_mm) <= cfg.height_band_mm
        candidates = np.zeros(zone.shape, np.uint8)
        candidates[y[band], x[band]] = 255
        method = "depth_height_contour"
    if candidates is None or not np.any(candidates):
        gray = cv2.cvtColor(rgb, cv2.COLOR_BGR2GRAY)
        candidates = cv2.Canny(gray, cfg.canny_low, cfg.canny_high) & zone
        method = "rgb_contour"
    kernel = np.ones((cfg.morphology_kernel, cfg.morphology_kernel), np.uint8)
    candidates = cv2.morphologyEx(candidates, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(candidates, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    minimum = np.count_nonzero(zone) * cfg.contour_min_area_fraction
    contours = [c for c in contours if cv2.contourArea(c) >= minimum]
    if not contours:
        return None, {
            "status": "INCOMPLETE",
            "dx": None,
            "dy": None,
            "unit": "px",
            "angle_deg": None,
            "reasons": ["PALLET_NOT_FOUND"],
            "method": method,
        }
    if taught:

        def score(c):
            box = orient_pallet(canonical_rect(c), taught)
            return sum(abs(np.log(max(box[k], 1) / taught[k])) for k in ("width_px", "height_px"))

        contour = min(contours, key=score)
    else:
        contour = max(contours, key=cv2.contourArea)
    pallet = canonical_rect(contour)
    if taught:
        pixel_origin = (
            np.asarray(origin) * [rgb.shape[1] - 1, rgb.shape[0] - 1] if origin is not None else None
        )
        pallet = orient_pallet(pallet, taught, pixel_origin)
        pallet["local_origin"] = pallet["polygon"][0]
    rectangularity = cv2.contourArea(contour) / max(pallet["width_px"] * pallet["height_px"], 1)
    if rectangularity < cfg.min_rectangularity:
        return None, {
            "status": "INCOMPLETE",
            "dx": None,
            "dy": None,
            "unit": "px",
            "angle_deg": None,
            "reasons": ["AMBIGUOUS_PALLET_CONTOUR"],
            "method": method,
        }
    target_contour = cv2.findContours(zone, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0][0]
    moments = cv2.moments(target_contour)
    target = np.array([moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]])
    target_angle = taught["angle_deg"] if taught else cfg.target_angle_deg
    if taught:
        target = np.asarray(taught["center"])
    target_theta = np.deg2rad(target_angle)
    target_basis = np.array(
        [[np.cos(target_theta), np.sin(target_theta)], [-np.sin(target_theta), np.cos(target_theta)]]
    )
    delta = (np.asarray(pallet["center"]) - target) @ target_basis.T
    unit = "px"
    pallet["metric_transform"] = None
    if frame.depth is not None and frame.metadata and plane is not None:
        intr = frame.metadata.intrinsics
        # Intersect rays with calibrated pallet support plane, not roll surfaces.
        sample = np.array(
            [
                pallet["center"],
                target,
                np.asarray(pallet["center"]) + np.asarray(pallet["basis"])[0],
                target + target_basis[0],
                pallet.get("local_origin", pallet["center"]),
            ]
        )
        rays = deproject(sample, np.ones(5), intr)
        denominator = rays @ plane[:3]
        if np.all(np.abs(denominator) > 1e-6):
            points = rays * ((config.calibration.pallet_height_mm - plane[3]) / denominator)[:, None]
            if np.all(points[:, 2] > 0):
                x_axis = points[2] - points[0]
                x_axis /= np.linalg.norm(x_axis)
                y_axis = np.cross(x_axis, plane[:3])
                y_axis /= np.linalg.norm(y_axis)
                # y follows down-image for a perpendicular camera.
                basis = np.array([x_axis, y_axis])
                target_x = points[3] - points[1]
                target_x /= np.linalg.norm(target_x)
                target_y = np.cross(target_x, plane[:3])
                target_y /= np.linalg.norm(target_y)
                delta = (points[0] - points[1]) @ np.array([target_x, target_y]).T
                pallet["metric_transform"] = {"origin": points[4].tolist(), "basis": basis.tolist()}
                unit = "mm"
    period = 360 if taught and origin is not None else 180
    angle = (pallet["angle_deg"] - target_angle + period / 2) % period - period / 2
    tolerance = cfg.position_tolerance_mm if unit == "mm" else cfg.position_tolerance_px
    reasons = []
    origin_missing = bool(teaching and teaching.require_origin_confirmation and origin is None)
    if origin_missing:
        reasons.append("ORIGIN_CONFIRMATION_REQUIRED")
    if taught:
        for key in ("width_px", "height_px"):
            if abs(pallet[key] / taught[key] - 1) * 100 > teaching.size_tolerance_percent:
                reasons.append(f"PALLET_SIZE_MISMATCH_{key.upper()}")
    for axis, value in zip(("X", "Y"), delta):
        if abs(value) > tolerance:
            reasons.append(f"Misaligned {axis}: {value:+.1f}{unit}")
    if abs(angle) > cfg.rotation_tolerance_deg:
        reasons.append(f"Rotated: {angle:+.1f} deg")
    for point in pallet["polygon"]:
        if cv2.pointPolygonTest(target_contour, tuple(point), True) < -cfg.boundary_margin_px:
            reasons.append("PALLET_OUTSIDE_TARGET_ROI")
            break
    # A contour cut at the search boundary cannot prove the entire pallet was observed.
    clipped = any(
        cv2.pointPolygonTest(target_contour, tuple(map(float, p[0])), True) <= cfg.boundary_margin_px
        for p in contour
    )
    ambiguous = (
        max(pallet["width_px"], pallet["height_px"]) / max(min(pallet["width_px"], pallet["height_px"]), 1)
        < cfg.square_ambiguity_ratio
    )
    if taught and origin is not None:
        ambiguous = False
    pallet["geometry_quality"] = {
        "rectangularity": rectangularity,
        "method": method,
        "clipped": clipped,
        "axis_ambiguous": ambiguous,
    }
    if clipped:
        reasons.append("PALLET_CLIPPED_BY_ROI")
    if ambiguous:
        reasons.append("PALLET_AXIS_AMBIGUOUS")
    return pallet, {
        "status": "INCOMPLETE" if clipped or ambiguous or origin_missing else ("NG" if reasons else "OK"),
        "target": taught,
        "acceptance_polygon": acceptance_polygon(
            config, plane, frame.metadata.intrinsics if frame.metadata else None
        ),
        "origin_confirmed": bool(taught and origin is not None),
        "dx": float(delta[0]),
        "dy": float(delta[1]),
        "unit": unit,
        "angle_deg": angle,
        "reasons": reasons,
        "method": method,
    }
