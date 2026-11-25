from datetime import timedelta
from pathlib import Path

import numpy as np

from app.errors import DomainError
from app.schemas.config import DepthMetadata, Intrinsics, RuntimeConfig
from app.sources.base import FrameBundle, FrameSource


def sdk():
    try:
        import pyrealsense2 as rs

        return rs
    except ImportError as exc:
        raise DomainError(
            "REALSENSE_SDK_MISSING", "Install the camera extra to use RealSense or .bag files", 503
        ) from exc


def camera_status():
    try:
        rs = sdk()
        devices = rs.context().query_devices()
        return {
            "sdk_available": True,
            "devices": [
                {"serial": d.get_info(rs.camera_info.serial_number), "name": d.get_info(rs.camera_info.name)}
                for d in devices
            ],
            "error": None,
        }
    except (DomainError, RuntimeError) as exc:
        return {"sdk_available": not isinstance(exc, DomainError), "devices": [], "error": str(exc)}


class RealSenseSource(FrameSource):
    def __init__(self, runtime: RuntimeConfig, serial: str | None = None, bag: Path | None = None):
        self.rs = rs = sdk()
        self.runtime, self.bag = runtime, bag
        self.pipeline = rs.pipeline()
        config = rs.config()
        if bag:
            config.enable_device_from_file(str(bag), repeat_playback=False)
        else:
            if serial:
                config.enable_device(serial)
            config.enable_stream(
                rs.stream.color,
                runtime.camera_width,
                runtime.camera_height,
                rs.format.bgr8,
                runtime.camera_fps,
            )
            config.enable_stream(
                rs.stream.depth,
                runtime.camera_width,
                runtime.camera_height,
                rs.format.z16,
                runtime.camera_fps,
            )
        try:
            self.profile = self.pipeline.start(config)
            device = self.profile.get_device()
            self.scale = device.first_depth_sensor().get_depth_scale()
            self.serial = device.get_info(rs.camera_info.serial_number)
            self.playback = device.as_playback() if bag else None
            if self.playback:
                self.playback.set_real_time(False)
            self.align = rs.align(rs.stream.color)
        except RuntimeError as exc:
            try:
                self.pipeline.stop()
            except RuntimeError:
                pass  # start failed; no running pipeline to release
            raise DomainError(
                "SOURCE_UNAVAILABLE",
                "Cannot start RealSense source; check device/recording and stream profile",
                503,
            ) from exc

    def read(self):
        try:
            frames = self.pipeline.wait_for_frames(self.runtime.frame_timeout_ms)
            frames = self.align.process(frames)
            color, depth = frames.get_color_frame(), frames.get_depth_frame()
            if not color or not depth:
                raise DomainError(
                    "FRAME_INCOMPLETE", "Recording/camera must contain both color and depth", 503
                )
            intr = color.profile.as_video_stream_profile().intrinsics
            mapping = {
                self.rs.distortion.none: "none",
                self.rs.distortion.brown_conrady: "brown_conrady",
                self.rs.distortion.inverse_brown_conrady: "inverse_brown_conrady",
            }
            if intr.model not in mapping:
                raise DomainError(
                    "UNSUPPORTED_DISTORTION",
                    "Camera distortion model is not supported by this calibration pipeline",
                )
            metadata = DepthMetadata(
                depth_scale_m=self.scale,
                aligned_to_color=True,
                camera_serial=self.serial,
                intrinsics=Intrinsics(
                    width=intr.width,
                    height=intr.height,
                    fx=intr.fx,
                    fy=intr.fy,
                    ppx=intr.ppx,
                    ppy=intr.ppy,
                    distortion=mapping[intr.model],
                    coeffs=list(intr.coeffs),
                ),
            )
            return FrameBundle(
                rgb=np.asanyarray(color.get_data()).copy(),
                depth=np.asanyarray(depth.get_data()).copy(),
                metadata=metadata,
                source="bag" if self.bag else "realsense",
            )
        except RuntimeError as exc:
            if self.playback and self.playback.current_status() == self.rs.playback_status.stopped:
                return None
            raise DomainError(
                "CAMERA_TIMEOUT", "No aligned frame received; check camera connection", 503
            ) from exc

    def seek(self, seconds: float):
        if not self.playback:
            raise DomainError("NOT_A_RECORDING", "Seeking is only available for .bag recordings")
        duration = self.playback.get_duration().total_seconds()
        if not 0 <= seconds < duration:
            raise DomainError("INVALID_SEEK", "Playback position is outside the recording")
        self.playback.seek(timedelta(seconds=seconds))

    def close(self):
        self.pipeline.stop()
