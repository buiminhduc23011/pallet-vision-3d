import pytest
from pydantic import ValidationError

from app.schemas.config import AppConfig, DepthMetadata, HSVRange, ROI


def test_hsv_rejects_reversed_and_out_of_range_bounds():
    with pytest.raises(ValidationError):
        HSVRange(low=(180, 0, 0), high=(179, 255, 255))


def test_roi_rejects_crossing_polygon():
    with pytest.raises(ValidationError):
        ROI(points=[(0, 0), (1, 1), (1, 0), (0, 1)])


def test_metric_metadata_requires_declared_alignment():
    with pytest.raises(ValidationError):
        DepthMetadata(
            depth_scale_m=0.001,
            aligned_to_color=False,
            intrinsics={"width": 640, "height": 480, "fx": 600, "fy": 600, "ppx": 320, "ppy": 240},
        )


def test_floor_distance_requires_perpendicular_assumption():
    with pytest.raises(ValidationError):
        AppConfig(calibration={"floor_distance_mm": 2000})


def test_unknown_config_key_is_rejected():
    with pytest.raises(ValidationError):
        AppConfig(positon_tolerance=123)
