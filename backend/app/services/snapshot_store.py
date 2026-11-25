from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np

from app.errors import DomainError
from app.persistence.database import Database
from app.services.config_store import atomic_json
from app.sources.file import FileSource


class SnapshotStore:
    def __init__(self, root: Path, db: Database):
        self.root, self.db = root.resolve(), db

    def media(self, path: Path, content_type: str):
        identifier = uuid4().hex
        relative = path.resolve().relative_to(self.root).as_posix()
        self.db.save("media", identifier, {"path": relative, "content_type": content_type})
        return f"/api/v1/media/{identifier}"

    def image(self, directory: Path, name: str, array: np.ndarray):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        ok, encoded = cv2.imencode(path.suffix, array)
        if not ok:
            raise DomainError("SNAPSHOT_WRITE_FAILED", "Could not encode inspection image", 500)
        encoded.tofile(path)
        return self.media(path, "image/png" if path.suffix == ".png" else "image/jpeg")

    def save_frame(self, frame):
        directory = self.root / "captures" / frame.id
        urls = {"rgb": self.image(directory, "rgb.png", frame.rgb)}
        if frame.depth is not None:
            # Preserve exact raw values, including float depth maps, without quantization.
            np.save(directory / "depth.npy", frame.depth, allow_pickle=False)
            urls["depth_raw"] = self.media(directory / "depth.npy", "application/octet-stream")
            atomic_json(directory / "metadata.json", frame.metadata.model_dump())
            urls["metadata"] = self.media(directory / "metadata.json", "application/json")
        record = {
            **frame.public(),
            "image_urls": urls,
            "directory": directory.relative_to(self.root).as_posix(),
        }
        self.db.save("frame", frame.id, record)
        return record

    def load_frame(self, identifier):
        record = self.db.get("frame", identifier)
        folder = self.root / record["directory"]
        frame = FileSource(
            folder / "rgb.png",
            folder / "depth.npy" if record["capabilities"]["depth"] else None,
            folder / "metadata.json" if record["capabilities"]["depth"] else None,
        ).read()
        frame.id, frame.source, frame.captured_at = record["id"], record["source"], record["captured_at"]
        return frame

    def resolve_media(self, identifier):
        record = self.db.get("media", identifier)
        path = (self.root / record["path"]).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            raise DomainError("MEDIA_NOT_FOUND", "Snapshot file is unavailable", 404)
        return path, record["content_type"]
