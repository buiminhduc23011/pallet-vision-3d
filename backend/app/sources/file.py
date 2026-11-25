import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

from app.errors import DomainError
from app.schemas.config import DepthMetadata, RuntimeConfig
from app.sources.base import FrameBundle, FrameSource


class FileSource(FrameSource):
    def __init__(
        self,
        rgb_path: Path,
        depth_path: Path | None = None,
        metadata_path: Path | None = None,
        runtime: RuntimeConfig | None = None,
    ):
        runtime = runtime or RuntimeConfig()
        self.recording = None
        if rgb_path.suffix.lower() == ".bag":
            if depth_path or metadata_path:
                raise DomainError("INVALID_RECORDING_INPUT", "A bag already contains its depth and metadata")
            from app.sources.realsense import RealSenseSource

            self.recording = RealSenseSource(runtime, bag=rgb_path)
            return
        validate_image_header(rgb_path, runtime.max_image_pixels)
        # imdecode supports non-ASCII Windows paths.
        try:
            rgb = cv2.imdecode(
                np.fromfile(rgb_path, dtype=np.uint8), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION
            )
        except cv2.error as exc:
            raise DomainError("INVALID_IMAGE", "Could not decode RGB image") from exc
        if rgb is None:
            raise DomainError("INVALID_IMAGE", "Could not decode RGB image")
        if rgb.shape[0] * rgb.shape[1] > runtime.max_image_pixels:
            raise DomainError("IMAGE_TOO_LARGE", "Image exceeds configured pixel limit", 413)
        depth, metadata = None, None
        if depth_path:
            try:
                if depth_path.suffix.lower() == ".npy":
                    # mmap bounds memory before copying and rejects object/pickle arrays.
                    depth = np.load(depth_path, allow_pickle=False, mmap_mode="r")
                else:
                    validate_image_header(depth_path, runtime.max_image_pixels)
                    depth = cv2.imdecode(np.fromfile(depth_path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
                if depth is None or depth.ndim != 2 or depth.shape != rgb.shape[:2]:
                    raise ValueError("Depth must be a 2D array matching RGB dimensions")
                if depth_path.suffix.lower() == ".png" and depth.dtype != np.uint16:
                    raise ValueError("Depth PNG must be 16-bit unsigned")
                if depth.dtype.kind not in "uif" or depth.dtype.itemsize > 8:
                    raise ValueError("Depth must be a numeric array")
                if not np.isfinite(depth).all() or (depth < 0).any():
                    raise ValueError("Depth must contain finite, nonnegative values; holes are zero")
                depth = np.array(depth, copy=True)
            except (ValueError, OSError, cv2.error) as exc:
                raise DomainError(
                    "INVALID_DEPTH",
                    "Depth must be a finite nonnegative numeric map matching RGB, with 16-bit PNG encoding",
                ) from exc
            if metadata_path is None:
                raise DomainError("DEPTH_METADATA_REQUIRED", "Aligned depth requires a metadata JSON file")
            try:
                metadata = DepthMetadata.model_validate(
                    json.loads(metadata_path.read_text(encoding="utf-8-sig"))
                )
            except (ValueError, ValidationError) as exc:
                raise DomainError(
                    "INVALID_METADATA", "Invalid depth metadata: check scale, alignment and intrinsics"
                ) from exc
            if (metadata.intrinsics.width, metadata.intrinsics.height) != (rgb.shape[1], rgb.shape[0]):
                raise DomainError(
                    "INTRINSICS_SIZE_MISMATCH", "Intrinsics resolution must match aligned RGB/depth"
                )
        elif metadata_path:
            raise DomainError("DEPTH_REQUIRED", "Metadata must accompany a depth map")
        self.frame = FrameBundle(rgb=rgb, depth=depth, metadata=metadata, source="file")

    def read(self):
        return self.recording.read() if self.recording else self.frame

    def seek(self, seconds):
        if not self.recording:
            raise DomainError("NOT_A_RECORDING", "This file is a static image")
        self.recording.seek(seconds)

    def close(self):
        if self.recording:
            self.recording.close()


def validate_image_header(path: Path, maximum: int):
    try:
        with Image.open(path) as image:
            if image.format not in ("PNG", "JPEG"):
                raise DomainError("INVALID_IMAGE_FORMAT", "Only real JPEG/PNG encodings are supported")
            if image.width * image.height > maximum:
                raise DomainError("IMAGE_TOO_LARGE", "Image exceeds configured pixel limit", 413)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise DomainError("INVALID_IMAGE", "Invalid or oversized image") from exc
