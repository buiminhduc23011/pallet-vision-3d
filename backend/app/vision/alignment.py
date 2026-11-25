import cv2
import numpy as np

from app.schemas.config import AppConfig
from app.sources.base import FrameBundle
from app.vision.calibration import floor_plane
from app.vision.geometry import canonical_rect, deproject, roi_mask


def detect_pallet(frame: FrameBundle, config: AppConfig) -> tuple[dict | None, dict]:
    rgb, cfg = frame.rgb, config.alignment
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
    contour = max(contours, key=cv2.contourArea)
    pallet = canonical_rect(contour)
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
    target_theta = np.deg2rad(cfg.target_angle_deg)
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
            ]
        )
        rays = deproject(sample, np.ones(4), intr)
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
                pallet["metric_transform"] = {"origin": points[0].tolist(), "basis": basis.tolist()}
                unit = "mm"
    angle = (pallet["angle_deg"] - cfg.target_angle_deg + 90) % 180 - 90
    tolerance = cfg.position_tolerance_mm if unit == "mm" else cfg.position_tolerance_px
    reasons = []
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
    ambiguous = pallet["width_px"] / max(pallet["height_px"], 1) < cfg.square_ambiguity_ratio
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
        "status": "INCOMPLETE" if clipped or ambiguous else ("NG" if reasons else "OK"),
        "dx": float(delta[0]),
        "dy": float(delta[1]),
        "unit": unit,
        "angle_deg": angle,
        "reasons": reasons,
        "method": method,
    }
