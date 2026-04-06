from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SingletonSessionStartupPlan:
    action: str
    singleton_path: str = ""
    source_path: str = ""

    @property
    def should_bootstrap_legacy(self) -> bool:
        return self.action == "bootstrap_legacy"

    @property
    def should_load_singleton(self) -> bool:
        return self.action == "load_singleton"

    @property
    def is_noop(self) -> bool:
        return self.action == "noop"


def build_singleton_session_startup_plan(
    *,
    pending_legacy_source_path: str,
    singleton_session_path: str,
) -> SingletonSessionStartupPlan:
    legacy_source = str(pending_legacy_source_path or "").strip()
    if legacy_source:
        return SingletonSessionStartupPlan(
            action="bootstrap_legacy",
            source_path=legacy_source,
        )

    singleton_path = str(singleton_session_path or "").strip()
    if singleton_path:
        return SingletonSessionStartupPlan(
            action="load_singleton",
            singleton_path=singleton_path,
        )

    return SingletonSessionStartupPlan(action="noop")
