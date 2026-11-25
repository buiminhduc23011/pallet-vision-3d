from abc import ABC, abstractmethod
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import cv2
import numpy as np

from app.errors import DomainError
from app.schemas.config import DetectorConfig
from app.vision.geometry import canonical_rect


@dataclass
class RollDetection:
    mask: np.ndarray
    geometry: dict


class RollDetector(ABC):
    @abstractmethod
    def detect(self, rgb: np.ndarray, roi: np.ndarray) -> list[RollDetection]: ...


def trusted_model_path(root: Path, configured: str) -> Path:
    path = (root / configured).resolve()
    if not path.is_relative_to(root.resolve()):
        raise DomainError("UNTRUSTED_MODEL_PATH", "Model must be inside the configured models directory")
    if not path.exists():
        raise DomainError(
            "MODEL_NOT_FOUND",
            "Model weights not found. Place trusted weights in models/ and update Settings",
            503,
        )
    if not (path.is_file() and path.suffix.lower() == ".pt") and not (
        path.is_dir() and list(path.glob("*.xml"))
    ):
        raise DomainError("INVALID_MODEL", "Expected a .pt file or OpenVINO export directory")
    return path


class UltralyticsDetector(RollDetector):
    def __init__(self, root: Path, config: DetectorConfig):
        self.config = config
        path = trusted_model_path(root, config.model_path)
        try:
            from ultralytics import FastSAM, YOLO
        except ImportError as exc:
            raise DomainError(
                "DETECTOR_DEPENDENCY_MISSING", "Install backend[vision] to enable roll segmentation", 503
            ) from exc
        try:
            self.model = (
                FastSAM(str(path)) if config.backend == "fastsam" else YOLO(str(path), task="segment")
            )
        except Exception as exc:
            raise DomainError(
                "MODEL_LOAD_FAILED", "Could not load the selected segmentation model", 503
            ) from exc
        digest = sha256()
        for file in [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file()):
            if file.is_symlink() or not file.resolve().is_relative_to(root.resolve()):
                raise DomainError("UNTRUSTED_MODEL_PATH", "Model artifacts must remain inside models/")
            with file.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
        self.fingerprint = digest.hexdigest()

    def detect(self, rgb, roi):
        cfg = self.config
        x, y, width, height = cv2.boundingRect(roi)
        if width == 0 or height == 0:
            return []
        crop = rgb[y : y + height, x : x + width].copy()
        crop[roi[y : y + height, x : x + width] == 0] = 0
        try:
            results = self.model.predict(
                crop,
                device=cfg.device,
                imgsz=cfg.image_size,
                conf=cfg.confidence,
                iou=cfg.iou,
                retina_masks=True,
                verbose=False,
            )
        except Exception as exc:
            raise DomainError(
                "INFERENCE_FAILED",
                "Segmentation failed; check model format, device and available memory",
                503,
            ) from exc
        detections = []
        for result in results:
            if result.masks is None:
                continue
            masks = result.masks.data.cpu().numpy()
            for index, raw in enumerate(masks):
                label = None
                if cfg.backend == "yolo":
                    label = result.names[int(result.boxes.cls[index].item())]
                    if label not in (cfg.standing_class, cfg.lying_class):
                        continue
                resized = (
                    cv2.resize(raw.astype(np.float32), (width, height), interpolation=cv2.INTER_NEAREST) > 0.5
                )
                mask = np.zeros(roi.shape, np.uint8)
                mask[y : y + height, x : x + width] = resized.astype(np.uint8) * 255
                mask &= roi
                area = int(np.count_nonzero(mask))
                if not cfg.min_area_px <= area <= cfg.max_area_px:
                    continue
                contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                if not contours:
                    continue
                contour = max(contours, key=cv2.contourArea)
                geom = canonical_rect(contour)
                aspect = geom["width_px"] / max(geom["height_px"], 1)
                perimeter = cv2.arcLength(contour, True)
                circularity = float(4 * np.pi * cv2.contourArea(contour) / max(perimeter**2, 1))
                if aspect > cfg.max_aspect_ratio or circularity < cfg.min_circularity:
                    continue
                if label:
                    orientation = "STANDING" if label == cfg.standing_class else "LYING"
                elif circularity >= cfg.standing_circularity and aspect <= cfg.standing_max_aspect:
                    orientation = "STANDING"
                elif aspect >= cfg.lying_min_aspect:
                    orientation = "LYING"
                else:
                    orientation = "UNKNOWN"
                moment = cv2.moments(mask, binaryImage=True)
                geom.update(
                    {
                        "centroid": [moment["m10"] / moment["m00"], moment["m01"] / moment["m00"]],
                        "orientation": orientation,
                        "orientation_method": "model_class" if label else "shape_heuristic",
                        "circularity": circularity,
                        "aspect_ratio": aspect,
                        "area_px": area,
                        "confidence": float(result.boxes.conf[index].item())
                        if result.boxes is not None
                        else None,
                    }
                )
                detections.append(RollDetection(mask, geom))
        # Prefer smaller individual regions to enclosing everything-masks from FastSAM.
        retained = []
        for detection in sorted(detections, key=lambda d: d.geometry["area_px"]):
            if any(
                np.count_nonzero(detection.mask & old.mask)
                / min(detection.geometry["area_px"], old.geometry["area_px"])
                >= cfg.duplicate_overlap
                for old in retained
            ):
                continue
            retained.append(detection)
        return retained


class FastSAMDetector(UltralyticsDetector):
    def __init__(self, root, config):
        super().__init__(root, config.model_copy(update={"backend": "fastsam"}))


class YOLOSegDetector(UltralyticsDetector):
    def __init__(self, root, config):
        super().__init__(root, config.model_copy(update={"backend": "yolo"}))
