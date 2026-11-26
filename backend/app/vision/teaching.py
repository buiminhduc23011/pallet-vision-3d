"""Taught geometry is a target, never a substitute for an observed contour."""

import cv2
import numpy as np

from app.errors import DomainError
from app.schemas.config import ROI, TeachingConfig
from app.vision.geometry import deproject, roi_mask


def geometry(points):
    p = np.asarray(points, dtype=float)
    edge = p[1] - p[0]
    x = edge / np.linalg.norm(edge)
    return {
        "center": p.mean(axis=0).tolist(),
        "polygon": p.tolist(),
        "width_px": float((np.linalg.norm(p[1] - p[0]) + np.linalg.norm(p[2] - p[3])) / 2),
        "height_px": float((np.linalg.norm(p[3] - p[0]) + np.linalg.norm(p[2] - p[1])) / 2),
        "angle_deg": float(np.rad2deg(np.arctan2(x[1], x[0]))),
        "basis": [x.tolist(), [-float(x[1]), float(x[0])]],
    }


def enforce_alignment(result, alignment):
    if alignment["status"] == "INCOMPLETE":
        result["verdict"] = "INCOMPLETE"
    elif alignment["status"] == "NG" and result["verdict"] != "INCOMPLETE":
        result["verdict"] = "FAIL"
    if alignment["status"] != "OK":
        result["reasons"].extend(alignment["reasons"])


def target_geometry(teaching: TeachingConfig):
    return geometry(
        np.asarray(teaching.target.points) * [teaching.image_width - 1, teaching.image_height - 1]
    )


def orient_pallet(pallet, target, origin=None):
    p = np.asarray(pallet["polygon"], dtype=float)
    center = p.mean(axis=0)
    p = p[np.argsort(np.arctan2(p[:, 1] - center[1], p[:, 0] - center[0]))]
    variants = [np.roll(p, -i, axis=0) for i in range(4)]
    if origin is not None:
        distances = [np.linalg.norm(v[0] - origin) for v in variants]
        if min(distances) > np.linalg.norm(p[0] - p[2]) * 0.2:
            raise DomainError(
                "ORIGIN_NOT_NEAR_CORNER", "Select the physical origin near a detected pallet corner"
            )
        chosen = variants[int(np.argmin(distances))]
    else:
        reference = np.asarray(target["polygon"]) - target["center"]
        chosen = min(variants, key=lambda v: np.linalg.norm(v - center - reference))
    return {**pallet, **geometry(chosen)}


def validate_teaching_frame(teaching, frame):
    if teaching is None:
        return
    if frame.rgb.shape[:2] != (teaching.image_height, teaching.image_width):
        raise DomainError(
            "TEACHING_FRAME_MISMATCH",
            "Image resolution differs from taught setup; teach this camera again",
            409,
        )
    intr = frame.metadata.intrinsics if frame.metadata else None
    serial = frame.metadata.camera_serial if frame.metadata else None
    if teaching.intrinsics != intr or teaching.camera_serial != serial:
        raise DomainError("TEACHING_CAMERA_MISMATCH", "Camera/intrinsics differ from taught setup", 409)


def following_mask(shape, region: ROI, teaching, pallet):
    """Move taught material/roll regions with the observed ordered pallet corners."""
    source = np.asarray(target_geometry(teaching)["polygon"], np.float32)
    transform = cv2.getPerspectiveTransform(source, np.asarray(pallet["polygon"], np.float32))
    return cv2.warpPerspective(
        roi_mask(shape, region), transform, (shape[1], shape[0]), flags=cv2.INTER_NEAREST
    )


def acceptance_polygon(config, plane=None, intrinsics=None):
    if config.teaching is None:
        return None
    target = target_geometry(config.teaching)
    center, basis = np.asarray(target["center"]), np.asarray(target["basis"])
    corners = np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]])
    if intrinsics is None:
        return (center + corners * config.alignment.position_tolerance_px @ basis).tolist()
    if plane is None or (intrinsics.distortion == "inverse_brown_conrady" and any(intrinsics.coeffs)):
        return None
    rays = deproject(np.array([center, center + basis[0]]), np.ones(2), intrinsics)
    denominator = rays @ plane[:3]
    if np.any(np.abs(denominator) < 1e-6):
        return None
    support = rays * ((config.calibration.pallet_height_mm - plane[3]) / denominator)[:, None]
    if np.any(support[:, 2] <= 0):
        return None
    x = support[1] - support[0]
    x /= np.linalg.norm(x)
    y = np.cross(x, plane[:3])
    y /= np.linalg.norm(y)
    points = support[0] + corners * config.alignment.position_tolerance_mm @ np.array([x, y])
    if np.any(points[:, 2] <= 0):
        return None
    intr = intrinsics
    matrix = np.array([[intr.fx, 0, intr.ppx], [0, intr.fy, intr.ppy], [0, 0, 1]], dtype=float)
    coeffs = np.asarray(intr.coeffs, dtype=float) if intr.distortion == "brown_conrady" else np.zeros(5)
    projected, _ = cv2.projectPoints(points, np.zeros(3), np.zeros(3), matrix, coeffs)
    return projected.reshape(-1, 2).tolist()
