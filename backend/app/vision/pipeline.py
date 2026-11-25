from pathlib import Path

import cv2
import numpy as np

from app.errors import DomainError
from app.schemas.config import AppConfig
from app.sources.base import FrameBundle, utcnow
from app.vision.alignment import detect_pallet
from app.vision.classifier import classify
from app.vision.depth_fusion import describe_roll
from app.vision.geometry import roi_mask
from app.vision.roll_detector import FastSAMDetector, YOLOSegDetector


class VisionPipeline:
    """Owned exclusively by the single inference worker; no concurrent model access."""

    def __init__(self, model_root: Path):
        self.model_root = model_root
        self.detector = None
        self.detector_key = None

    def inspect(self, frame: FrameBundle, config: AppConfig):
        warnings, masks = [], []
        pallet, alignment = detect_pallet(frame, config)
        zone = roi_mask(frame.rgb.shape, config.roi)
        detection_region = zone.copy()
        if pallet:
            detection_region[:] = 0
            cv2.fillPoly(detection_region, [np.asarray(pallet["polygon"], np.int32)], 255)
            detection_region &= zone
        detector_state = "READY"
        fingerprint = None
        detections = []
        try:
            key = config.detector.model_dump_json()
            if self.detector is None or self.detector_key != key:
                cls = FastSAMDetector if config.detector.backend == "fastsam" else YOLOSegDetector
                self.detector = cls(self.model_root, config.detector)
                self.detector_key = key
            fingerprint = self.detector.fingerprint
            detections = self.detector.detect(frame.rgb, detection_region)
        except DomainError as exc:
            detector_state = "UNAVAILABLE"
            warnings.append(exc.public())
        material_region = detection_region.copy()
        for detection in detections:
            material_region[detection.mask > 0] = 0
        classification = classify(frame.rgb, material_region, config.classifier)
        if not pallet:
            classification = {
                "material": "UNKNOWN",
                "confidence": 0.0,
                "evidence": {"reason": "PALLET_NOT_FOUND"},
            }
        elif detector_state != "READY":
            classification["evidence"]["goods_exclusion"] = "unavailable"
            warnings.append(
                {
                    "code": "MATERIAL_MAY_INCLUDE_GOODS",
                    "message": "Material estimate includes unsegmented goods",
                }
            )
        rolls = [describe_roll(d, i, frame, pallet, config) for i, d in enumerate(detections)]
        masks = [d.mask for d in detections]
        complete = pallet is not None and alignment["status"] != "INCOMPLETE" and detector_state == "READY"
        if frame.depth is not None and (not pallet or not pallet["metric_transform"]):
            complete = False
            warnings.append(
                {
                    "code": "FLOOR_CALIBRATION_REQUIRED",
                    "message": "RGB-D transfer needs a calibrated floor/base plane",
                }
            )
        if any(
            r["warnings"] or (config.matching.check_orientation and r["orientation"] == "UNKNOWN")
            for r in rolls
        ):
            complete = False
        return {
            "frame_id": frame.id,
            "source": frame.source,
            "captured_at": frame.captured_at,
            "processed_at": utcnow(),
            "config_revision": config.revision,
            "calibration_id": config.calibration.id,
            "model_fingerprint": fingerprint,
            "config_snapshot": config.model_dump(),
            "frame": frame.public(),
            "scope": "RGBD" if frame.depth is not None else "2D",
            "state": "COMPLETE" if complete else "INCOMPLETE",
            "detector_state": detector_state,
            "classification": classification,
            "alignment": alignment,
            "pallet": pallet,
            "rolls": rolls,
            "warnings": warnings,
        }, masks
