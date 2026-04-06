from __future__ import annotations

import os
from copy import deepcopy
from typing import Any, Callable, Sequence, TypeVar

from app.application.use_cases.authoritative_write_coordinator import (
    AuthoritativeWriteCoordinator,
    AuthoritativeWriteError,
    AuthoritativeWriteStatus,
    CoordinatedWriteResult,
)
from app.application.use_cases.local_mutation_sync import (
    LocalMutationApplyResult,
    LocalMutationSyncUseCases,
)
from app.application.use_cases.local_record_queries import (
    LocalDuplicateCheckResult,
    LocalFilterFacetsResult,
    LocalRecordQueriesUseCases,
    LocalRecordReadResult,
    LocalSelectedRecordResult,
)
from app.application.use_cases.local_write_authority import (
    LocalCreatePreparation,
    LocalDeletePreparation,
    LocalUpdatePreparation,
    LocalWriteAuthorityUseCases,
    LocalWritePreparation,
)
from app.application.use_cases.authoritative_persistence_support import (
    AuthoritativeMonitoringSnapshot,
    AuthoritativeWorkbookLoadResult,
    SessionAvailability,
    WorkbookServiceStateSnapshot,
    bind_workbook_runtime_path,
    build_authoritative_workbook_load_result,
    build_monitoring_snapshot,
    build_runtime_record_result,
    build_session_availability,
    current_session_path as current_runtime_session_path,
    current_workbook_path as current_runtime_workbook_path,
    get_session_snapshot_summary,
    has_snapshot_data,
    list_session_records,
    restore_workbook_service_state,
    snapshot_workbook_service_state,
    sync_session_snapshot,
    try_touch_session_catalog_entry,
)
from app.application.use_cases.authoritative_persistence_write_support import (
    assign_provisional_add_identity,
    assign_provisional_import_identities,
    build_batch_geocode_audit_after_payload,
    build_batch_geocode_audit_metadata,
    build_import_audit_after_payload,
    build_import_audit_metadata,
    build_import_execution_result,
)
from app.application.use_cases.persistence_monitoring import (
    PersistenceMonitoringUseCases,
    PersistenceRecordOverviewReport,
    PersistenceStatusReport,
)
from app.application.use_cases.record_mutations import RecordMutationUseCases
from app.application.use_cases.recovery_operations import (
    OperationHistoryPlan,
    RecoveryOperationsUseCases,
    RestoreRequest,
    RollbackDialogPlan,
)
from app.application.use_cases.workbook_commands import ImportExecutionResult
from app.application.use_cases.workbook_commands import (
    RollbackOption,
    RollbackRestoreResult,
    SessionRecoveryUseCases,
)
from app.application.use_cases.workbook_session import (
    ImportSessionAnalysis,
    LoadSessionResult,
    ProgressCallback,
    SessionRuntimeUseCases,
)
from app.models.compensacao import Compensacao
from app.services.audit_service import serialize_record, serialize_records_sample
from app.services.sqlite_session_backup_service import SqliteSessionBackupService
from app.utils.logger import get_logger


logger = get_logger("UseCases.AuthoritativePersistence")

TExcelResult = TypeVar("TExcelResult")


