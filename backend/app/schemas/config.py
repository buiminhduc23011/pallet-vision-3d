from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class HSVRange(StrictModel):
    low: tuple[int, int, int]
    high: tuple[int, int, int]

    @model_validator(mode="after")
    def bounds(self):
        for i, maximum in enumerate((179, 255, 255)):
            if not 0 <= self.low[i] <= self.high[i] <= maximum:
                raise ValueError("HSV bounds must be ordered; H: 0..179, S/V: 0..255")
        return self


class ROI(StrictModel):
    # Normalized image coordinates; preserves a drawn ROI across display sizes.
    points: list[tuple[float, float]] = Field(
        default_factory=lambda: [(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)],
        min_length=3,
        max_length=32,
    )

    @model_validator(mode="after")
    def bounds(self):
        if any(not 0 <= v <= 1 for p in self.points for v in p):
            raise ValueError("ROI coordinates must be between 0 and 1")
        area = (
            abs(
                sum(
                    self.points[i][0] * self.points[(i + 1) % len(self.points)][1]
                    - self.points[(i + 1) % len(self.points)][0] * self.points[i][1]
                    for i in range(len(self.points))
                )
            )
            / 2
        )
        if area < 0.0001:
            raise ValueError("ROI must have non-zero area")
        # Require convex, consistently ordered vertices, rejecting bow-ties.
        signs = []
        for i, a in enumerate(self.points):
            b, c = self.points[(i + 1) % len(self.points)], self.points[(i + 2) % len(self.points)]
            cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
            if abs(cross) > 1e-9:
                signs.append(cross > 0)
        if not signs or len(set(signs)) > 1:
            raise ValueError("Use a convex, non-intersecting ROI")
        return self


class Intrinsics(StrictModel):
    width: int = Field(gt=0, le=16384)
    height: int = Field(gt=0, le=16384)
    fx: float = Field(gt=0)
    fy: float = Field(gt=0)
    ppx: float
    ppy: float
    distortion: Literal["none", "brown_conrady", "inverse_brown_conrady"] = "none"
    coeffs: list[float] = Field(default_factory=lambda: [0.0] * 5, min_length=5, max_length=5)


class DepthMetadata(StrictModel):
    depth_scale_m: float = Field(gt=0, le=1)
    aligned_to_color: Literal[True]
    intrinsics: Intrinsics
    camera_serial: str | None = None


class CalibrationConfig(StrictModel):
    id: str | None = None
    intrinsics: Intrinsics | None = None
    # Plane in camera mm: n dot point + d = 0. Normal points toward camera.
    floor_plane: tuple[float, float, float, float] | None = None
    floor_distance_mm: float | None = Field(default=None, gt=0)
    perpendicular_camera: bool = False
    camera_serial: str | None = None
    pallet_height_mm: float = Field(default=150, ge=0)
    plane_max_residual_mm: float = Field(default=10, gt=0)
    plane_min_points: int = Field(default=100, ge=3)
    plane_max_points: int = Field(default=10000, ge=100)

    @model_validator(mode="after")
    def plane_valid(self):
        if self.floor_plane is not None:
            norm = sum(v * v for v in self.floor_plane[:3]) ** 0.5
            if abs(norm - 1) > 0.001:
                raise ValueError("Floor plane normal must be a unit vector")
        if self.floor_distance_mm is not None and not self.perpendicular_camera:
            raise ValueError("Scalar floor distance requires perpendicular_camera=true")
        return self


class ClassifierConfig(StrictModel):
    wood: list[HSVRange] = Field(
        default_factory=lambda: [HSVRange(low=(5, 25, 35), high=(38, 230, 255))], min_length=1
    )
    plastic: list[HSVRange] = Field(
        default_factory=lambda: [
            HSVRange(low=(90, 55, 30), high=(135, 255, 255)),
            HSVRange(low=(35, 45, 30), high=(85, 255, 255)),
            HSVRange(low=(0, 0, 0), high=(179, 255, 45)),
        ],
        min_length=1,
    )
    minimum_coverage: float = Field(default=0.3, ge=0, le=1)
    minimum_margin: float = Field(default=0.12, ge=0, le=1)
    minimum_pixels: int = Field(default=200, ge=1)
    histogram_bins: int = Field(default=18, ge=2, le=180)
    histogram_weight: float = Field(default=0.25, ge=0, le=1)
    # Optional operator-supplied normalized hue histograms from real samples.
    wood_histogram: list[float] | None = None
    plastic_histogram: list[float] | None = None

    @model_validator(mode="after")
    def histograms(self):
        for hist in (self.wood_histogram, self.plastic_histogram):
            if hist is not None and (
                len(hist) != self.histogram_bins or any(x < 0 for x in hist) or sum(hist) <= 0
            ):
                raise ValueError("Histogram must have histogram_bins nonnegative entries and positive mass")
        return self


