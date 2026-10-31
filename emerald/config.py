"""Paths and runtime settings. Everything is overridable by environment variable."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PASSAGES = ROOT / "sources" / "passages.jsonl"


def _load_env_file() -> None:
    """Optional local settings, such as a non-default OLLAMA_HOST or EMERALD_LEDGER_BUCKET. Git-ignored."""
    file = ROOT / ".env"
    if file.exists():
        for line in file.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


_load_env_file()


def data_dir() -> Path:
    path = Path(os.environ.get("EMERALD_DATA", ROOT / "data"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "emerald.db"


def device_id() -> str:
    return os.environ.get("EMERALD_DEVICE", "field-kit-01")


def lane() -> str:
    """'cloud' uses Amazon Bedrock, 'offline' uses a local Ollama model. Same graph, same tools."""
    return os.environ.get("EMERALD_LANE", "cloud")
