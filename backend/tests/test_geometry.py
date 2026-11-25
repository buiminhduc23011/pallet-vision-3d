import numpy as np
import pytest

from app.schemas.config import Intrinsics
from app.vision.geometry import deproject, local_pixels


def test_pinhole_deprojection_uses_intrinsics_and_metric_depth():
    intrinsics = Intrinsics(width=640, height=480, fx=600, fy=600, ppx=320, ppy=240)
    points = deproject([[320, 240], [380, 300]], np.array([1000, 1000]), intrinsics)
    np.testing.assert_allclose(points, [[0, 0, 1000], [100, 100, 1000]])


def test_local_frame_removes_pallet_translation_and_rotation():
    pallet = {"center": [100, 200], "basis": [[0, 1], [-1, 0]]}
    np.testing.assert_allclose(local_pixels([[100, 210]], pallet), [[10, 0]])


def test_model_path_rejects_traversal(tmp_path):
    from app.errors import DomainError
    from app.vision.roll_detector import trusted_model_path

    with pytest.raises(DomainError) as exc:
        trusted_model_path(tmp_path, "../outside.pt")
    assert exc.value.code == "UNTRUSTED_MODEL_PATH"


def test_model_missing_is_explicit_not_empty_detection(tmp_path):
    from app.errors import DomainError
    from app.schemas.config import DetectorConfig
    from app.vision.roll_detector import FastSAMDetector

    with pytest.raises(DomainError) as exc:
        FastSAMDetector(tmp_path, DetectorConfig())
    assert exc.value.code == "MODEL_NOT_FOUND"
