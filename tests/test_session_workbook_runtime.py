from app.services.session_workbook_runtime import SessionWorkbookRuntime


class FakeWorkbookLoader:
    def __init__(self, tracker):
        tracker["created"] += 1
        self._tracker = tracker
        self.path = ""
        self.wb = None
        self.ws = None
        self.plantio_ws = None
        self.col_map = {}
        self.plantio_col_map = {}
        self.uid_to_row = {}
        self.last_backup_time = 0
        self.merged_cells_warning = False
        self.loaded_source_mtime_ns = 0
        self.loaded_source_size = 0

    def load(self, path):
        self._tracker["loads"].append(path)
        self.path = path
        self.wb = object()
        self.ws = object()
        return ["ok"]


def test_session_workbook_runtime_keeps_path_without_eager_loader_init():
    tracker = {"created": 0, "loads": []}
    runtime = SessionWorkbookRuntime(loader_factory=lambda: FakeWorkbookLoader(tracker))

    runtime.path = "C:/dados/base.xlsx"

    assert runtime.path == "C:/dados/base.xlsx"
    assert runtime.session_path == "C:/dados/base.xlsx"
    assert runtime.has_materialized_workbook() is False
    assert runtime.has_materialized_session() is False
    assert tracker == {"created": 0, "loads": []}


def test_session_workbook_runtime_materializes_loader_only_when_loading():
    tracker = {"created": 0, "loads": []}
    runtime = SessionWorkbookRuntime(loader_factory=lambda: FakeWorkbookLoader(tracker))

    result = runtime.load("C:/dados/base.xlsx")

    assert result == ["ok"]
    assert runtime.has_materialized_workbook() is True
    assert runtime.has_materialized_session() is True
    assert tracker == {"created": 1, "loads": ["C:/dados/base.xlsx"]}
    assert runtime.wb is not None
    assert runtime.ws is not None


def test_session_workbook_runtime_exposes_session_alias_methods(tmp_path):
    tracker = {"created": 0, "loads": []}
    runtime = SessionWorkbookRuntime(loader_factory=lambda: FakeWorkbookLoader(tracker))
    session_path = tmp_path / "base.xlsx"
    session_path.write_text("base", encoding="utf-8")

    runtime.session_path = str(session_path)
    runtime.ensure_session_is_current()

    assert runtime.session_path == str(session_path)
    assert tracker == {"created": 1, "loads": [str(session_path)]}
