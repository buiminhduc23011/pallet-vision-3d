import asyncio
import json
import shutil
import struct
from pathlib import Path
from typing import Literal
from uuid import uuid4

import cv2
from fastapi import (
    APIRouter,
    File,
    Header,
    Query,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import Field

from app.errors import DomainError
from app.schemas.config import AppConfig, ROI, StrictModel
from app.sources.file import FileSource
from app.vision.calibration import fit_floor
from app.vision.overlays import depth_image

router = APIRouter(prefix="/api/v1")


class SessionCreate(StrictModel):
    mode: Literal["live", "offline"]
    asset_id: str | None = None
    camera_serial: str | None = None


class SessionUpdate(StrictModel):
    playback: Literal["playing", "paused"] | None = None
    seek_seconds: float | None = Field(default=None, ge=0)
    reference_id: str | None = None
    continuous: bool | None = None


class PinRequest(StrictModel):
    frame_id: str | None = None


class InspectionRequest(StrictModel):
    frame_id: str
    config_revision: int
    session_id: str | None = None


class ReferenceRequest(StrictModel):
    inspection_id: str
    label: str = Field(default="Reference pallet", max_length=120)
    session_id: str | None = None


class VerificationRequest(StrictModel):
    reference_id: str
    inspection_id: str
    session_id: str | None = None


class CaptureRequest(StrictModel):
    frame_id: str


class CalibrationRequest(StrictModel):
    frame_id: str
    roi: ROI


@router.get("/health")
def health(request: Request):
    return request.app.state.engine.health()


@router.get("/config", response_model=AppConfig)
def get_config(request: Request, response: Response):
    config = request.app.state.engine.config.get()
    response.headers["ETag"] = f'"{config.revision}"'
    return config


@router.put("/config")
def put_config(value: AppConfig, request: Request, response: Response, if_match: str = Header()):
    engine = request.app.state.engine
    try:
        revision = int(if_match.strip('"'))
    except ValueError as exc:
        raise DomainError("INVALID_ETAG", "If-Match must contain the configuration revision") from exc
    # Validate trusted location even when the weights have not yet been installed.
    path = (engine.pipeline.model_root / value.detector.model_path).resolve()
    if not path.is_relative_to(engine.pipeline.model_root.resolve()):
        raise DomainError("UNTRUSTED_MODEL_PATH", "Model path must stay inside models/")
    if engine.pending:
        raise DomainError("PROCESSING_BUSY", "Wait for current processing before changing settings", 409)
    saved = engine.config.put(value, revision)
    response.headers["ETag"] = f'"{saved.revision}"'
    jobs = engine.reprocess()
    engine.emit("config.applied", {"revision": saved.revision, "job_ids": jobs})
    return {"config": saved.model_dump(), "reprocessing_job_ids": jobs}


@router.post("/assets", status_code=201)
async def upload_asset(
    request: Request,
    rgb: UploadFile | None = File(None),
    depth: UploadFile | None = File(None),
    metadata: UploadFile | None = File(None),
    bag: UploadFile | None = File(None),
):
    engine = request.app.state.engine
    engine.require_storage()
    if (bag and any((rgb, depth, metadata))) or (not bag and not rgb):
        raise DomainError("INVALID_UPLOAD", "Upload either RGB with optional depth/metadata, or one .bag")
    if bool(depth) != bool(metadata):
        raise DomainError("DEPTH_METADATA_REQUIRED", "Depth and metadata JSON must be provided together")
    identifier = uuid4().hex
    directory = engine.root / "uploads" / identifier
    directory.mkdir(parents=True)
    total = 0
    paths = {}
    try:
        for key, upload, allowed in (
            ("rgb", rgb, (".jpg", ".jpeg", ".png")),
            ("depth", depth, (".png", ".npy")),
            ("metadata", metadata, (".json",)),
            ("bag", bag, (".bag",)),
        ):
            if upload is None:
                continue
            suffix = Path(upload.filename or "").suffix.lower()
            if suffix not in allowed:
                raise DomainError("UNSUPPORTED_FILE", f"Unsupported {key} file extension")
            name = "recording.bag" if key == "bag" else f"{key}{suffix}"
            path = directory / name
            with path.open("wb") as destination:
                while block := await upload.read(1024 * 1024):
                    total += len(block)
                    if total > engine.config.get().runtime.max_upload_mb * 1024 * 1024:
                        raise DomainError("UPLOAD_TOO_LARGE", "Upload exceeds configured size limit", 413)
                    engine.require_storage(len(block))
                    destination.write(block)
            paths[key] = name
            await upload.close()
        if bag:
            # Validate recording through the actual SDK; never pretend a bag is an image.
            source = await asyncio.to_thread(
                FileSource, directory / paths["bag"], runtime=engine.config.get().runtime
            )
            try:
                frame = await asyncio.to_thread(source.read)
            finally:
                await asyncio.to_thread(source.close)
            if frame is None:
                raise DomainError("EMPTY_RECORDING", "Recording has no aligned frames")
        else:
            source = await asyncio.to_thread(
                FileSource,
                directory / paths["rgb"],
                directory / paths["depth"] if depth else None,
                directory / "metadata.json" if metadata else None,
                engine.config.get().runtime,
            )
            frame = source.read()
        result = {
            "id": identifier,
            "kind": "bag" if bag else "image",
            "name": (bag or rgb).filename,
            "directory": directory.relative_to(engine.root).as_posix(),
            **paths,
            "capabilities": frame.public()["capabilities"],
            "warnings": [],
        }
        engine.db.save("asset", identifier, result)
        return result
    except Exception:
        # Only remove this request's UUID upload directory on validation failure.
        if directory.parent == engine.root / "uploads":
            shutil.rmtree(directory)
        raise


@router.get("/assets/{identifier}")
def get_asset(identifier: str, request: Request):
    value = request.app.state.engine.db.get("asset", identifier)
    return {k: v for k, v in value.items() if k != "directory"}


@router.post("/sessions", status_code=201)
def create_session(value: SessionCreate, request: Request):
    return request.app.state.engine.open_session(value.mode, value.asset_id, value.camera_serial)


@router.get("/sessions/{identifier}")
def session(identifier: str, request: Request):
    return request.app.state.engine.session_state(identifier)


@router.patch("/sessions/{identifier}")
def update_session(identifier: str, value: SessionUpdate, request: Request):
    return request.app.state.engine.patch_session(identifier, value.model_dump(exclude_unset=True))


@router.delete("/sessions/{identifier}", status_code=204)
def delete_session(identifier: str, request: Request):
    engine = request.app.state.engine
    engine.session_state(identifier)
    engine.close_session()


@router.post("/sessions/{identifier}/reset")
def reset_session(identifier: str, request: Request):
    engine = request.app.state.engine
    engine.session_state(identifier)
    if engine.pending:
        raise DomainError("PROCESSING_BUSY", "Wait for pinned jobs to finish before resetting", 409)
    with engine.lock:
        engine.session.update(reference_id=None, inspection_id=None, verification_id=None, continuous=False)
    engine.emit("session.state", engine.session_state())
    return engine.session_state()


@router.post("/sessions/{identifier}/frames", status_code=201)
def pin(identifier: str, value: PinRequest, request: Request):
    return request.app.state.engine.pin(identifier, value.frame_id)


@router.post("/inspections", status_code=202)
def inspect(value: InspectionRequest, request: Request):
    engine = request.app.state.engine
    config = engine.config.get()
    if value.config_revision != config.revision:
        raise DomainError("STALE_CONFIG", "Reload the current configuration", 409)
    engine.db.get("frame", value.frame_id)
    return engine.submit("inspection", lambda: engine.inspect(value.frame_id, config, value.session_id))


@router.get("/inspections/{identifier}")
def get_inspection(identifier: str, request: Request):
    return request.app.state.engine.db.get("inspection", identifier)


@router.post("/references", status_code=201)
def capture_reference(value: ReferenceRequest, request: Request):
    return request.app.state.engine.reference(value.inspection_id, value.label, value.session_id)


@router.get("/references/{identifier}")
def get_reference(identifier: str, request: Request):
    return request.app.state.engine.db.get("reference", identifier)


@router.post("/verifications", status_code=202)
def verify(value: VerificationRequest, request: Request):
    engine = request.app.state.engine
    engine.db.get("reference", value.reference_id)
    engine.db.get("inspection", value.inspection_id)
    return engine.submit(
        "verification", lambda: engine.verify(value.reference_id, value.inspection_id, value.session_id)
    )


@router.get("/verifications/{identifier}")
def get_verification(identifier: str, request: Request):
    return request.app.state.engine.db.get("verification", identifier)


@router.post("/calibrations", status_code=202)
def calibration(value: CalibrationRequest, request: Request):
    engine = request.app.state.engine
    config = engine.config.get()

    def run():
        result = fit_floor(engine.store.load_frame(value.frame_id), value.roi, config)
        result.update(id=uuid4().hex, frame_id=value.frame_id, config_revision=config.revision)
        engine.db.save("calibration", result["id"], result)
        return result

    return engine.submit("calibration", run)


@router.get("/calibrations/{identifier}")
def get_calibration(identifier: str, request: Request):
    return request.app.state.engine.db.get("calibration", identifier)


@router.post("/captures", status_code=201)
def capture(value: CaptureRequest, request: Request):
    return request.app.state.engine.db.get("frame", value.frame_id)


@router.get("/jobs/{identifier}")
def job(identifier: str, request: Request):
    return request.app.state.engine.db.get("job", identifier)


@router.get("/history")
def history(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
    verdict: Literal["PASS", "FAIL", "INCOMPLETE"] | None = None,
    source: str | None = None,
):
    return request.app.state.engine.db.history(limit, cursor, verdict, source)


@router.get("/history/{identifier}")
def history_item(identifier: str, request: Request):
    return request.app.state.engine.db.get("verification", identifier)


@router.get("/media/{identifier}")
def media(identifier: str, request: Request):
    path, content_type = request.app.state.engine.store.resolve_media(identifier)
    return FileResponse(
        path,
        media_type=content_type,
        filename=path.name,
        content_disposition_type="inline" if content_type.startswith("image/") else "attachment",
        headers={"X-Content-Type-Options": "nosniff"},
    )


def allowed_origin(origin):
    from urllib.parse import urlparse

    if not origin:
        return True  # local command-line clients have no browser Origin
    parsed = urlparse(origin)
    return (
        parsed.scheme in ("http", "https")
        and parsed.hostname in ("127.0.0.1", "localhost", "::1")
        and parsed.port in (None, 8000, 5173, 4173)
    )


@router.websocket("/sessions/{identifier}/events")
async def events(socket: WebSocket, identifier: str):
    if not allowed_origin(socket.headers.get("origin")):
        await socket.close(code=1008)
        return
    engine = socket.app.state.engine
    try:
        state = engine.session_state(identifier)
    except DomainError:
        await socket.close(code=1008)
        return
    await socket.accept()
    sequence = state["sequence"]
    await socket.send_json(
        {"schema_version": 1, "type": "session.state", "sequence": sequence, "payload": state}
    )
    try:
        while True:
            engine.session_state(identifier)
            with engine.lock:
                pending = [
                    e for e in engine.events if e["sequence"] > sequence and e["session_id"] == identifier
                ]
            for event in pending:
                await socket.send_json(event)
                sequence = event["sequence"]
            if not pending:
                await socket.send_json(
                    {"type": "heartbeat", "sequence": sequence, "payload": engine.session_state(identifier)}
                )
            await asyncio.sleep(0.5)
    except (WebSocketDisconnect, DomainError, RuntimeError):
        return


def preview(engine, identifier, view):
    state = engine.session_state(identifier)
    with engine.lock:
        frame = engine.latest
    if frame is None:
        return None
    cfg = engine.config.get()
    image = frame.rgb if view != "depth" else depth_image(frame, cfg)
    # Annotated image is pinned: never combine an old overlay with a new frame.
    if view == "annotated" and state["inspection_id"]:
        inspection = engine.db.get("inspection", state["inspection_id"])
        path, _ = engine.store.resolve_media(inspection["image_urls"]["annotated"].split("/")[-1])
        return {
            "frame_id": inspection["frame_id"],
            "width": inspection["frame"]["width"],
            "height": inspection["frame"]["height"],
            "config_revision": inspection["config_revision"],
            "pinned": True,
        }, path.read_bytes()
    if image is None:
        return None
    ok, data = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, cfg.runtime.jpeg_quality])
    if not ok:
        return None
    return {
        "frame_id": frame.id,
        "width": image.shape[1],
        "height": image.shape[0],
        "config_revision": cfg.revision,
        "pinned": False,
    }, data.tobytes()


