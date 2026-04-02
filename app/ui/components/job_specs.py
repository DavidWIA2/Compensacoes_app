from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


DisconnectCallback = Callable[[], None]
StopCallback = Callable[[], None]
CancelCallback = Callable[[], None]
TrackCallback = Callable[[object], None]


@dataclass(frozen=True)
class BlockingJobSpec:
    busy_message: str
    operation: Callable[[], Any]
    total: Optional[int] = None
    cancellable: bool = False
    cancel_callback: Optional[CancelCallback] = None
    success_message: str = "Pronto"
    failure_message: str = "Operacao interrompida."
    name: str = ""


@dataclass
class BackgroundJobSpec:
    name: str
    worker: object
    disconnect_callbacks: list[DisconnectCallback] = field(default_factory=list)
    stop_callback: Optional[StopCallback] = None
    wait_ms: int = 1000
    busy_message: Optional[str] = None
    total: Optional[int] = None
    cancellable: bool = False
    cancel_callback: Optional[CancelCallback] = None
    on_tracked: Optional[TrackCallback] = None
    auto_start: bool = True


def build_disconnect_callback(signal: Any, handler: Any) -> DisconnectCallback:
    def _disconnect() -> None:
        signal.disconnect(handler)

    return _disconnect
