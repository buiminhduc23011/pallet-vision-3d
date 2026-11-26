import cv2
import numpy as np

from app.errors import DomainError
from app.schemas.config import Intrinsics, ROI


def roi_mask(shape: tuple, roi: ROI) -> np.ndarray:
    h, w = shape[:2]
    points = np.round(np.asarray(roi.points) * [w - 1, h - 1]).astype(np.int32)
    mask = np.zeros((h, w), np.uint8)
    cv2.fillPoly(mask, [points], 255)
    return mask


def deproject(pixels: np.ndarray, depth_mm: np.ndarray, intr: Intrinsics) -> np.ndarray:
    pixels = np.asarray(pixels, dtype=np.float64).reshape(-1, 2)
    x, y = (pixels[:, 0] - intr.ppx) / intr.fx, (pixels[:, 1] - intr.ppy) / intr.fy
    if intr.distortion == "brown_conrady" and any(intr.coeffs):
        matrix = np.array([[intr.fx, 0, intr.ppx], [0, intr.fy, intr.ppy], [0, 0, 1]], dtype=float)
        normalized = cv2.undistortPoints(pixels.reshape(-1, 1, 2), matrix, np.asarray(intr.coeffs)).reshape(
            -1, 2
        )
        x, y = normalized[:, 0], normalized[:, 1]
    elif intr.distortion == "inverse_brown_conrady" and any(intr.coeffs):
        # RealSense SDK handles the inverse model with its exact convention.
        try:
            from app.sources.realsense import sdk

            rs = sdk()
            rs_intr = rs.intrinsics()
            for key in ("width", "height", "fx", "fy", "ppx", "ppy", "coeffs"):
                setattr(rs_intr, key, getattr(intr, key))
            rs_intr.model = rs.distortion.inverse_brown_conrady
            return np.array(
                [
                    rs.rs2_deproject_pixel_to_point(rs_intr, p.tolist(), float(z))
                    for p, z in zip(pixels, np.broadcast_to(depth_mm, len(pixels)))
                ]
            )
        except ImportError as exc:
            raise DomainError(
                "DISTORTION_SDK_REQUIRED", "This depth file requires the RealSense SDK for deprojection"
            ) from exc
    z = np.broadcast_to(depth_mm, len(pixels))
    return np.column_stack((x * z, y * z, z))


def canonical_rect(contour):
    (cx, cy), (width, height), angle = cv2.minAreaRect(contour)
    if width < height:
        width, height = height, width
        angle += 90
    angle = (angle + 90) % 180 - 90
    theta = np.deg2rad(angle)
    # Rows are the local basis; canonical x follows the long pallet edge.
    basis = np.array([[np.cos(theta), np.sin(theta)], [-np.sin(theta), np.cos(theta)]])
    box = cv2.boxPoints(((cx, cy), (width, height), angle))
    return {
        "center": [float(cx), float(cy)],
        "width_px": float(width),
        "height_px": float(height),
        "angle_deg": float(angle),
        "polygon": box.tolist(),
        "basis": basis.tolist(),
    }


def local_pixels(points, pallet):
    return (np.asarray(points) - pallet.get("local_origin", pallet["center"])) @ np.asarray(pallet["basis"]).T
