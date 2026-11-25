import json
import os
from pathlib import Path
from threading import RLock
from uuid import uuid4

from app.errors import DomainError
from app.schemas.config import AppConfig


def atomic_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class ConfigStore:
    def __init__(self, path: Path):
        self.path, self.lock = path, RLock()
        self.value = (
            AppConfig.model_validate_json(path.read_text(encoding="utf-8-sig"))
            if path.exists()
            else AppConfig()
        )

    def get(self):
        with self.lock:
            return self.value.model_copy(deep=True)

    def put(self, value: AppConfig, revision: int):
        with self.lock:
            if revision != self.value.revision:
                raise DomainError("STALE_CONFIG", "Configuration changed; reload settings", 412)
            value = value.model_copy(update={"revision": self.value.revision + 1}, deep=True)
            atomic_json(self.path, value.model_dump())
            self.value = value
            return self.get()
