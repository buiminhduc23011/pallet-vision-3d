from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

import numpy as np

from app.schemas.config import DepthMetadata


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class FrameBundle:
    rgb: np.ndarray  # OpenCV BGR, uint8, H x W x 3
    source: str
    depth: np.ndarray | None = None
    metadata: DepthMetadata | None = None
    id: str = field(default_factory=lambda: uuid4().hex)
    captured_at: str = field(default_factory=utcnow)

    def public(self):
        h, w = self.rgb.shape[:2]
        return {
            "id": self.id,
            "source": self.source,
            "captured_at": self.captured_at,
            "width": w,
            "height": h,
            "capabilities": {
                "rgb": True,
                "depth": self.depth is not None,
                "metric": self.depth is not None and self.metadata is not None,
            },
        }


class FrameSource(ABC):
    @abstractmethod
    def read(self) -> FrameBundle | None:
        """Return real data, or None at end of a recording. Never fabricate frames."""

    @abstractmethod
    def close(self) -> None: ...
