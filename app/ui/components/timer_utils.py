from __future__ import annotations

from collections.abc import Callable
import weakref

from PySide6.QtCore import QObject, QTimer


def schedule_owned_single_shot(
    owner: QObject | None,
    delay_ms: int,
    callback: Callable[[], object],
):
    delay = max(int(delay_ms), 0)
    if owner is None:
        QTimer.singleShot(delay, callback)
        return None

    timer = QTimer(owner)
    timer.setSingleShot(True)
    owner_ref = weakref.ref(owner)
    tracked_timers = getattr(owner, "_owned_single_shot_timers", None)
    if tracked_timers is None:
        tracked_timers = []
        setattr(owner, "_owned_single_shot_timers", tracked_timers)
    tracked_timers.append(timer)

    def _release_timer():
        tracked_owner = owner_ref()
        if tracked_owner is None:
            return
        tracked = getattr(tracked_owner, "_owned_single_shot_timers", None)
        if tracked is None:
            return
        try:
            tracked.remove(timer)
        except ValueError:
            pass

    def _run_callback():
        try:
            callback()
        finally:
            _release_timer()
            try:
                timer.deleteLater()
            except RuntimeError:
                pass

    timer.destroyed.connect(_release_timer)
    timer.timeout.connect(_run_callback)
    timer._owned_single_shot_callback = _run_callback
    timer.start(delay)
    return timer