@router.websocket("/sessions/{identifier}/frames")
async def frames(socket: WebSocket, identifier: str, view: Literal["rgb", "depth", "annotated"] = "rgb"):
    if not allowed_origin(socket.headers.get("origin")):
        await socket.close(code=1008)
        return
    await socket.accept()
    engine = socket.app.state.engine
    try:
        while True:
            item = await asyncio.to_thread(preview, engine, identifier, view)
            if item:
                metadata, jpeg = item
                header = json.dumps({"schema_version": 1, **metadata}).encode()
                await socket.send_bytes(struct.pack(">I", len(header)) + header + jpeg)
            await asyncio.sleep(1 / engine.config.get().runtime.stream_fps)
    except (WebSocketDisconnect, DomainError, RuntimeError):
        return


@router.get("/sessions/{identifier}/stream.mjpg")
async def mjpeg(identifier: str, request: Request, view: Literal["rgb", "depth", "annotated"] = "rgb"):
    engine = request.app.state.engine
    engine.session_state(identifier)

    async def stream():
        while not await request.is_disconnected():
            try:
                item = await asyncio.to_thread(preview, engine, identifier, view)
            except DomainError:
                break
            if item:
                metadata, data = item
                yield (
                    f"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: {len(data)}\r\nX-Frame-Id: {metadata['frame_id']}\r\n\r\n".encode()
                    + data
                    + b"\r\n"
                )
            await asyncio.sleep(1 / engine.config.get().runtime.stream_fps)

    return StreamingResponse(stream(), media_type="multipart/x-mixed-replace; boundary=frame")
