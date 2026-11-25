import numpy as np

from app.errors import DomainError
from app.schemas.config import AppConfig, ROI
from app.sources.base import FrameBundle
from app.vision.geometry import deproject, roi_mask


def floor_plane(config: AppConfig, frame: FrameBundle):
    cal = config.calibration
    if not frame.metadata:
        return None
    if cal.camera_serial and cal.camera_serial != frame.metadata.camera_serial:
        raise DomainError("CALIBRATION_CAMERA_MISMATCH", "Calibration belongs to another camera")
    if cal.intrinsics and cal.intrinsics != frame.metadata.intrinsics:
        raise DomainError(
            "CALIBRATION_INTRINSICS_MISMATCH", "Calibration does not match this image's camera profile"
        )
    if cal.floor_plane:
        if cal.intrinsics is None:
            raise DomainError(
                "CALIBRATION_PROFILE_REQUIRED", "A fitted plane requires matching camera intrinsics"
            )
        return np.asarray(cal.floor_plane)
    if cal.perpendicular_camera and cal.floor_distance_mm:
        return np.array([0.0, 0.0, -1.0, cal.floor_distance_mm])
    return None


def fit_floor(frame: FrameBundle, roi: ROI, config: AppConfig):
    if frame.depth is None or frame.metadata is None:
        raise DomainError("DEPTH_REQUIRED", "Floor calibration requires aligned RGB-D")
    mask = roi_mask(frame.rgb.shape, roi) > 0
    depth_mm = frame.depth.astype(float) * frame.metadata.depth_scale_m * 1000
    valid = (
        mask & (depth_mm > config.detector.minimum_depth_mm) & (depth_mm < config.detector.maximum_depth_mm)
    )
    y, x = np.nonzero(valid)
    cal = config.calibration
    if len(x) < cal.plane_min_points:
        raise DomainError("INSUFFICIENT_FLOOR_DEPTH", "Select a visible bare floor patch with valid depth")
    stride = max(1, int(np.ceil(len(x) / cal.plane_max_points)))
    x, y = x[::stride], y[::stride]
    points = deproject(np.column_stack((x, y)), depth_mm[y, x], frame.metadata.intrinsics)
    # Deterministic robust trimming, not random/synthetic sample generation.
    inliers = points
    for _ in range(5):
        center = np.median(inliers, axis=0)
        _, singular, vt = np.linalg.svd(inliers - center, full_matrices=False)
        if singular[1] <= 1e-8:
            raise DomainError("DEGENERATE_FLOOR", "Floor samples must span a plane, not a line")
        normal = vt[-1]
        if np.dot(normal, center) > 0:
            normal = -normal
        offset = -float(np.dot(normal, center))
        residual = np.abs(points @ normal + offset)
        inliers = points[residual <= cal.plane_max_residual_mm]
        if len(inliers) < cal.plane_min_points:
            raise DomainError("NON_PLANAR_FLOOR", "Selected floor is not sufficiently planar")
    residual = inliers @ normal + offset
    return {
        "plane": [*normal.tolist(), offset],
        "rms_mm": float(np.sqrt(np.mean(residual**2))),
        "inlier_count": len(inliers),
        "sample_count": len(points),
        "intrinsics": frame.metadata.intrinsics.model_dump(),
        "camera_serial": frame.metadata.camera_serial,
    }
