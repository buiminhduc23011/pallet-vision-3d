from app.schemas.config import MatchingConfig
from app.vision.transfer_qc import compare_rolls


def test_empty_reference_is_incomplete_not_pass():
    result = compare_rolls([], [], MatchingConfig(), "px")
    assert result["verdict"] == "INCOMPLETE"
    assert "EMPTY_REFERENCE" in result["reasons"]


# Numerical contract cases, not generated images, camera frames or runtime data.
ROLL = {
    "id": "r1",
    "x_local": 10.0,
    "y_local": 20.0,
    "width": 100.0,
    "height": 80.0,
    "orientation": "STANDING",
    "unit": "px",
}


def test_identical_geometry_passes():
    result = compare_rolls([ROLL], [dict(ROLL, id="c1")], MatchingConfig(), "px")
    assert result["verdict"] == "PASS"
    assert result["matched_count"] == 1


def test_missing_current_is_a_count_failure():
    result = compare_rolls([ROLL], [], MatchingConfig(), "px")
    assert result["verdict"] == "FAIL"
    assert result["missing_count"] == 1


def test_wrong_orientation_is_mismatch_not_match():
    result = compare_rolls([ROLL], [dict(ROLL, orientation="LYING")], MatchingConfig(), "px")
    assert result["mismatch_count"] == 1
    assert result["pairs"][0]["reasons"] == ["WRONG_ORIENTATION"]


def test_unknown_orientation_cannot_pass():
    result = compare_rolls([ROLL], [dict(ROLL, orientation="UNKNOWN")], MatchingConfig(), "px")
    assert result["verdict"] == "INCOMPLETE"


def test_far_away_detection_is_missing_and_extra_not_forced_pair():
    result = compare_rolls([ROLL], [dict(ROLL, x_local=10000)], MatchingConfig(), "px")
    assert result["missing_count"] == result["extra_count"] == 1
    assert result["pairs"] == []


def test_unit_mismatch_is_incomplete():
    result = compare_rolls([ROLL], [dict(ROLL, unit="mm")], MatchingConfig(), "px")
    assert result["verdict"] == "INCOMPLETE"


def test_wrong_size_is_diagnosed():
    result = compare_rolls([ROLL], [dict(ROLL, width=140)], MatchingConfig(), "px")
    assert result["pairs"][0]["reasons"] == ["WRONG_SIZE"]
