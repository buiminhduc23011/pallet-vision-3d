"""Generate public contracts from the installed app. No camera/model is started."""

import json
from pathlib import Path

from app.main import create_app
from app.schemas.config import AppConfig


def export():
    root = Path(__file__).resolve().parents[1]
    contracts = {
        root / "config.schema.json": AppConfig.model_json_schema(),
        root / "docs" / "openapi.json": create_app().openapi(),
    }
    for path, data in contracts.items():
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    print("Exported config.schema.json and docs/openapi.json")


if __name__ == "__main__":
    export()
