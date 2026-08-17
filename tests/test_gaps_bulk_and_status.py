"""Testes offline dos 2 gaps fechados: bulk copyjobs (Plan 39) e status
polling de execução. Nenhum destes testes faz qualquer chamada de rede real
(o "client" usado nos testes de polling é um mock local, sem HTTP)."""
from __future__ import annotations

import json

import pytest
import yaml

from dlctl.core import copyjob_bulk as bulk
from dlctl.core.execution import TERMINAL_STATUSES, poll_job_status
from dlctl.core.gates import GateContext, SecurityError


def _write_copyjob_yaml(tmp_path, name, source_signature="", definition_file="def.json"):
    (tmp_path / definition_file).write_text(json.dumps({"a": 1}), encoding="utf-8")
    data = {
        "display_name": name, "folder_path": "copyjobs/SUPRIMENTOS",
        "definition_file": definition_file, "source_signature": source_signature,
    }
    (tmp_path / f"{name}.copyjob.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")


# ==================== copyjob_bulk ====================

def test_load_bulk_definitions_reads_all_yaml(tmp_path):
    _write_copyjob_yaml(tmp_path, "cpj_a")
    _write_copyjob_yaml(tmp_path, "cpj_b")
    entries = bulk.load_bulk_definitions(tmp_path)
    assert {e.display_name for e in entries} == {"cpj_a", "cpj_b"}


def test_detect_duplicates_by_suffix(tmp_path):
    _write_copyjob_yaml(tmp_path, "cpj_x_1")
    _write_copyjob_yaml(tmp_path, "cpj_x_2")
    entries = bulk.load_bulk_definitions(tmp_path)
    dups = bulk.detect_duplicates(entries)
    assert any(d["type"] == "suffix_name" and d["base"] == "cpj_x" for d in dups)


def test_detect_duplicates_by_signature(tmp_path):
    _write_copyjob_yaml(tmp_path, "cpj_a", source_signature="ORACLE:T1->LH:t1")
    _write_copyjob_yaml(tmp_path, "cpj_b", source_signature="ORACLE:T1->LH:t1")
    entries = bulk.load_bulk_definitions(tmp_path)
    dups = bulk.detect_duplicates(entries)
    assert any(d["type"] == "same_source_dest_signature" for d in dups)


def test_bulk_plan_without_client_marks_everything_create(tmp_path):
    _write_copyjob_yaml(tmp_path, "cpj_a")
    result = bulk.bulk_plan(None, tmp_path, fabric_client=None)
    assert not result.live_compared
    assert all(e.action == "create" for e in result.entries)


def test_bulk_dry_run_detects_staleness(tmp_path):
    _write_copyjob_yaml(tmp_path, "cpj_a", definition_file="def.json")
    result = bulk.bulk_plan(None, tmp_path, fabric_client=None)
    # muda o conteúdo do arquivo depois do plano -> hash diverge
    (tmp_path / "def.json").write_text(json.dumps({"a": 2}), encoding="utf-8")
    issues = bulk.bulk_dry_run(result)
    assert any(i.level == "error" and "staleness" in i.message for i in issues)


def test_bulk_dry_run_ok_when_unchanged(tmp_path):
    _write_copyjob_yaml(tmp_path, "cpj_a")
    result = bulk.bulk_plan(None, tmp_path, fabric_client=None)
    issues = bulk.bulk_dry_run(result)
    assert not any(i.level == "error" for i in issues)


def test_bulk_apply_blocked_without_confirm_write(tmp_path, tmp_profile):
    _write_copyjob_yaml(tmp_path, "cpj_a")
    result = bulk.bulk_plan(tmp_profile, tmp_path, fabric_client=None)
    gate = GateContext(profile=tmp_profile)
    with pytest.raises(SecurityError):
        bulk.bulk_apply(tmp_profile, result, gate, confirm_write=False)


def test_bulk_apply_manual_required_without_fabric_client(tmp_path, tmp_profile):
    tmp_profile.microsoft.allow_write = True
    _write_copyjob_yaml(tmp_path, "cpj_a")
    result = bulk.bulk_plan(tmp_profile, tmp_path, fabric_client=None)
    gate = GateContext(profile=tmp_profile)
    outcome = bulk.bulk_apply(tmp_profile, result, gate, confirm_write=True, fabric_client=None)
    assert outcome["results"]["cpj_a"]["status"] == "manual_required"


def test_bulk_apply_aborts_on_stale_plan(tmp_path, tmp_profile):
    tmp_profile.microsoft.allow_write = True
    _write_copyjob_yaml(tmp_path, "cpj_a", definition_file="def.json")
    result = bulk.bulk_plan(tmp_profile, tmp_path, fabric_client=None)
    (tmp_path / "def.json").write_text(json.dumps({"changed": True}), encoding="utf-8")
    gate = GateContext(profile=tmp_profile)
    with pytest.raises(SecurityError, match="abortado"):
        bulk.bulk_apply(tmp_profile, result, gate, confirm_write=True, fabric_client=None)


def test_bulk_reconcile_without_client_is_explicit(tmp_path):
    _write_copyjob_yaml(tmp_path, "cpj_a")
    result = bulk.bulk_reconcile(None, tmp_path, fabric_client=None)
    assert result["live_compared"] is False
    assert "manual_required" in result["note"]


class _FakeFabricClient:
    """Mock local (sem HTTP) para provar a lógica de poll_job_status."""
    def __init__(self, status_sequence):
        self._sequence = list(status_sequence)
        self.calls = 0

    def job_instance_status(self, item_id, job_instance_id):
        self.calls += 1
        status = self._sequence[min(self.calls - 1, len(self._sequence) - 1)]
        return {"status": status, "itemId": item_id, "id": job_instance_id}


# ==================== execute status polling ====================

def test_poll_job_status_single_check_no_wait():
    client = _FakeFabricClient(["InProgress"])
    result = poll_job_status(client, "item1", "job1", wait=False)
    assert result["status"] == "InProgress"
    assert result["terminal"] is False
    assert client.calls == 1


def test_poll_job_status_waits_until_terminal():
    client = _FakeFabricClient(["InProgress", "InProgress", "Completed"])
    result = poll_job_status(client, "item1", "job1", wait=True, poll_seconds=0.01, timeout_seconds=5)
    assert result["status"] == "Completed"
    assert result["terminal"] is True
    assert client.calls == 3


def test_poll_job_status_times_out():
    client = _FakeFabricClient(["InProgress"])
    result = poll_job_status(client, "item1", "job1", wait=True, poll_seconds=0.01, timeout_seconds=0.05)
    assert result["status"] == "TIMEOUT"
    assert result["terminal"] is False


def test_terminal_statuses_include_failed_and_cancelled():
    assert "Failed" in TERMINAL_STATUSES
    assert "Cancelled" in TERMINAL_STATUSES
    assert "Completed" in TERMINAL_STATUSES
