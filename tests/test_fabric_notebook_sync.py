"""Testes de dlctl.connectors.fabric_notebook_sync: resolução de
FABRIC_SYNC_MAX_WORKERS (com override explícito) e paralelismo real dos
downloads de notebooks via ThreadPoolExecutor."""
from __future__ import annotations

import base64
import time
from pathlib import Path

import pytest

from dlctl.connectors.fabric_notebook_sync import (
    NotebookSyncError,
    _max_workers,
    sync_workspace_notebooks,
)


def test_max_workers_uses_env_when_no_override(monkeypatch):
    monkeypatch.setenv("FABRIC_SYNC_MAX_WORKERS", "6")
    assert _max_workers() == 6


def test_max_workers_clamps_env_value_to_range(monkeypatch):
    monkeypatch.setenv("FABRIC_SYNC_MAX_WORKERS", "99")
    assert _max_workers() == 8
    monkeypatch.setenv("FABRIC_SYNC_MAX_WORKERS", "0")
    assert _max_workers() == 1


def test_max_workers_invalid_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("FABRIC_SYNC_MAX_WORKERS", "not-a-number")
    assert _max_workers() == 4


def test_max_workers_explicit_override_wins_over_env(monkeypatch):
    monkeypatch.setenv("FABRIC_SYNC_MAX_WORKERS", "1")
    assert _max_workers(override=8) == 8
    assert _max_workers(override=99) == 8  # também clampado
    assert _max_workers(override=0) == 1


def _fake_notebook_definition() -> dict:
    payload = base64.b64encode(b"print('hello')").decode()
    return {"parts": [{"path": "notebook-content.py", "payload": payload, "payloadType": "InlineBase64"}]}


class _SlowFakeFabricClient:
    """Simula o FabricClient real, mas com uma latência artificial por
    notebook — permite medir se os downloads realmente rodam em paralelo."""

    def __init__(self, profile, workspace_id=None, sleep_seconds: float = 0.05, notebook_count: int = 6):
        self.workspace_id = workspace_id
        self._sleep_seconds = sleep_seconds
        self._notebook_count = notebook_count

    def list_items(self):
        return [
            {"id": f"nb-{i}", "displayName": f"Notebook{i}", "type": "Notebook", "folderId": None}
            for i in range(self._notebook_count)
        ]

    def list_folders(self):
        return []

    def get_definition_lro(self, item_id, item_type="notebooks"):
        time.sleep(self._sleep_seconds)
        return _fake_notebook_definition()


@pytest.fixture()
def fake_profile(tmp_profile):
    tmp_profile.microsoft.default_workspace_id = "fake-workspace-id"
    return tmp_profile


def test_sync_workspace_notebooks_missing_workspace_id_raises(tmp_profile):
    tmp_profile.microsoft.default_workspace_id = None
    with pytest.raises(NotebookSyncError, match="FABRIC_WORKSPACE_ID"):
        sync_workspace_notebooks(tmp_profile)


def test_sync_workspace_notebooks_downloads_all_and_reports_max_workers(monkeypatch, fake_profile, tmp_path):
    monkeypatch.setattr(
        "dlctl.connectors.fabric_notebook_sync.FabricClient",
        lambda profile, workspace_id=None: _SlowFakeFabricClient(profile, workspace_id, sleep_seconds=0.01, notebook_count=4),
    )
    output_dir = tmp_path / "lakehouse-dev"

    result = sync_workspace_notebooks(fake_profile, output_dir=str(output_dir), max_workers=4)

    assert result["downloaded"] == 4
    assert result["total"] == 4
    assert result["failures"] == []
    assert result["max_workers"] == 4

    written_files = list(output_dir.rglob("notebook-content.py"))
    assert len(written_files) == 4
    assert all(f.read_text(encoding="utf-8") == "print('hello')" for f in written_files)


def test_sync_workspace_notebooks_runs_downloads_in_parallel(monkeypatch, fake_profile, tmp_path):
    """Com 8 notebooks e 0.08s de latência simulada cada: em série levaria
    ~0.64s; com max_workers=8, deve levar perto de ~0.08-0.2s. Usamos uma
    margem generosa (metade do tempo serial) para evitar flutuação em CI."""
    notebook_count = 8
    sleep_seconds = 0.08
    serial_estimate = notebook_count * sleep_seconds

    monkeypatch.setattr(
        "dlctl.connectors.fabric_notebook_sync.FabricClient",
        lambda profile, workspace_id=None: _SlowFakeFabricClient(
            profile, workspace_id, sleep_seconds=sleep_seconds, notebook_count=notebook_count,
        ),
    )

    # Pré-aquece o engine/tabelas do state.db (SQLModel.metadata.create_all) ANTES
    # de medir: essa criação é um custo único de infraestrutura (não relacionado
    # ao paralelismo dos downloads) que, sem isso, poderia mascarar a medição na
    # primeira chamada de log_activity() dentro de sync_workspace_notebooks.
    from dlctl.core.state import get_engine

    get_engine(fake_profile)

    started = time.perf_counter()
    result = sync_workspace_notebooks(
        fake_profile, output_dir=str(tmp_path / "parallel"), max_workers=8,
    )
    elapsed = time.perf_counter() - started

    assert result["downloaded"] == notebook_count
    assert result["max_workers"] == 8
    assert elapsed < serial_estimate / 2, (
        f"Download não parece paralelo: levou {elapsed:.3f}s, esperado bem menos que {serial_estimate:.3f}s serial."
    )


def test_sync_workspace_notebooks_max_workers_none_uses_env_default(monkeypatch, fake_profile, tmp_path):
    monkeypatch.setenv("FABRIC_SYNC_MAX_WORKERS", "2")
    monkeypatch.setattr(
        "dlctl.connectors.fabric_notebook_sync.FabricClient",
        lambda profile, workspace_id=None: _SlowFakeFabricClient(profile, workspace_id, sleep_seconds=0.01, notebook_count=2),
    )

    result = sync_workspace_notebooks(fake_profile, output_dir=str(tmp_path / "env_default"))
    assert result["max_workers"] == 2


def test_sync_workspace_notebooks_no_matching_notebooks_raises(monkeypatch, fake_profile, tmp_path):
    class _EmptyClient:
        def __init__(self, profile, workspace_id=None):
            pass

        def list_items(self):
            return [{"id": "x", "displayName": "NaoNotebook", "type": "Lakehouse"}]

        def list_folders(self):
            return []

    monkeypatch.setattr("dlctl.connectors.fabric_notebook_sync.FabricClient", _EmptyClient)
    with pytest.raises(NotebookSyncError, match="Nenhum notebook"):
        sync_workspace_notebooks(fake_profile, output_dir=str(tmp_path / "empty"))