class AlignmentConfig(StrictModel):
    target_angle_deg: float = Field(default=0, ge=-180, le=180)
    position_tolerance_px: float = Field(default=20, gt=0)
    position_tolerance_mm: float = Field(default=20, gt=0)
    rotation_tolerance_deg: float = Field(default=5, gt=0, le=90)
    canny_low: int = Field(default=40, ge=0, le=255)
    canny_high: int = Field(default=120, ge=0, le=255)
    contour_min_area_fraction: float = Field(default=0.08, gt=0, le=1)
    morphology_kernel: int = Field(default=5, ge=1, le=31)
    height_band_mm: float = Field(default=100, gt=0)
    min_rectangularity: float = Field(default=0.55, ge=0, le=1)
    boundary_margin_px: float = Field(default=2, ge=0)
    square_ambiguity_ratio: float = Field(default=1.08, ge=1)


class DetectorConfig(StrictModel):
    backend: Literal["fastsam", "yolo"] = "fastsam"
    model_path: str = "FastSAM-s.pt"
    device: str = "cpu"
    confidence: float = Field(default=0.4, gt=0, le=1)
    iou: float = Field(default=0.7, gt=0, le=1)
    image_size: int = Field(default=1024, ge=128, le=2048)
    min_area_px: int = Field(default=300, ge=1)
    max_area_px: int = Field(default=400000, ge=1)
    max_aspect_ratio: float = Field(default=8, ge=1)
    min_circularity: float = Field(default=0.08, ge=0, le=1)
    standing_circularity: float = Field(default=0.65, ge=0, le=1)
    standing_max_aspect: float = Field(default=1.35, ge=1)
    lying_min_aspect: float = Field(default=1.6, ge=1)
    duplicate_overlap: float = Field(default=0.85, gt=0, le=1)
    standing_class: str = "roll_standing"
    lying_class: str = "roll_lying"
    depth_valid_fraction: float = Field(default=0.25, gt=0, le=1)
    minimum_depth_mm: float = Field(default=100, gt=0)
    maximum_depth_mm: float = Field(default=10000, gt=0)

    @model_validator(mode="after")
    def ordered(self):
        if self.min_area_px > self.max_area_px or self.minimum_depth_mm >= self.maximum_depth_mm:
            raise ValueError("Minimum must be below maximum")
        return self


class MatchingConfig(StrictModel):
    position_tolerance_px: float = Field(default=25, gt=0)
    position_tolerance_mm: float = Field(default=25, gt=0)
    size_tolerance_percent: float = Field(default=15, gt=0)
    check_orientation: bool = True
    position_weight: float = Field(default=1, gt=0)
    size_weight: float = Field(default=0.5, ge=0)
    orientation_weight: float = Field(default=1, ge=0)
    candidate_gate_multiplier: float = Field(default=5, gt=1)
    unmatched_cost: float = Field(default=4, gt=0)
    minimum_reference_count: int = Field(default=1, ge=1)
    canonical_pallet_width_px: float = Field(default=1000, gt=0)
    pallet_aspect_tolerance_percent: float = Field(default=15, gt=0)


class RuntimeConfig(StrictModel):
    camera_width: int = Field(default=640, ge=320, le=1920)
    camera_height: int = Field(default=480, ge=240, le=1080)
    camera_fps: int = Field(default=30, ge=1, le=90)
    frame_timeout_ms: int = Field(default=3000, ge=100, le=10000)
    stream_fps: int = Field(default=10, ge=1, le=30)
    jpeg_quality: int = Field(default=85, ge=20, le=100)
    continuous_interval_seconds: float = Field(default=2, ge=0.2, le=3600)
    max_upload_mb: int = Field(default=512, ge=1, le=8192)
    max_image_pixels: int = Field(default=16000000, ge=1000, le=64000000)
    max_pending_jobs: int = Field(default=8, ge=1, le=100)
    max_pinned_frames: int = Field(default=16, ge=2, le=100)
    depth_colormap_max_mm: float = Field(default=4000, gt=0)
    minimum_free_disk_mb: int = Field(default=1024, ge=100)


class AppConfig(StrictModel):
    schema_version: Literal[1] = 1
    revision: int = Field(default=1, ge=1)
    roi: ROI = Field(default_factory=ROI)
    calibration: CalibrationConfig = Field(default_factory=CalibrationConfig)
    classifier: ClassifierConfig = Field(default_factory=ClassifierConfig)
    alignment: AlignmentConfig = Field(default_factory=AlignmentConfig)
    detector: DetectorConfig = Field(default_factory=DetectorConfig)
    matching: MatchingConfig = Field(default_factory=MatchingConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
