from __future__ import annotations

import json
from pathlib import Path

from app.main import app

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "docs" / "openapi.json"


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    schema = app.openapi()
    OUTPUT_PATH.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    print(f"Wrote OpenAPI schema to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
