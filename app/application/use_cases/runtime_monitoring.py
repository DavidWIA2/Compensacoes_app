from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class RuntimeJobSnapshot:
    name: str
    kind: str
    status: str
    label: str
    detail_message: str
    total: int
    progress_value: int
    cancellable: bool
    started_at: str
    finished_at: str = ""

    @property
    def is_running(self) -> bool:
        return self.status == "running"


@dataclass(frozen=True)
class RuntimeJobOverviewReport:
    total_jobs: int
    running_jobs: int
    completed_jobs: int
    failed_jobs: int
    cancelled_jobs: int
    cancellable_jobs: int
    latest_status: str
    latest_label: str
    latest_detail_message: str
    recent_jobs: tuple[RuntimeJobSnapshot, ...] = ()
    active_jobs: tuple[RuntimeJobSnapshot, ...] = ()


class RuntimeMonitoringUseCases:
    def build_overview_report(
        self,
        jobs: Sequence[RuntimeJobSnapshot],
        *,
        recent_limit: int = 5,
    ) -> RuntimeJobOverviewReport:
        items = list(jobs)
        active_jobs = tuple(job for job in items if job.status == "running")
        latest_job = items[0] if items else None

        return RuntimeJobOverviewReport(
            total_jobs=len(items),
            running_jobs=sum(1 for job in items if job.status == "running"),
            completed_jobs=sum(1 for job in items if job.status == "completed"),
            failed_jobs=sum(1 for job in items if job.status == "failed"),
            cancelled_jobs=sum(1 for job in items if job.status == "cancelled"),
            cancellable_jobs=sum(1 for job in active_jobs if job.cancellable),
            latest_status=str(getattr(latest_job, "status", "") or ""),
            latest_label=str(getattr(latest_job, "label", "") or ""),
            latest_detail_message=str(getattr(latest_job, "detail_message", "") or ""),
            recent_jobs=tuple(items[: max(recent_limit, 0)]),
            active_jobs=active_jobs,
        )
