from app.application.use_cases.runtime_monitoring import (
    RuntimeJobSnapshot,
    RuntimeMonitoringUseCases,
)


def test_build_overview_report_summarizes_runtime_jobs():
    use_cases = RuntimeMonitoringUseCases()
    jobs = [
        RuntimeJobSnapshot(
            name="import-workbook",
            kind="blocking",
            status="running",
            label="Importando planilha",
            detail_message="Lendo registros...",
            total=10,
            progress_value=4,
            cancellable=True,
            started_at="2026-03-31T12:00:00+00:00",
        ),
        RuntimeJobSnapshot(
            name="sync-mirror",
            kind="background",
            status="completed",
            label="Sincronizando espelho",
            detail_message="Espelho sincronizado.",
            total=0,
            progress_value=0,
            cancellable=False,
            started_at="2026-03-31T11:50:00+00:00",
            finished_at="2026-03-31T11:51:00+00:00",
        ),
        RuntimeJobSnapshot(
            name="check-update",
            kind="background",
            status="failed",
            label="Verificando atualizações",
            detail_message="Manifest inválido.",
            total=0,
            progress_value=0,
            cancellable=False,
            started_at="2026-03-31T11:40:00+00:00",
            finished_at="2026-03-31T11:41:00+00:00",
        ),
    ]

    report = use_cases.build_overview_report(jobs, recent_limit=2)

    assert report.total_jobs == 3
    assert report.running_jobs == 1
    assert report.completed_jobs == 1
    assert report.failed_jobs == 1
    assert report.cancelled_jobs == 0
    assert report.cancellable_jobs == 1
    assert report.latest_status == "running"
    assert report.latest_label == "Importando planilha"
    assert report.latest_detail_message == "Lendo registros..."
    assert [job.name for job in report.active_jobs] == ["import-workbook"]
    assert [job.name for job in report.recent_jobs] == ["import-workbook", "sync-mirror"]
