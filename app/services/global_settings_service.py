"""Global user settings persistence and helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any

from app.config import get_settings
from app.storage.json_store import JsonFileStore


DEFAULT_SCHEDULED_START_TIME = "09:59:58"
DEFAULT_PREVIEW_CONCURRENCY = 2
DEFAULT_PREVIEW_CONCURRENCY_TIME = "09:59:59"
DEFAULT_TICKET_POOL_SIZE = 20
DEFAULT_TICKET_POOL_DRAIN_INTERVAL_MS = 500
DEFAULT_STOCK_MONITOR_ENABLED = False


@dataclass
class GlobalSettings:
    """User-editable global defaults for account execution."""

    scheduled_start_time: str = DEFAULT_SCHEDULED_START_TIME
    preview_concurrency: int = DEFAULT_PREVIEW_CONCURRENCY
    preview_concurrency_time: str = DEFAULT_PREVIEW_CONCURRENCY_TIME
    ticket_pool_size: int = DEFAULT_TICKET_POOL_SIZE
    ticket_pool_drain_interval_ms: int = DEFAULT_TICKET_POOL_DRAIN_INTERVAL_MS
    stock_monitor_enabled: bool = DEFAULT_STOCK_MONITOR_ENABLED
    auto_probe_on_import: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GlobalSettings":
        return cls(
            scheduled_start_time=str(data.get("scheduled_start_time") or DEFAULT_SCHEDULED_START_TIME),
            preview_concurrency=max(1, min(4, int(data.get("preview_concurrency") or DEFAULT_PREVIEW_CONCURRENCY))),
            preview_concurrency_time=str(data.get("preview_concurrency_time") or DEFAULT_PREVIEW_CONCURRENCY_TIME),
            ticket_pool_size=max(0, int(data.get("ticket_pool_size") or DEFAULT_TICKET_POOL_SIZE)),
            ticket_pool_drain_interval_ms=max(0, int(data.get("ticket_pool_drain_interval_ms") or DEFAULT_TICKET_POOL_DRAIN_INTERVAL_MS)),
            stock_monitor_enabled=bool(data.get("stock_monitor_enabled", False)),
            auto_probe_on_import=bool(data.get("auto_probe_on_import", True)),
        )


class GlobalSettingsService:
    """Persist global settings to a JSON file in the data directory."""

    def __init__(self) -> None:
        path = get_settings().data_dir / "settings.json"
        self._store = JsonFileStore(path, default_factory=GlobalSettings().to_dict)

    def get(self) -> GlobalSettings:
        data = self._store.read()
        return GlobalSettings.from_dict(data if isinstance(data, dict) else {})

    def update(self, updates: dict[str, Any]) -> GlobalSettings:
        def updater(data: Any) -> dict[str, Any]:
            current = GlobalSettings.from_dict(data if isinstance(data, dict) else {})
            merged = {**current.to_dict(), **updates}
            return GlobalSettings.from_dict(merged).to_dict()

        self._store.update(updater)
        return self.get()


@lru_cache(maxsize=1)
def get_global_settings_service() -> GlobalSettingsService:
    return GlobalSettingsService()
