import numpy as np

from app.schemas.config import AppConfig
from app.sources.base import FrameBundle
from app.vision.calibration import floor_plane
from app.vision.geometry import deproject, local_pixels
from app.vision.roll_detector import RollDetection


def describe_roll(
    detection: RollDetection, index: int, frame: FrameBundle, pallet: dict | None, config: AppConfig
):
    geom = detection.geometry
    roll = {
        "id": f"roll-{index + 1}",
        "centroid": geom["centroid"],
        "rotated_box": geom["polygon"],
        "orientation": geom["orientation"],
        "orientation_method": geom["orientation_method"],
        "confidence": geom["confidence"],
        "circularity": geom["circularity"],
        "aspect_ratio": geom["aspect_ratio"],
        "x_local": None,
        "y_local": None,
        "z_height": None,
        "width": None,
        "height": None,
        "unit": "px",
        "depth_valid_fraction": None,
        "median_depth_mm": None,
        "local_box": None,
        "warnings": [],
    }
    if pallet:
        scale = config.matching.canonical_pallet_width_px / pallet["width_px"]
        local = local_pixels([geom["centroid"]], pallet)[0] * scale
        roll.update(
            x_local=float(local[0]),
            y_local=float(local[1]),
            width=geom["width_px"] * scale,
            height=geom["height_px"] * scale,
            local_box=(local_pixels(geom["polygon"], pallet) * scale).tolist(),
        )
    if frame.depth is None or frame.metadata is None:
        return roll
    depths = frame.depth.astype(float) * frame.metadata.depth_scale_m * 1000
    valid = (
        (detection.mask > 0)
        & (depths > config.detector.minimum_depth_mm)
        & (depths < config.detector.maximum_depth_mm)
    )
    fraction = np.count_nonzero(valid) / max(np.count_nonzero(detection.mask), 1)
    roll["depth_valid_fraction"] = fraction
    if fraction < config.detector.depth_valid_fraction:
        roll["warnings"].append("INSUFFICIENT_ROLL_DEPTH")
        if pallet and pallet["metric_transform"]:
            roll.update(unit="mm", x_local=None, y_local=None, width=None, height=None, local_box=None)
        return roll
    median = float(np.median(depths[valid]))
    roll["median_depth_mm"] = median
    point = deproject([geom["centroid"]], np.array([median]), frame.metadata.intrinsics)[0]
    plane = floor_plane(config, frame)
    if plane is not None:
        roll["z_height"] = float(point @ plane[:3] + plane[3])
    if pallet and pallet["metric_transform"]:
        transform = pallet["metric_transform"]
        basis, origin = np.asarray(transform["basis"]), np.asarray(transform["origin"])
        local = (point - origin) @ basis.T
        corners = deproject(geom["polygon"], np.full(4, median), frame.metadata.intrinsics)
        local_box = (corners - origin) @ basis.T
        edges = np.linalg.norm(np.roll(local_box, -1, axis=0) - local_box, axis=1)
        roll.update(
            unit="mm",
            x_local=float(local[0]),
            y_local=float(local[1]),
            width=float(max(edges)),
            height=float(min(edges)),
            local_box=local_box.tolist(),
        )
    else:
        roll["warnings"].append("FLOOR_CALIBRATION_REQUIRED_FOR_METRIC_LAYOUT")
    return roll
