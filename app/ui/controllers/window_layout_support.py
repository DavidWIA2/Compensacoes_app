from __future__ import annotations

from functools import partial
from typing import Iterable

from app.ui.components.timer_utils import schedule_owned_single_shot
from app.ui.controllers.settings_support import ensure_window_fits_available_geometry

_RESPONSIVE_METHOD_NAMES = ("apply_responsive_layout", "_apply_responsive_layout")
_FINALIZE_METHOD_NAMES = ("finalize_responsive_layout", "_finalize_responsive_layout")


def _resolve_method(target, method_names: Iterable[str]):
    for method_name in method_names:
        method = getattr(target, method_name, None)
        if callable(method):
            return method_name, method
    return "", None


def current_tab_widget(window):
    tabs = getattr(window, "tabs", None)
    if tabs is None:
        return None
    try:
        return tabs.currentWidget()
    except Exception:
        return None


def apply_widget_responsive_layout(widget, *, finalize: bool = False) -> bool:
    if widget is None:
        return False

    responsive_name, responsive_method = _resolve_method(widget, _RESPONSIVE_METHOD_NAMES)
    finalize_name, finalize_method = _resolve_method(widget, _FINALIZE_METHOD_NAMES)
    applied = False

    if responsive_method is not None:
        responsive_method()
        applied = True

    if finalize and finalize_method is not None and finalize_name != responsive_name:
        finalize_method()
        applied = True

    return applied


def apply_window_responsive_layout(
    window,
    *,
    include_active_tab: bool = True,
    finalize_active_tab: bool = True,
) -> bool:
    if window is None:
        return False

    applied = apply_widget_responsive_layout(
        getattr(window, "shell_controller", None),
        finalize=False,
    )

    if include_active_tab:
        applied = apply_widget_responsive_layout(
            current_tab_widget(window),
            finalize=finalize_active_tab,
        ) or applied

    return applied


def fit_window_to_available_geometry(
    window,
    *,
    include_active_tab: bool = True,
    finalize_active_tab: bool = True,
) -> bool:
    apply_window_responsive_layout(
        window,
        include_active_tab=include_active_tab,
        finalize_active_tab=finalize_active_tab,
    )
    return ensure_window_fits_available_geometry(window)


def schedule_window_fit(
    window,
    *,
    delays: Iterable[int] = (0, 120),
    include_active_tab: bool = True,
    finalize_active_tab: bool = True,
) -> bool:
    if window is None:
        return False

    for delay in tuple(int(delay) for delay in delays):
        schedule_owned_single_shot(
            window,
            delay,
            partial(
                fit_window_to_available_geometry,
                window,
                include_active_tab=include_active_tab,
                finalize_active_tab=finalize_active_tab,
            ),
        )
    return True
