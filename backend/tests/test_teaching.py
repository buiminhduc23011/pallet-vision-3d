import numpy as np
import pytest
from app.errors import DomainError

from app.schemas.config import ROI, TeachingConfig
from app.vision.teaching import target_geometry, orient_pallet
from pydantic import ValidationError


def test_taught_origin_preserves_short_x_edge_and_detects_half_turn():
    taught = TeachingConfig(
        source_frame_id="real-frame-id",
        image_width=101,
        image_height=101,
        target=ROI(points=[(0.2, 0.2), (0.4, 0.2), (0.4, 0.8), (0.2, 0.8)]),
    )
    target = target_geometry(taught)
    assert target["width_px"] == pytest.approx(20)
    assert target["center"] == pytest.approx([30, 50])
    pallet = {"polygon": [[20, 20], [40, 20], [40, 80], [20, 80]]}
    oriented = orient_pallet(pallet, target, [40, 80])
    assert oriented["angle_deg"] == pytest.approx(180)
    assert np.allclose(oriented["polygon"][0], [40, 80])


def test_rejects_duplicate_teach_corners():
    with pytest.raises(ValidationError):
        TeachingConfig(
            source_frame_id="frame",
            image_width=101,
            image_height=101,
            target=ROI(points=[(0.2, 0.2), (0.2, 0.2), (0.8, 0.8), (0.2, 0.8)]),
        )


def test_metric_acceptance_projects_mm_tolerance_to_image():
    from app.schemas.config import AppConfig, Intrinsics
    from app.vision.teaching import acceptance_polygon

    config = AppConfig(
        teaching=TeachingConfig(
            source_frame_id="frame",
            image_width=101,
            image_height=101,
            target=ROI(points=[(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]),
        )
    )
    config.calibration.pallet_height_mm = 0
    config.alignment.position_tolerance_mm = 20
    intr = Intrinsics(width=101, height=101, fx=100, fy=100, ppx=50, ppy=50)
    result = acceptance_polygon(config, np.array([0.0, 0.0, -1.0, 1000.0]), intr)
    assert np.allclose(result, [[48, 48], [52, 48], [52, 52], [48, 52]])


def test_matching_rolls_cannot_pass_when_taught_alignment_is_ng():
    from app.vision.teaching import enforce_alignment

    result = {"verdict": "PASS", "reasons": []}
    enforce_alignment(result, {"status": "NG", "reasons": ["Rotated: -180 deg"]})
    assert result["verdict"] == "FAIL"
    assert "Rotated: -180 deg" in result["reasons"]


def test_origin_must_be_near_an_observed_corner():
    teaching = TeachingConfig(
        source_frame_id="frame",
        image_width=101,
        image_height=101,
        target=ROI(points=[(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]),
    )
    target = target_geometry(teaching)
    with pytest.raises(DomainError, match="Select the physical origin"):
        orient_pallet(target, target, [50, 50])


def test_incomplete_alignment_never_becomes_fail_or_pass():
    from app.vision.teaching import enforce_alignment

    result = {"verdict": "INCOMPLETE", "reasons": []}
    enforce_alignment(result, {"status": "NG", "reasons": ["size"]})
    assert result["verdict"] == "INCOMPLETE"
    result = {"verdict": "PASS", "reasons": []}
    enforce_alignment(result, {"status": "INCOMPLETE", "reasons": ["ORIGIN_CONFIRMATION_REQUIRED"]})
    assert result["verdict"] == "INCOMPLETE"


def test_counterclockwise_teaching_is_rejected():
    with pytest.raises(ValidationError):
        TeachingConfig(
            source_frame_id="frame",
            image_width=101,
            image_height=101,
            target=ROI(points=[(0.2, 0.2), (0.2, 0.8), (0.8, 0.8), (0.8, 0.2)]),
        )


def test_taught_material_region_follows_observed_translation():
    from app.vision.teaching import following_mask

    teaching = TeachingConfig(
        source_frame_id="frame",
        image_width=101,
        image_height=101,
        target=ROI(points=[(0.2, 0.2), (0.6, 0.2), (0.6, 0.6), (0.2, 0.6)]),
    )
    target = target_geometry(teaching)
    current = {"polygon": (np.array(target["polygon"]) + [10, 20]).tolist()}
    mask = following_mask(
        (101, 101), ROI(points=[(0.3, 0.3), (0.4, 0.3), (0.4, 0.4), (0.3, 0.4)]), teaching, current
    )
    y, x = np.nonzero(mask)
    assert (x.min(), x.max(), y.min(), y.max()) == (40, 50, 50, 60)


def test_taught_roll_coordinates_start_at_physical_origin():
    from app.vision.geometry import local_pixels

    pallet = {"center": [50, 50], "local_origin": [20, 20], "basis": [[1, 0], [0, 1]]}
    assert np.allclose(local_pixels([[20, 20], [50, 50]], pallet), [[0, 0], [30, 30]])
