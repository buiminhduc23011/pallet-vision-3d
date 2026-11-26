"""Single-workstation orchestration. Camera and inference have separate owners."""

import json
import logging
import shutil
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np

from app.errors import DomainError
from app.persistence.database import Database
from app.schemas.config import AppConfig
from app.services.config_store import ConfigStore
from app.services.snapshot_store import SnapshotStore
from app.sources.base import utcnow
from app.sources.file import FileSource
from app.sources.realsense import RealSenseSource, camera_status
from app.vision.overlays import depth_image, draw_overlay
from app.vision.pipeline import VisionPipeline
from app.vision.transfer_qc import compare_rolls

logger = logging.getLogger("pallet.engine")


class Engine:
    def __init__(self, root: Path, config_path: Path, model_root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.config = ConfigStore(config_path)
        self.db = Database(self.root / "inspections.sqlite3")
        self.store = SnapshotStore(self.root, self.db)
        self.pipeline = VisionPipeline(model_root)
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vision")
        self.lock = threading.RLock()
        self.source_lock = threading.RLock()
        self.session = None
        self.source = None
        self.latest = None
        self.source_thread = None
        self.stop_event = threading.Event()
        self.pending = 0
        self.events = deque(maxlen=256)
        self.sequence = 0
        self.last_error = None
        self.last_continuous = 0.0
        self.closing = False
        self.camera = camera_status()

    def emit(self, event_type, payload, frame_id=None):
        with self.lock:
            self.sequence += 1
            self.events.append(
                {
                    "schema_version": 1,
                    "type": event_type,
                    "sequence": self.sequence,
                    "session_id": self.session["id"] if self.session else None,
                    "frame_id": frame_id,
                    "config_revision": self.config.get().revision,
                    "timestamp": utcnow(),
                    "payload": payload,
                }
            )

    def health(self):
        config = self.config.get()
        return {
            "status": "degraded" if self.last_error else "ready",
            "camera": self.camera,
            "default_mode": "live" if self.camera["devices"] else "offline",
            "detector": {
                "backend": config.detector.backend,
                "loaded": self.pipeline.detector is not None,
                "model_present": (self.pipeline.model_root / config.detector.model_path).is_file()
                or (self.pipeline.model_root / config.detector.model_path).is_dir(),
            },
            "pending_jobs": self.pending,
            "last_error": self.last_error,
            "version": "0.1.0",
            "free_disk_mb": int(shutil.disk_usage(self.root).free / 1024 / 1024),
        }

    def require_storage(self, reserved_bytes=0):
        if (
            shutil.disk_usage(self.root).free - reserved_bytes
            < self.config.get().runtime.minimum_free_disk_mb * 1024 * 1024
        ):
            raise DomainError(
                "STORAGE_LOW", "Not enough free disk space; archive existing captures before continuing", 503
            )

    def session_state(self, identifier=None):
        with self.lock:
            if not self.session or (identifier and identifier != self.session["id"]):
                raise DomainError("SESSION_NOT_FOUND", "Inspection session no longer exists", 404)
            return {
                **self.session,
                "frame": self.latest.public() if self.latest else None,
                "pending_jobs": self.pending,
                "sequence": self.sequence,
            }

    def open_session(self, mode, asset_id=None, serial=None):
        if mode == "offline" and asset_id:
            asset = self.db.get("asset", asset_id)
            folder = self.root / asset["directory"]
            if asset["kind"] == "bag":
                source = FileSource(folder / "recording.bag", runtime=self.config.get().runtime)
            else:
                source = FileSource(
                    folder / asset["rgb"],
                    folder / asset["depth"] if asset.get("depth") else None,
                    folder / "metadata.json" if asset.get("depth") else None,
                    self.config.get().runtime,
                )
        elif mode == "live":
            self.camera = camera_status()
            if self.session and self.session["mode"] == "live":
                raise DomainError("CAMERA_BUSY", "Close the active live session before reconnecting", 409)
            source = RealSenseSource(self.config.get().runtime, serial=serial)
        else:
            source = None
        try:
            first = source.read() if source else None
            if source and first is None:
                raise DomainError("EMPTY_RECORDING", "Recording contains no aligned RGB-D frames")
        except Exception:
            if source:
                source.close()
            raise
        self.close_session()
        with self.lock:
            self.source, self.latest = source, first
            self.stop_event = threading.Event()
            self.session = {
                "id": uuid4().hex,
                "mode": mode,
                "asset_id": asset_id,
                "status": "ready",
                "playback": "paused" if mode == "offline" else "playing",
                "continuous": False,
                "reference_id": None,
                "inspection_id": None,
                "verification_id": None,
            }
        if source and (not isinstance(source, FileSource) or source.recording):
            self.source_thread = threading.Thread(target=self.acquire, name="camera-acquisition", daemon=True)
            self.source_thread.start()
        self.emit("session.state", self.session_state())
        return self.session_state()

    def close_session(self):
        self.stop_event.set()
        if self.source_thread:
            self.source_thread.join(timeout=self.config.get().runtime.frame_timeout_ms / 1000 + 2)
            if self.source_thread.is_alive():
                raise DomainError("SOURCE_STOP_TIMEOUT", "Camera is still stopping; retry shortly", 503)
            self.source_thread = None
        with self.source_lock:
            if self.source:
                self.source.close()
            self.source = None
        with self.lock:
            self.session, self.latest = None, None

    def acquire(self):
        while not self.stop_event.is_set():
            if not self.session or self.session["playback"] == "paused":
                self.stop_event.wait(0.05)
                continue
            try:
                with self.source_lock:
                    frame = self.source.read()
                if frame is None:
                    with self.lock:
                        self.session.update(status="eof", playback="paused")
                    self.emit("session.state", self.session_state())
                    continue
                with self.lock:
                    self.latest = frame
                self.maybe_continuous()
                self.stop_event.wait(1 / self.config.get().runtime.stream_fps)
            except Exception as exc:
                error = (
                    exc.public()
                    if isinstance(exc, DomainError)
                    else {"code": "SOURCE_FAILED", "message": "Source acquisition failed"}
                )
                logger.exception(json.dumps({"event": "source.failed", "code": error["code"]}))
                with self.lock:
                    self.last_error = error
                    if self.session:
                        self.session.update(status="disconnected", playback="paused", continuous=False)
                    self.latest = None  # stale camera data must never become a new capture
                self.db.save("failure", uuid4().hex, {"created_at": utcnow(), "error": error})
                self.emit("source.disconnected", error)
                break

    def maybe_continuous(self):
        config = self.config.get()
        with self.lock:
            if (
                not self.session
                or not self.session["continuous"]
                or self.pending
                or time.monotonic() - self.last_continuous < config.runtime.continuous_interval_seconds
            ):
                return
            reference_id = self.session["reference_id"]
            if not reference_id:
                return
            frame = self.latest
            session_id = self.session["id"]
            self.last_continuous = time.monotonic()

        def run():
            self.ensure_saved(frame)
            inspection = self.inspect(frame.id, config, session_id)
            return self.verify(reference_id, inspection["id"], session_id)

        self.submit("continuous_verification", run)

    def patch_session(self, identifier, updates):
        self.session_state(identifier)
        if updates.get("reference_id"):
            reference = self.db.get("reference", updates["reference_id"])
            if reference["config_revision"] != self.config.get().revision:
                raise DomainError(
                    "STALE_REFERENCE", "Reprocess reference with current settings before activation", 409
                )
        if "seek_seconds" in updates:
            with self.source_lock:
                if not isinstance(self.source, FileSource) or not self.source.recording:
                    raise DomainError("NOT_A_RECORDING", "Only bag recordings support seeking")
                self.source.seek(updates.pop("seek_seconds"))
                frame = self.source.read()
                if frame is not None:
                    self.latest = frame
            updates["status"] = "ready"
        if updates.get("continuous") and not (updates.get("reference_id") or self.session["reference_id"]):
            raise DomainError("REFERENCE_REQUIRED", "Capture a reference before continuous verification", 409)
        teaching = self.config.get().teaching
        if updates.get("continuous") and teaching and teaching.require_origin_confirmation:
            raise DomainError(
                "MANUAL_ORIGIN_REQUIRED",
                "This setup requires origin confirmation on each pinned frame; use manual inspections",
                409,
            )
        with self.lock:
            self.session.update(updates)
        self.emit("session.state", self.session_state())
        return self.session_state()

    def ensure_saved(self, frame):
        try:
            return self.db.get("frame", frame.id)
        except DomainError as exc:
            if exc.status != 404:
                raise
        self.require_storage(frame.rgb.nbytes + (frame.depth.nbytes if frame.depth is not None else 0))
        return self.store.save_frame(frame)

    def pin(self, session_id, frame_id=None):
        self.session_state(session_id)
        with self.lock:
            frame = self.latest
            if frame is None or self.session["status"] == "disconnected":
                raise DomainError("NO_FRAME", "Load an image or connect a camera first", 409)
            if frame_id and frame_id != frame.id:
                raise DomainError(
                    "FRAME_EXPIRED", "Requested preview frame has expired; pin the current frame", 409
                )
            # Saving while lock held prevents duplicate pin races, not acquisition reads.
            return self.ensure_saved(frame)

    def submit(self, operation, function):
        with self.lock:
            if self.closing or self.pending >= self.config.get().runtime.max_pending_jobs:
                raise DomainError("WORKER_BUSY", "Inference queue is full; retry shortly", 503)
            self.pending += 1
        identifier = uuid4().hex
        job = {
            "id": identifier,
            "operation": operation,
            "status": "queued",
            "created_at": utcnow(),
            "result": None,
            "error": None,
        }
        self.db.save("job", identifier, job)

        def run():
            job["status"] = "running"
            self.db.save("job", identifier, job, update=True)
            try:
                job["result"] = function()
                job["status"] = "succeeded"
            except Exception as exc:
                job["status"] = "failed"
                job["error"] = (
                    exc.public()
                    if isinstance(exc, DomainError)
                    else {"code": "PROCESSING_FAILED", "message": "Processing failed; inspect server logs"}
                )
                self.last_error = job["error"]
                with self.lock:
                    if self.session:
                        self.session["continuous"] = False
                logger.exception(
                    json.dumps(
                        {
                            "event": "job.failed",
                            "job_id": identifier,
                            "operation": operation,
                            "code": job["error"]["code"],
                        }
                    )
                )
                self.emit("job.failed", {"job_id": identifier, "error": job["error"]})
            finally:
                job["finished_at"] = utcnow()
                self.db.save("job", identifier, job, update=True)
                with self.lock:
                    self.pending -= 1

        self.worker.submit(run)
        return {"job_id": identifier, "status": "queued", "status_url": f"/api/v1/jobs/{identifier}"}

    def inspect(self, frame_id, config: AppConfig, session_id=None, origin=None):
        self.require_storage()
        frame = self.store.load_frame(frame_id)
        result, masks = self.pipeline.inspect(frame, config, origin)
        identifier = uuid4().hex
        result["id"] = identifier
        folder = self.root / "inspections" / identifier
        urls = dict(self.db.get("frame", frame_id)["image_urls"])
        urls["annotated"] = self.store.image(folder, "annotated.jpg", draw_overlay(frame.rgb, result, masks))
        depth = depth_image(frame, config)
        if depth is not None:
            urls["depth"] = self.store.image(folder, "depth.jpg", depth)
        for i, mask in enumerate(masks):
            result["rolls"][i]["mask_url"] = self.store.image(folder, f"mask-{i}.png", mask)
        result["image_urls"] = urls
        self.db.save("inspection", identifier, result)
        with self.lock:
            if (
                self.session
                and self.session["id"] == session_id
                and config.revision == self.config.get().revision
            ):
                self.session.update(inspection_id=identifier, verification_id=None)
                self.emit("inspection.completed", {"inspection_id": identifier}, frame_id)
        return result

    def reference(self, inspection_id, label, session_id=None):
        inspection = self.db.get("inspection", inspection_id)
        if inspection["config_snapshot"].get("teaching") and inspection["alignment"]["status"] != "OK":
            raise DomainError(
                "REFERENCE_NOT_ALIGNED", "A taught reference must pass alignment, size and origin checks", 409
            )
        if inspection["state"] != "COMPLETE" or not inspection["rolls"]:
            raise DomainError(
                "REFERENCE_INCOMPLETE",
                "Reference needs a visible pallet and valid roll segmentation/calibration",
                409,
            )
        identifier = uuid4().hex
        result = {
            **inspection,
            "id": identifier,
            "inspection_id": inspection_id,
            "label": label,
            "created_at": utcnow(),
        }
        self.db.save("reference", identifier, result)
        with self.lock:
            if (
                self.session
                and self.session["id"] == session_id
                and result["config_revision"] == self.config.get().revision
            ):
                self.session["reference_id"] = identifier
        return result

    def verify(self, reference_id, inspection_id, session_id=None):
        reference, current = self.db.get("reference", reference_id), self.db.get("inspection", inspection_id)
        config = AppConfig.model_validate(current["config_snapshot"])
        unit = "mm" if current["scope"] == "RGBD" else "px"
        compatible = (
            reference["scope"] == current["scope"]
            and reference["config_snapshot"] == current["config_snapshot"]
            and reference["model_fingerprint"] == current["model_fingerprint"]
        )
        if not compatible:
            raise DomainError(
                "INCOMPATIBLE_REFERENCE",
                "Reference and target must use the same scope, settings and model; reprocess the reference",
                409,
            )
        result = compare_rolls(reference["rolls"], current["rolls"], config.matching, unit)
        if current["state"] != "COMPLETE":
            result["verdict"] = "INCOMPLETE"
            result["reasons"].append("CURRENT_INSPECTION_INCOMPLETE")
        if config.teaching:
            from app.vision.teaching import enforce_alignment

            enforce_alignment(result, current["alignment"])
        if reference["pallet"] and current["pallet"]:
            a = reference["pallet"]["width_px"] / reference["pallet"]["height_px"]
            b = current["pallet"]["width_px"] / current["pallet"]["height_px"]
            if abs(b - a) / a * 100 > config.matching.pallet_aspect_tolerance_percent:
                result["verdict"] = "INCOMPLETE"
                result["reasons"].append("INCOMPATIBLE_PALLET_VIEW")
        identifier = uuid4().hex
        result.update(
            id=identifier,
            reference_id=reference_id,
            inspection_id=inspection_id,
            frame_id=current["frame_id"],
            created_at=utcnow(),
            source=current["source"],
            scope=current["scope"],
            config_revision=config.revision,
            unit=unit,
        )
        # Expected 2D boxes in target image, independent of actual target detections.
        pallet = current["pallet"]
        for missing in result["missing"]:
            if missing.get("local_box") is not None and pallet and unit == "px":
                local = (
                    np.asarray(missing["local_box"])
                    * pallet["width_px"]
                    / config.matching.canonical_pallet_width_px
                )
                missing["expected_box"] = (
                    local @ np.asarray(pallet["basis"]) + pallet.get("local_origin", pallet["center"])
                ).tolist()
            elif missing.get("local_box") is not None and pallet and pallet["metric_transform"]:
                transform = pallet["metric_transform"]
                points = (
                    np.asarray(missing["local_box"]) @ np.asarray(transform["basis"]) + transform["origin"]
                )
                # Project at measured roll height rather than the pallet support plane.
                frame = self.store.load_frame(current["frame_id"])
                intr = frame.metadata.intrinsics
                plane = config.calibration.floor_plane or (0, 0, -1, config.calibration.floor_distance_mm)
                if missing.get("z_height") is not None:
                    points += np.asarray(plane[:3]) * (
                        missing["z_height"] - config.calibration.pallet_height_mm
                    )
                camera_matrix = np.array(
                    [[intr.fx, 0, intr.ppx], [0, intr.fy, intr.ppy], [0, 0, 1]], dtype=float
                )
                if intr.distortion in ("none", "brown_conrady"):
                    projected, _ = cv2.projectPoints(
                        points, np.zeros(3), np.zeros(3), camera_matrix, np.asarray(intr.coeffs)
                    )
                    missing["expected_box"] = projected.reshape(-1, 2).tolist()
        frame = self.store.load_frame(current["frame_id"])
        image = draw_overlay(frame.rgb, current, verification=result)
        for missing in result["missing"]:
            box = missing.get("expected_box")
            if box:
                points = np.asarray(box)
                for a, b in zip(points, np.roll(points, -1, axis=0)):
                    for t in np.arange(0, 1, 0.1):
                        p, q = a + (b - a) * t, a + (b - a) * min(t + 0.05, 1)
                        cv2.line(image, tuple(p.astype(int)), tuple(q.astype(int)), (30, 40, 220), 2)
        result["overlay_url"] = self.store.image(
            self.root / "verifications" / identifier, "overlay.jpg", image
        )
        result["image_urls"] = current["image_urls"]
        result["reference_image_url"] = reference["image_urls"]["rgb"]
        self.db.save("verification", identifier, result)
        with self.lock:
            if (
                self.session
                and self.session["id"] == session_id
                and config.revision == self.config.get().revision
            ):
                self.session["verification_id"] = identifier
                self.emit("verification.completed", {"verification_id": identifier}, current["frame_id"])
        return result

    def reprocess(self):
        with self.lock:
            if not self.session or not self.latest:
                return []
            session_id = self.session["id"]
            reference_id, frame = self.session["reference_id"], self.latest
            self.session.update(inspection_id=None, verification_id=None, continuous=False)
        config = self.config.get()
        self.ensure_saved(frame)

        def run():
            new_reference = None
            if reference_id:
                old = self.db.get("reference", reference_id)
                inspected = self.inspect(old["frame_id"], config, origin=old.get("confirmed_origin"))
                aligned = not config.teaching or inspected["alignment"]["status"] == "OK"
                if inspected["state"] == "COMPLETE" and inspected["rolls"] and aligned:
                    new_reference = self.reference(inspected["id"], old["label"], session_id)
                else:
                    with self.lock:
                        if self.session and self.session["id"] == session_id:
                            self.session["reference_id"] = None
                    self.emit(
                        "reference.invalidated", {"reason": "Reference is incomplete under new settings"}
                    )
            current = self.inspect(frame.id, config, session_id)
            if new_reference:
                self.verify(new_reference["id"], current["id"], session_id)
            return {
                "inspection_id": current["id"],
                "reference_id": new_reference["id"] if new_reference else None,
            }

        return [self.submit("settings_reprocess", run)["job_id"]]

    def close(self):
        self.closing = True
        self.close_session()
        self.worker.shutdown(wait=True, cancel_futures=False)
