from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def merge_resume_data(path: str | Path, updates: dict[str, Any]) -> dict[str, Any]:
    file_path = Path(path)
    current: dict[str, Any] = {}
    if file_path.exists():
        current = json.loads(file_path.read_text(encoding="utf-8"))
    current.update(updates)
    file_path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return current