class AuthoritativePersistenceUseCases:
    def __init__(
        self,
        workbook,
        audit_service,
        persistence_service=None,
        *,
        loader_factory: Callable[[], object] | None = None,
        monitoring_use_cases: PersistenceMonitoringUseCases | None = None,
    ):
        self.workbook = workbook
        self.audit_service = audit_service
        self.persistence_service = persistence_service
        self.session_backup_service = SqliteSessionBackupService()
        self.persistence_monitoring_use_cases = monitoring_use_cases or PersistenceMonitoringUseCases(
            persistence_service
        )
        self.local_record_queries = LocalRecordQueriesUseCases(persistence_service)
        self.local_mutation_sync = LocalMutationSyncUseCases(persistence_service)
        self.local_write_authority = LocalWriteAuthorityUseCases(self.local_record_queries)
        self.record_mutations = RecordMutationUseCases(workbook)
        self.authoritative_write = AuthoritativeWriteCoordinator(self.local_mutation_sync)
        self.workbook_use_cases = (
            SessionRuntimeUseCases(workbook, loader_factory=loader_factory)
            if loader_factory is not None
            else None
        )
        self.recovery_use_cases = SessionRecoveryUseCases(workbook, audit_service)
        self.recovery_operations = RecoveryOperationsUseCases(self.recovery_use_cases, audit_service)

    @staticmethod
    def _clone_records(records: Sequence[Compensacao]) -> tuple[Compensacao, ...]:
        return tuple(deepcopy(list(records)))

    @staticmethod
    def _normalized_issues(*issue_groups: Sequence[str]) -> tuple[str, ...]:
        merged: list[str] = []
        for group in issue_groups:
            for issue in group:
                normalized = str(issue or "").strip()
                if normalized and normalized not in merged:
                    merged.append(normalized)
        return tuple(merged)

    @staticmethod
    def _build_write_status_with_issues(
        status: AuthoritativeWriteStatus,
        *extra_issues: str,
    ) -> AuthoritativeWriteStatus:
        merged_issues = AuthoritativePersistenceUseCases._normalized_issues(status.issues, extra_issues)
        if merged_issues == status.issues:
            return status
        return AuthoritativeWriteStatus(
            status=status.status,
            operation=status.operation,
            workbook_path=status.workbook_path,
            authority_source=status.authority_source,
            sqlite_status=status.sqlite_status,
            sqlite_strategy=status.sqlite_strategy,
            synced_at=status.synced_at,
            record_count=status.record_count,
            excel_mirrored=status.excel_mirrored,
            finalized=status.finalized,
            rollback_applied=status.rollback_applied,
            issues=merged_issues,
        )

    @staticmethod
    def _with_write_issues(
        result: CoordinatedWriteResult[TExcelResult],
        *extra_issues: str,
    ) -> CoordinatedWriteResult[TExcelResult]:
        write_status = AuthoritativePersistenceUseCases._build_write_status_with_issues(
            result.write_status,
            *extra_issues,
        )
        if write_status == result.write_status:
            return result
        return CoordinatedWriteResult(
            status=result.status,
            write_status=write_status,
            records=result.records,
            excel_result=result.excel_result,
            rollback_issues=result.rollback_issues,
            finalized=result.finalized,
        )

    def current_workbook_path(self) -> str:
        return current_runtime_workbook_path(self.workbook)

    def current_session_path(self) -> str:
        return current_runtime_session_path(self.workbook)

    def ensure_singleton_session(self):
        if self.persistence_service is None or not hasattr(self.persistence_service, "ensure_singleton_session"):
            raise RuntimeError("Banco local único indisponível sem SQLite ativo.")
        return self.persistence_service.ensure_singleton_session()

    def migrate_legacy_workbook_to_singleton(self, source_path: str) -> str:
        normalized_source = str(source_path or "").strip()
        if not normalized_source:
            raise ValueError("Informe o caminho da planilha legada para inicializar o banco local.")

        if not normalized_source.lower().startswith("session://"):
            normalized_source = os.path.abspath(normalized_source)

        singleton_entry = self.ensure_singleton_session()
        singleton_path = str(getattr(singleton_entry, "session_path", "") or "").strip()
        if not singleton_path:
            raise RuntimeError("Não foi possível resolver o caminho do banco local único.")

        if os.path.exists(normalized_source):
            if self.workbook_use_cases is None:
                raise RuntimeError("Migração inicial indisponível sem SessionRuntimeUseCases configurado.")
            load_result = self.workbook_use_cases.load_session(normalized_source)
            source_records = tuple(load_result.records)
        elif self.has_local_snapshot(normalized_source):
            source_records = list_session_records(self.persistence_service, normalized_source)
        else:
            raise FileNotFoundError(
                f"Não foi possível encontrar a base legada em '{normalized_source}' nem um snapshot local correspondente."
            )

        sync_session_snapshot(self.persistence_service, singleton_path, source_records)
        try_touch_session_catalog_entry(self.persistence_service, singleton_path)
        bind_workbook_runtime_path(self.workbook, singleton_path, clear_loaded_workbook=True)
        logger.info(
            "Banco local inicializado a partir da base legada '%s' com %s registro(s).",
            normalized_source,
            len(source_records),
        )
        return singleton_path

    def list_named_sessions(self, *, limit: int = 200):
        if self.persistence_service is None or not hasattr(self.persistence_service, "list_named_sessions"):
            return ()
        return tuple(self.persistence_service.list_named_sessions(limit=limit))

    def create_named_session(self, session_name: str):
        if self.persistence_service is None or not hasattr(self.persistence_service, "create_named_session"):
            raise RuntimeError("Catálogo de sessões indisponível sem SQLite ativo.")
        return self.persistence_service.create_named_session(session_name)

    def load_session(self, path: str) -> AuthoritativeWorkbookLoadResult:
        return self.load_workbook(path)

    def analyze_session_import(
        self,
        current_records: Sequence[Compensacao],
        import_path: str,
    ) -> ImportSessionAnalysis:
        return self.analyze_import(current_records, import_path)

    def _get_session_snapshot_summary(self, workbook_path: str):
        return get_session_snapshot_summary(self.persistence_service, workbook_path)

    def _list_session_records(self, workbook_path: str) -> tuple[Compensacao, ...]:
        return list_session_records(self.persistence_service, workbook_path)

    def _sync_session_snapshot(self, workbook_path: str, records: Sequence[Compensacao]) -> object | None:
        return sync_session_snapshot(self.persistence_service, workbook_path, records)

    def resolve_session_availability(self, workbook_path: str) -> SessionAvailability:
        return build_session_availability(
            workbook_path,
            has_local_snapshot=self.has_local_snapshot(workbook_path),
            persistence_service=self.persistence_service,
        )

    def has_local_snapshot(self, workbook_path: str) -> bool:
        normalized_path = str(workbook_path or "").strip()
        if not normalized_path or self.persistence_service is None:
            return False
        try:
            snapshot = self._get_session_snapshot_summary(normalized_path)
        except Exception:
            return False
        return has_snapshot_data(snapshot)

    def _bind_workbook_runtime_path(self, workbook_path: str, *, clear_loaded_workbook: bool = False) -> None:
        bind_workbook_runtime_path(
            self.workbook,
            workbook_path,
            clear_loaded_workbook=clear_loaded_workbook,
        )

    def _load_records_from_sqlite(
        self,
        workbook_path: str,
    ) -> tuple[tuple[Compensacao, ...], object | None]:
        normalized_path = str(workbook_path or "").strip()
        if not normalized_path or self.persistence_service is None:
            return (), None
        snapshot = self._get_session_snapshot_summary(normalized_path)
        if not has_snapshot_data(snapshot):
            return (), snapshot
        records = self._list_session_records(normalized_path)
        expected_count = int(getattr(snapshot, "record_count", 0) or 0)
        if expected_count > 0 and len(records) != expected_count:
            raise RuntimeError(
                f"Snapshot SQLite de {normalized_path} informou {expected_count} registro(s), mas retornou {len(records)}."
            )
        return records, snapshot

    def resolve_runtime_record_source(
        self,
        workbook_path: str,
        *,
        fallback_records: Sequence[Compensacao],
    ) -> LocalRecordReadResult:
        normalized_path = str(workbook_path or "").strip()
        fallback = tuple(fallback_records)
        try:
            records, snapshot = self._load_records_from_sqlite(normalized_path)
        except Exception as exc:
            return build_runtime_record_result(
                source="session",
                records=fallback,
                strategy="session_runtime",
                metrics=self.local_record_queries._build_session_record_result(
                    fallback,
                    workbook_path=normalized_path,
                    strategy="session_runtime",
                ).metrics,
                workbook_path=normalized_path,
                issues=(f"Falha ao atualizar a sessao pelo SQLite: {exc}",),
            )
        if not records:
            return build_runtime_record_result(
                source="session",
                records=fallback,
                strategy="session_runtime",
                metrics=self.local_record_queries._build_session_record_result(
                    fallback,
                    workbook_path=normalized_path,
                    strategy="session_runtime",
                ).metrics,
                workbook_path=normalized_path,
                snapshot=snapshot,
                issues=("Snapshot SQLite indisponivel para recarregar a sessao.",),
            )
        return build_runtime_record_result(
            source="sqlite",
            records=records,
            strategy="sqlite_runtime",
            metrics=self.local_record_queries._build_session_record_result(
                records,
                workbook_path=normalized_path,
                strategy="sqlite_runtime",
            ).metrics,
            workbook_path=normalized_path,
            snapshot=snapshot,
        )

    def bind_runtime_window(self, window) -> None:
        self.set_persistence_service(getattr(window, "persistence_service", None))

    def set_persistence_service(self, persistence_service) -> None:
        self.persistence_service = persistence_service
        self.local_record_queries.snapshot_reader = persistence_service
        self.local_mutation_sync.snapshot_writer = persistence_service
        self.persistence_monitoring_use_cases.snapshot_reader = persistence_service

    def snapshot_workbook_service_state(self) -> WorkbookServiceStateSnapshot:
        return snapshot_workbook_service_state(self.workbook)

    def restore_workbook_service_state(self, snapshot: WorkbookServiceStateSnapshot) -> None:
        restore_workbook_service_state(self.workbook, snapshot)

    def ensure_workbook_is_current(self) -> None:
        ensure_current = getattr(self.workbook, "ensure_workbook_is_current", None)
        if callable(ensure_current):
            ensure_current()

    def sync_workbook_snapshot(self, records: Sequence[Compensacao]) -> object | None:
        workbook_path = self.current_session_path()
        if not workbook_path or self.persistence_service is None:
            return None
        return sync_session_snapshot(self.persistence_service, workbook_path, records)

    def build_persistence_status_report(
        self,
        workbook_path: str,
        *,
        expected_records: int,
        expected_audit_events: int,
    ) -> PersistenceStatusReport:
        normalized_path = str(workbook_path or "").strip()
        try:
            return self.persistence_monitoring_use_cases.build_status_report(
                normalized_path,
                expected_records=int(expected_records),
                expected_audit_events=int(expected_audit_events),
            )
        except Exception as exc:
            issue = f"Falha ao consultar o status do espelho local: {exc}"
            logger.warning(issue, exc_info=True)
            return PersistenceStatusReport(
                status="indisponivel",
                workbook_path=normalized_path,
                synced_at="",
                mirrored_records=0,
                mirrored_plantios=0,
                mirrored_audit_events=0,
                expected_records=int(expected_records),
                expected_audit_events=int(expected_audit_events),
                issues=(issue,),
            )

    def resolve_dashboard_record_overview(
        self,
        workbook_path: str,
        *,
        cached_report: PersistenceRecordOverviewReport | None = None,
        refresh: bool = False,
        top_microbacias_limit: int = 3,
        sample_limit: int = 0,
    ) -> PersistenceRecordOverviewReport | None:
        if cached_report is not None and not refresh:
            return cached_report

        normalized_path = str(workbook_path or "").strip()
        if not normalized_path:
            return None

        try:
            return self.persistence_monitoring_use_cases.build_record_overview_report(
                normalized_path,
                top_microbacias_limit=int(top_microbacias_limit),
                sample_limit=int(sample_limit),
            )
        except Exception as exc:
            logger.warning("Falha ao montar resumo local autoritativo: %s", exc, exc_info=True)
            return None

    def resolve_monitoring_snapshot(
        self,
        workbook_path: str,
        *,
        expected_records: int,
        expected_audit_events: int,
        cached_record_overview: PersistenceRecordOverviewReport | None = None,
        refresh_record_overview: bool = False,
        top_microbacias_limit: int = 3,
        sample_limit: int = 3,
    ) -> AuthoritativeMonitoringSnapshot:
        normalized_path = str(workbook_path or "").strip()
        return build_monitoring_snapshot(
            normalized_path,
            persistence_report=self.build_persistence_status_report(
                normalized_path,
                expected_records=int(expected_records),
                expected_audit_events=int(expected_audit_events),
            ),
            record_overview_report=self.resolve_dashboard_record_overview(
                normalized_path,
                cached_report=cached_record_overview,
                refresh=refresh_record_overview,
                top_microbacias_limit=int(top_microbacias_limit),
                sample_limit=int(sample_limit),
            ),
        )

    def create_operation_backup(self, label: str) -> str:
        workbook_path = self.current_session_path()
        if not workbook_path:
            return ""
        records_result = self.resolve_runtime_record_source(
            workbook_path,
            fallback_records=(),
        )
        return self.session_backup_service.create_backup(
            workbook_path=workbook_path,
            label=label,
            records=records_result.records,
        )

    def resolve_filter_facets(
        self,
        workbook_path: str,
        *,
        fallback_records: Sequence[Compensacao],
    ) -> LocalFilterFacetsResult:
        return self.local_record_queries.resolve_filter_facets(
            workbook_path,
            fallback_records=fallback_records,
        )

    def build_filter_facets_status(self, facets_result: LocalFilterFacetsResult):
        return self.local_record_queries.build_filter_facets_status(facets_result)

    def resolve_selected_record(
        self,
        workbook_path: str,
        *,
        fallback_records: Sequence[Compensacao],
        uid: str = "",
        excel_row: int = 0,
    ) -> LocalSelectedRecordResult:
        return self.local_record_queries.resolve_selected_record(
            workbook_path,
            fallback_records=fallback_records,
            uid=uid,
            excel_row=excel_row,
        )

    def resolve_duplicate_av_tec(
        self,
        workbook_path: str,
        *,
        fallback_records: Sequence[Compensacao],
        av_tec: str,
        current_uid: str = "",
    ) -> LocalDuplicateCheckResult:
        return self.local_record_queries.resolve_duplicate_av_tec(
            workbook_path,
            fallback_records=fallback_records,
            av_tec=av_tec,
            current_uid=current_uid,
        )

    def resolve_authoritative_record_source(
        self,
        workbook_path: str,
        *,
        fallback_records: Sequence[Compensacao],
    ) -> LocalRecordReadResult:
        return self.local_record_queries.resolve_authoritative_record_source(
            workbook_path,
            fallback_records=fallback_records,
        )

    def prepare_base(
        self,
        workbook_path: str,
        *,
        fallback_records: Sequence[Compensacao],
    ) -> LocalWritePreparation:
        return self.local_write_authority.prepare_base(
            workbook_path,
            fallback_records=fallback_records,
        )

    def prepare_create(
        self,
        workbook_path: str,
        *,
        fallback_records: Sequence[Compensacao],
        draft_record: Compensacao,
    ) -> LocalCreatePreparation:
        return self.local_write_authority.prepare_create(
            workbook_path,
            fallback_records=fallback_records,
            draft_record=draft_record,
        )

    def prepare_update(
        self,
        workbook_path: str,
        *,
        fallback_records: Sequence[Compensacao],
        fallback_selected: Compensacao | None,
        draft_record: Compensacao,
    ) -> LocalUpdatePreparation:
        return self.local_write_authority.prepare_update(
            workbook_path,
            fallback_records=fallback_records,
            fallback_selected=fallback_selected,
            draft_record=draft_record,
        )

    def prepare_delete(
        self,
        workbook_path: str,
        *,
        fallback_records: Sequence[Compensacao],
        fallback_selected: Compensacao | None,
    ) -> LocalDeletePreparation:
        return self.local_write_authority.prepare_delete(
            workbook_path,
            fallback_records=fallback_records,
            fallback_selected=fallback_selected,
        )

    def load_workbook(self, path: str) -> AuthoritativeWorkbookLoadResult:
        normalized_path = str(path or "").strip()
        if not normalized_path:
            raise ValueError("Informe o caminho da sessao para carregar os registros.")

        self._bind_workbook_runtime_path(normalized_path, clear_loaded_workbook=True)

        sqlite_issues: tuple[str, ...] = ()
        try:
            sqlite_records, snapshot_status = self._load_records_from_sqlite(normalized_path)
        except Exception as exc:
            sqlite_records = ()
            snapshot_status = None
            sqlite_issues = (f"Falha ao carregar a sessao local no SQLite: {exc}",)
            logger.warning(sqlite_issues[0], exc_info=True)

        sqlite_has_session = bool(sqlite_records or has_snapshot_data(snapshot_status))

        if sqlite_has_session:
            if self.persistence_service is not None and hasattr(self.persistence_service, "touch_session"):
                try:
                    self.persistence_service.touch_session(normalized_path)
                except Exception:
                    logger.warning("Falha ao marcar a sessão '%s' como aberta no catálogo local.", normalized_path, exc_info=True)
            record_source = build_runtime_record_result(
                source="sqlite",
                records=sqlite_records,
                strategy="sqlite_session_load",
                metrics=self.local_record_queries._build_session_record_result(
                    sqlite_records,
                    workbook_path=normalized_path,
                    strategy="sqlite_session_load",
                ).metrics,
                workbook_path=normalized_path,
                snapshot=snapshot_status,
                issues=sqlite_issues,
            )
            read_status = self.local_record_queries.build_read_status(
                record_source,
                filtered_records=len(record_source.records),
            )
            load_result = LoadSessionResult(path=normalized_path, records=list(sqlite_records))
            return build_authoritative_workbook_load_result(
                path=normalized_path,
                loaded_records=sqlite_records,
                record_source=record_source,
                local_session_source_status=read_status,
                load_result=load_result,
                issues=record_source.issues,
                snapshot_status=snapshot_status,
            )

        if self.workbook_use_cases is None:
            raise RuntimeError("Carga da sessao indisponivel sem SessionRuntimeUseCases configurado.")

        load_result = self.workbook_use_cases.load_session(normalized_path)
        loaded_records = tuple(load_result.records)
        bind_workbook_runtime_path(self.workbook, load_result.path)
        snapshot_status = None
        sync_issues: tuple[str, ...] = ()

        if self.persistence_service is not None:
            try:
                snapshot_status = sync_session_snapshot(
                    self.persistence_service,
                    load_result.path,
                    loaded_records,
                )
            except Exception as exc:
                issue = f"Falha ao sincronizar espelho local apos carga: {exc}"
                sync_issues = (issue,)
                logger.warning(issue, exc_info=True)

        record_source = self.resolve_runtime_record_source(
            load_result.path,
            fallback_records=loaded_records,
        )
        issues = self._normalized_issues(sync_issues, sqlite_issues, record_source.issues)
        if issues and issues != record_source.issues:
            record_source = build_runtime_record_result(
                source=record_source.source,
                records=record_source.records,
                strategy=record_source.strategy,
                metrics=record_source.metrics,
                workbook_path=record_source.workbook_path,
                snapshot=type(
                    "SnapshotProxy",
                    (),
                    {
                        "synced_at": record_source.synced_at,
                        "record_count": record_source.mirrored_records,
                    },
                )(),
                issues=issues,
            )

        read_status = self.local_record_queries.build_read_status(
            record_source,
            filtered_records=len(record_source.records),
        )
        return build_authoritative_workbook_load_result(
            path=load_result.path,
            loaded_records=loaded_records,
            record_source=record_source,
            local_session_source_status=read_status,
            load_result=load_result,
            issues=issues,
            snapshot_status=snapshot_status,
        )

    def analyze_import(
        self,
        current_records: Sequence[Compensacao],
        import_path: str,
    ) -> ImportSessionAnalysis:
        if self.workbook_use_cases is None:
            raise RuntimeError("Fluxo de importacao indisponivel sem SessionRuntimeUseCases configurado.")
        return self.workbook_use_cases.analyze_import(current_records, import_path)

    def build_audited_rollback_options(
        self,
        workbook_path: str,
        *,
        limit: int = 200,
    ) -> tuple[RollbackOption, ...]:
        return self.recovery_use_cases.build_audited_rollback_options(workbook_path, limit=limit)

    def restore_backup(
        self,
        source_backup_path: str,
        *,
        rollback_source: str,
        metadata: dict[str, object] | None = None,
        label: str,
    ) -> RollbackRestoreResult:
        workbook_path = self.current_session_path()
        if not workbook_path:
            raise ValueError("Abra uma sessao antes de restaurar um backup.")
        if self.persistence_service is None:
            raise RuntimeError("Restauracao indisponivel sem espelho SQLite ativo.")

        rollback_backup_path = self.create_operation_backup("rollback")
        backup = self.session_backup_service.load_backup(source_backup_path)
        target_records = list(backup.records)
        sync_session_snapshot(self.persistence_service, workbook_path, target_records)
        self._append_audit_event_safely(
            action="rollback",
            summary=f"Sessao restaurada a partir de {label}",
            backup_path=rollback_backup_path,
            metadata={
                "source_type": rollback_source,
                "source_backup_path": os.path.abspath(source_backup_path),
                **dict(metadata or {}),
            },
            after={
                "restored_count": len(target_records),
                "sample_records": serialize_records_sample(target_records),
            },
        )
        return RollbackRestoreResult(
            workbook_path=workbook_path,
            source_backup_path=os.path.abspath(source_backup_path),
            rollback_source=rollback_source,
            label=label,
            backup_path=rollback_backup_path,
        )

    def build_operation_history_plan(self, workbook_path: str, *, limit: int = 200) -> OperationHistoryPlan:
        return self.recovery_operations.build_operation_history_plan(workbook_path, limit=limit)

    def build_restore_request_for_event(self, event) -> RestoreRequest:
        return self.recovery_operations.build_restore_request_for_event(event)

    def build_rollback_dialog_plan(self, workbook_path: str, *, limit: int = 200) -> RollbackDialogPlan:
        return self.recovery_operations.build_rollback_dialog_plan(workbook_path, limit=limit)

    def resolve_rollback_choice(
        self,
        dialog_plan: RollbackDialogPlan,
        selected_label: str,
    ) -> RestoreRequest | None:
        return self.recovery_operations.resolve_rollback_choice(dialog_plan, selected_label)

    def build_no_backup_message(self) -> str:
        return self.recovery_operations.build_no_backup_message()

    def log_preparation_issues(self, operation: str, issues: Sequence[str]) -> None:
        normalized_issues = self._normalized_issues(issues)
        if not normalized_issues:
            return
        logger.warning(
            "Contexto autoritativo de escrita (%s) consultado com fallback/local issues: %s",
            operation,
            " | ".join(normalized_issues),
        )

    def store_local_mutation_status(self, window, status) -> None:
        window._local_mutation_sync_status = status
        if status is None:
            return
        if getattr(status, "issues", ()):
            logger.warning(
                "Falha ao sincronizar mutacao '%s' no espelho local: %s",
                getattr(status, "operation", "mutacao"),
                " | ".join(str(issue) for issue in getattr(status, "issues", ()) if str(issue).strip()),
            )

    def store_authoritative_write_status(self, window, status) -> None:
        window._authoritative_write_status = status
        if status is None:
            return
        if getattr(status, "issues", ()):
            logger.warning(
                "Escrita autoritativa '%s' reportou observacoes: %s",
                getattr(status, "operation", "mutacao"),
                " | ".join(str(issue) for issue in getattr(status, "issues", ()) if str(issue).strip()),
            )

    def publish_write_result(self, window, result: CoordinatedWriteResult[object]) -> None:
        self.store_local_mutation_status(window, result.status)
        self.store_authoritative_write_status(window, result.write_status)

    def unwrap_write_exception(self, window, exc: Exception) -> Exception:
        if isinstance(exc, AuthoritativeWriteError):
            self.store_authoritative_write_status(window, exc.write_status)
            if exc.__cause__ is not None:
                return exc.__cause__
        return exc

    def assign_provisional_add_identity(
        self,
        record: Compensacao,
        *,
        existing_records: Sequence[Compensacao],
    ) -> None:
        assign_provisional_add_identity(record, existing_records=existing_records)

    def assign_provisional_import_identities(
        self,
        imported_records: Sequence[Compensacao],
        *,
        existing_records: Sequence[Compensacao],
    ) -> None:
        assign_provisional_import_identities(
            imported_records,
            existing_records=existing_records,
        )

    def _append_audit_event_safely(
        self,
        *,
        action: str,
        summary: str,
        backup_path: str = "",
        metadata: dict[str, Any] | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> tuple[str, ...]:
        workbook_path = self.current_session_path()
        if not workbook_path:
            return ()

        try:
            audit_payload = {
                "action": action,
                "summary": summary,
                "backup_path": backup_path,
                "metadata": dict(metadata or {}),
                "before": before,
                "after": after,
            }
            if hasattr(self.audit_service, "append_session_event"):
                self.audit_service.append_session_event(session_path=workbook_path, **audit_payload)
            else:
                self.audit_service.append_event(workbook_path=workbook_path, **audit_payload)
        except Exception as exc:
            issue = f"Falha ao registrar auditoria da operacao '{action}': {exc}"
            logger.warning(issue, exc_info=True)
            return (issue,)
        return ()

    def _execute_coordinated_write(
        self,
        *,
        operation: str,
        sqlite_apply: Callable[[], LocalMutationApplyResult],
        finalized_records_factory: Callable[[], Sequence[Compensacao]] | None = None,
        audit_callback: Callable[[CoordinatedWriteResult[None]], tuple[str, ...]] | None = None,
    ) -> CoordinatedWriteResult[None]:
        result = self.authoritative_write.execute_sqlite_authoritative(
            workbook_path=self.current_session_path(),
            operation=operation,
            sqlite_apply=sqlite_apply,
            finalized_records_factory=finalized_records_factory,
        )
        if audit_callback is None:
            return result
        audit_issues = audit_callback(result)
        return self._with_write_issues(result, *audit_issues)

    def _build_import_result(
        self,
        *,
        analysis: ImportSessionAnalysis,
        imported_records: Sequence[Compensacao],
        backup_path: str,
    ) -> ImportExecutionResult:
        return build_import_execution_result(
            analysis=analysis,
            imported_records=imported_records,
            backup_path=backup_path,
        )

    def _execute_coordinated_import(
        self,
        *,
        analysis: ImportSessionAnalysis,
        base_records: Sequence[Compensacao],
        imported_records: Sequence[Compensacao],
        backup_path: str,
    ) -> CoordinatedWriteResult[ImportExecutionResult]:
        write_result = self.authoritative_write.execute_sqlite_authoritative(
            workbook_path=self.current_session_path(),
            operation="import",
            sqlite_apply=lambda: self.local_mutation_sync.apply_after_import(
                workbook_path=self.current_session_path(),
                existing_records=base_records,
                imported_records=imported_records,
            ),
            finalized_records_factory=lambda: self.local_mutation_sync.project_after_import(
                base_records,
                imported_records,
            ),
        )
        import_result = self._build_import_result(
            analysis=analysis,
            imported_records=imported_records,
            backup_path=backup_path,
        )
        return CoordinatedWriteResult(
            status=write_result.status,
            write_status=write_result.write_status,
            records=write_result.records,
            excel_result=import_result,
            rollback_issues=write_result.rollback_issues,
            finalized=write_result.finalized,
        )

    def execute_add(
        self,
        record: Compensacao,
        *,
        authoritative_records: Sequence[Compensacao],
    ) -> CoordinatedWriteResult[None]:
        backup_path = self.create_operation_backup("add")
        self.assign_provisional_add_identity(record, existing_records=authoritative_records)
        return self._execute_coordinated_write(
            operation="add",
            sqlite_apply=lambda: self.local_mutation_sync.apply_after_add(
                workbook_path=self.current_session_path(),
                existing_records=authoritative_records,
                added_record=record,
            ),
            finalized_records_factory=lambda: self.local_mutation_sync.project_after_add(
                authoritative_records,
                record,
            ),
            audit_callback=lambda _result: self._append_audit_event_safely(
                action="add",
                summary=f"Registro cadastrado: {record.av_tec or record.oficio_processo}",
                backup_path=backup_path,
                after=serialize_record(record),
            ),
        )

    def execute_edit(
        self,
        record: Compensacao,
        *,
        authoritative_records: Sequence[Compensacao],
        before_record: Compensacao | None,
    ) -> CoordinatedWriteResult[None]:
        backup_path = self.create_operation_backup("edit")
        return self._execute_coordinated_write(
            operation="edit",
            sqlite_apply=lambda: self.local_mutation_sync.apply_after_edit(
                workbook_path=self.current_session_path(),
                existing_records=authoritative_records,
                updated_record=record,
            ),
            audit_callback=lambda _result: self._append_audit_event_safely(
                action="edit",
                summary=f"Registro alterado: {record.av_tec or record.oficio_processo}",
                backup_path=backup_path,
                before=serialize_record(before_record) if before_record is not None else None,
                after=serialize_record(record),
            ),
        )

    def execute_delete(
        self,
        deleted_record: Compensacao,
        *,
        authoritative_records: Sequence[Compensacao],
    ) -> CoordinatedWriteResult[None]:
        backup_path = self.create_operation_backup("delete")
        return self._execute_coordinated_write(
            operation="delete",
            sqlite_apply=lambda: self.local_mutation_sync.apply_after_delete(
                workbook_path=self.current_session_path(),
                existing_records=authoritative_records,
                deleted_record=deleted_record,
            ),
            audit_callback=lambda _result: self._append_audit_event_safely(
                action="delete",
                summary=f"Registro excluido: {deleted_record.av_tec or deleted_record.oficio_processo}",
                backup_path=backup_path,
                before=serialize_record(deleted_record),
            ),
        )

    def execute_import(
        self,
        analysis: ImportSessionAnalysis,
        *,
        base_records: Sequence[Compensacao],
        progress_callback: ProgressCallback | None = None,
    ) -> CoordinatedWriteResult[ImportExecutionResult]:
        imported_records = list(analysis.records_to_add)
        backup_path = self.create_operation_backup("import")
        self.assign_provisional_import_identities(
            imported_records,
            existing_records=base_records,
        )
        if progress_callback is not None:
            total = len(imported_records)
            for index, _record in enumerate(imported_records, start=1):
                progress_callback(index, total)

        result = self._execute_coordinated_import(
            analysis=analysis,
            base_records=base_records,
            imported_records=imported_records,
            backup_path=backup_path,
        )

        import_result = result.excel_result
        if import_result is None:
            raise RuntimeError("A importacao concluiu sem retornar o resultado esperado.")

        audit_issues = self._append_audit_event_safely(
            action="import",
            summary=f"{import_result.imported_count} registro(s) importado(s) de {os.path.basename(analysis.import_path)}",
            backup_path=backup_path,
            metadata=build_import_audit_metadata(
                analysis=analysis,
                import_result=import_result,
            ),
            after=build_import_audit_after_payload(imported_records),
        )
        return self._with_write_issues(result, *audit_issues)

    def execute_batch_geocode(
        self,
        *,
        authoritative_records: Sequence[Compensacao],
        projected_records: Sequence[Compensacao],
        updated_records: Sequence[Compensacao],
    ) -> CoordinatedWriteResult[int]:
        backup_path = self.create_operation_backup("batch_geocode")

        def sqlite_apply() -> LocalMutationApplyResult:
            status = self.local_mutation_sync.sync_projected_records(
                workbook_path=self.current_session_path(),
                records=projected_records,
                operation="batch_geocode",
            )
            return LocalMutationApplyResult(
                status=status,
                records=self._clone_records(projected_records),
                source="sqlite" if getattr(status, "uses_sqlite", False) else "projection",
            )

        result = self._execute_coordinated_write(
            operation="batch_geocode",
            sqlite_apply=sqlite_apply,
        )

        updated_count = len(updated_records)
        audit_issues = self._append_audit_event_safely(
            action="batch_geocode",
            summary=f"Geocodificacao em lote aplicada a {updated_count} registro(s)",
            backup_path=backup_path,
            metadata=build_batch_geocode_audit_metadata(updated_records),
            after=build_batch_geocode_audit_after_payload(updated_records),
        )
        result_with_count = CoordinatedWriteResult(
            status=result.status,
            write_status=result.write_status,
            records=result.records,
            excel_result=updated_count,
            rollback_issues=result.rollback_issues,
            finalized=result.finalized,
        )
        return self._with_write_issues(result_with_count, *audit_issues)


SessionServiceStateSnapshot = WorkbookServiceStateSnapshot
AuthoritativeSessionLoadResult = AuthoritativeWorkbookLoadResult
SessionMonitoringSnapshot = AuthoritativeMonitoringSnapshot
