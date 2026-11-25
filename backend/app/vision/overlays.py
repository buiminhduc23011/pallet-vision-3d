import cv2
import numpy as np

from app.schemas.config import AppConfig
from app.sources.base import FrameBundle


def depth_image(frame: FrameBundle, config: AppConfig):
    if frame.depth is None or frame.metadata is None:
        return None
    mm = frame.depth.astype(float) * frame.metadata.depth_scale_m * 1000
    normalized = np.clip(mm / config.runtime.depth_colormap_max_mm * 255, 0, 255).astype(np.uint8)
    colored = cv2.applyColorMap(normalized, cv2.COLORMAP_TURBO)
    colored[frame.depth == 0] = 0
    return colored


def draw_overlay(rgb, result, masks=(), verification=None):
    image = rgb.copy()
    colors = {}
    if verification:
        for pair in verification["pairs"]:
            colors[pair["current_roll_id"]] = (40, 160, 45) if not pair["reasons"] else (0, 120, 240)
        for extra in verification["extra"]:
            colors[extra["id"]] = (30, 50, 220)
    for index, roll in enumerate(result["rolls"]):
        color = colors.get(roll["id"], (185, 145, 20))
        if index < len(masks):
            selected = masks[index] > 0
            image[selected] = (image[selected] * 0.7 + np.array(color) * 0.3).astype(np.uint8)
        box = np.asarray(roll["rotated_box"], np.int32)
        cv2.polylines(image, [box], True, color, 2, cv2.LINE_AA)
        reasons = (
            next((p["reasons"] for p in verification["pairs"] if p["current_roll_id"] == roll["id"]), [])
            if verification
            else []
        )
        label = f"{roll['id']} {'/'.join(reasons) if reasons else roll['orientation']}"
        cv2.putText(image, label, tuple(box[0]), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
    if result["pallet"]:
        cv2.polylines(image, [np.asarray(result["pallet"]["polygon"], np.int32)], True, (150, 90, 220), 2)
    return image
