from uuid import uuid4

import cv2
import numpy as np
from fastapi import APIRouter, Query, Request, Response
from pydantic import Field

from app.errors import DomainError
from app.schemas.config import AppConfig, ROI, StrictModel
from app.sources.base import utcnow
from app.vision.teaching import acceptance_polygon, validate_teaching_frame
from app.vision.calibration import floor_plane

router = APIRouter(prefix="/api/v1")


def validate_setup(engine, config):
    if config.teaching is None:
        raise DomainError("TEACHING_REQUIRED", "Teach a pallet on a pinned real frame first")
    frame = engine.store.load_frame(config.teaching.source_frame_id)
    validate_teaching_frame(config.teaching, frame)
    boundary = np.asarray(config.roi.points, np.float32)
    if any(cv2.pointPolygonTest(boundary, p, False) < 0 for p in config.teaching.target.points):
        raise DomainError(
            "TARGET_OUTSIDE_SEARCH", "All taught pallet corners must be inside the search region"
        )
    target = np.asarray(config.teaching.target.points, np.float32)
    for region in (config.teaching.material_roi, config.teaching.roll_roi):
        if region and any(cv2.pointPolygonTest(target, p, False) < 0 for p in region.points):
            raise DomainError(
                "REGION_OUTSIDE_PALLET", "Material and roll regions must be inside the taught pallet"
            )


class TeachingRequest(StrictModel):
    frame_id: str
    config: AppConfig


class TeachingPreview(StrictModel):
    config: AppConfig
    acceptance_polygon: list[tuple[float, float]] | None
    position_unit: str


class RecipeSummary(StrictModel):
    id: str
    name: str
    created_at: str


class Recipe(RecipeSummary):
    config: AppConfig


class RecipePage(StrictModel):
    items: list[RecipeSummary]
    next_cursor: str | None


class SampleResult(StrictModel):
    histogram: list[float]
    sample_pixels: int


@router.post("/teachings", response_model=TeachingPreview)
def prepare_teaching(value: TeachingRequest, request: Request):
    engine = request.app.state.engine
    frame = engine.store.load_frame(value.frame_id)
    teaching = value.config.teaching
    if teaching is None:
        raise DomainError("TEACHING_REQUIRED", "Draw the four pallet corners first")
    teaching.source_frame_id = frame.id
    teaching.image_width = frame.rgb.shape[1]
    teaching.image_height = frame.rgb.shape[0]
    teaching.intrinsics = frame.metadata.intrinsics if frame.metadata else None
    teaching.camera_serial = frame.metadata.camera_serial if frame.metadata else None
    validate_setup(engine, value.config)
    polygon = acceptance_polygon(
        value.config, floor_plane(value.config, frame), frame.metadata.intrinsics if frame.metadata else None
    )
    return {
        "config": value.config.model_dump(),
        "acceptance_polygon": polygon,
        "position_unit": "mm" if frame.metadata else "px",
    }


class RecipeCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120, pattern=r"\S")
    config: AppConfig


@router.post("/recipes", status_code=201, response_model=Recipe)
def save_recipe(value: RecipeCreate, request: Request, response: Response):
    engine = request.app.state.engine
    validate_setup(engine, value.config)
    engine.require_storage()
    identifier = uuid4().hex
    recipe = {
        "id": identifier,
        "name": value.name.strip(),
        "created_at": utcnow(),
        "config": value.config.model_dump(),
    }
    engine.db.save("recipe", identifier, recipe)
    response.headers["Location"] = f"/api/v1/recipes/{identifier}"
    return recipe


@router.get("/recipes", response_model=RecipePage)
def list_recipes(
    request: Request, limit: int = Query(25, ge=1, le=100), cursor: int | None = Query(None, gt=0)
):
    with request.app.state.engine.db.connect() as db:
        rows = db.execute(
            "SELECT seq,id,created_at,json_extract(payload,'$.name') AS name FROM resources "
            "WHERE kind='recipe' AND (? IS NULL OR seq < ?) ORDER BY seq DESC LIMIT ?",
            (cursor, cursor, limit + 1),
        ).fetchall()
    return {
        "items": [{"id": r["id"], "name": r["name"], "created_at": r["created_at"]} for r in rows[:limit]],
        "next_cursor": str(rows[limit - 1]["seq"]) if len(rows) > limit else None,
    }


@router.get("/recipes/{identifier}", response_model=Recipe)
def get_recipe(identifier: str, request: Request):
    return request.app.state.engine.db.get("recipe", identifier)


class MaterialSample(StrictModel):
    frame_id: str
    roi: ROI
    bins: int = Field(default=18, ge=2, le=180)


@router.post("/material-samples", response_model=SampleResult)
def material_sample(value: MaterialSample, request: Request):
    from app.vision.geometry import roi_mask

    frame = request.app.state.engine.store.load_frame(value.frame_id)
    mask = roi_mask(frame.rgb.shape, value.roi)
    if np.count_nonzero(mask) < request.app.state.engine.config.get().classifier.minimum_pixels:
        raise DomainError("SAMPLE_TOO_SMALL", "Select a larger exposed material patch")
    hsv = cv2.cvtColor(frame.rgb, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0], mask, [value.bins], [0, 180]).flatten()
    return {"histogram": (hist / hist.sum()).tolist(), "sample_pixels": int(np.count_nonzero(mask))}
