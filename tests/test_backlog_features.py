"""Testes offline dos novos módulos do backlog (fabric-fullctl-backlog.zip):
copyjob_audit, definitions_inspect, log_classifier, leases, campaign.
Nenhum destes testes faz qualquer chamada de rede."""
from __future__ import annotations

import base64
import json

import pytest

from dlctl.core.campaign import CampaignManifest, _topological_order, load_campaign_manifest, run_campaign
from dlctl.core.copyjob_audit import mappings_inspect, oracle_number_audit
from dlctl.core.definitions_inspect import part_inspect
from dlctl.core.log_classifier import classify_log
from dlctl.core.state import acquire_lease, has_conflicting_lease, list_leases, release_lease


# ==================== copyjob_audit ====================

def _write_copyjob_definition(tmp_path, tables):
    data = {"properties": {"tableMappings": tables}}
    path = tmp_path / "copyjob-content.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_mappings_inspect_lists_tables_and_columns(tmp_path):
    path = _write_copyjob_definition(tmp_path, [
        {"sourceTableName": "T1", "columnMappings": [{"sourceColumnName": "C1", "sourceType": "NUMBER(10,0)"}]},
    ])
    result = mappings_inspect(path)
    assert result["table_count"] == 1
    assert result["tables"][0]["column_count"] == 1


def test_oracle_number_audit_flags_bare_number_without_cast(tmp_path):
    path = _write_copyjob_definition(tmp_path, [
        {"sourceTableName": "T1", "columnMappings": [
            {"sourceColumnName": "C1", "sourceType": "NUMBER"},
            {"sourceColumnName": "C2", "sourceType": "NUMBER(10,0)"},
        ]},
    ])
    outcome = oracle_number_audit(path)  # fallback mode: sem schema export (warning, não bloqueia)
    assert outcome.ok  # fallback só gera warning, não error
    assert any(i.column == "C1" and i.severity == "warning" for i in outcome.issues)
    assert not any(i.column == "C2" for i in outcome.issues)


def test_oracle_number_audit_with_schema_export_detects_unmapped(tmp_path):
    copyjob_path = _write_copyjob_definition(tmp_path, [
        {"sourceTableName": "T1", "columnMappings": [{"sourceColumnName": "C1", "sourceType": "NUMBER(10,0)"}]},
    ])
    schema_path = tmp_path / "schema_export.json"
    schema_path.write_text(json.dumps([
        {"table": "T1", "column": "C1", "data_type": "NUMBER(10,0)"},
        {"table": "T1", "column": "C2", "data_type": "NUMBER"},  # não mapeado
        {"table": "T2", "column": "C3", "data_type": "NUMBER"},  # tabela não mapeada
    ]), encoding="utf-8")
    outcome = oracle_number_audit(copyjob_path, schema_path)
    assert not outcome.ok
    assert "T2" in outcome.unmapped_tables
    assert any(c["column"] == "C2" for c in outcome.unmapped_columns)


def test_oracle_number_audit_ok_when_all_mapped_and_typed(tmp_path):
    copyjob_path = _write_copyjob_definition(tmp_path, [
        {"sourceTableName": "T1", "columnMappings": [{"sourceColumnName": "C1", "sourceType": "NUMBER(10,0)"}]},
    ])
    schema_path = tmp_path / "schema_export.json"
    schema_path.write_text(json.dumps([{"table": "T1", "column": "C1", "data_type": "NUMBER(10,0)"}]), encoding="utf-8")
    outcome = oracle_number_audit(copyjob_path, schema_path)
    assert outcome.ok


# ==================== definitions_inspect ====================

def test_part_inspect_computes_three_distinct_hashes(tmp_path):
    inner_content = json.dumps({"properties": {"activities": [{"name": "a1"}], "parameters": {"P1": {}}}})
    payload_b64 = base64.b64encode(inner_content.encode()).decode()
    definition_payload = {"definition": {"parts": [
        {"path": "pipeline-content.json", "payload": payload_b64, "payloadType": "InlineBase64"}
    ]}}
    path = tmp_path / "definition.json"
    path.write_text(json.dumps(definition_payload), encoding="utf-8")

    result = part_inspect(path)
    assert result["aggregateDefinitionSha256"]
    part = result["parts"][0]
    assert part["encodedPayloadSha256"] != part["decodedContentSha256"]
    assert result["semantic_summary"]["activity_count"] == 1
    assert result["semantic_summary"]["parameters"] == ["P1"]


# ==================== log_classifier ====================

def test_classify_log_marks_unknown_as_never_pass():
    outcome = classify_log("some totally unrecognized line of text")
    assert outcome.overall == "NEVER_PASS"
    assert len(outcome.unknown_lines) == 1


def test_classify_log_interrupted_exception_passes_after_completed():
    log_text = "job Completed\nInterruptedException during shutdown"
    outcome = classify_log(log_text)
    assert outcome.overall == "PASS"


def test_classify_log_interrupted_exception_fails_before_completed():
    log_text = "InterruptedException before anything finished"
    outcome = classify_log(log_text)
    assert outcome.overall == "FAIL"


def test_classify_log_known_error_signature_fails():
    outcome = classify_log("Traceback (most recent call last):\nOutOfMemoryError")
    assert outcome.overall == "FAIL"


# ==================== leases ====================

def test_acquire_lease_then_conflict_then_release(tmp_profile):
    result = acquire_lease(tmp_profile, workspace="WS", item_ids=[], tables=["T1"], owner="agent-a", ttl_seconds=3600)
    assert result["ok"]
    lease_id = result["lease_id"]

    conflict = has_conflicting_lease(tmp_profile, item_ids=[], tables=["T1"], owner="agent-b")
    assert conflict == lease_id

    no_conflict_same_owner = has_conflicting_lease(tmp_profile, item_ids=[], tables=["T1"], owner="agent-a")
    assert no_conflict_same_owner is None

    release_result = release_lease(tmp_profile, lease_id, "agent-b")
    assert not release_result["ok"]  # dono errado

    release_result_ok = release_lease(tmp_profile, lease_id, "agent-a")
    assert release_result_ok["ok"]

    conflict_after_release = has_conflicting_lease(tmp_profile, item_ids=[], tables=["T1"], owner="agent-b")
    assert conflict_after_release is None


def test_acquire_lease_blocks_second_agent_on_same_table(tmp_profile):
    r1 = acquire_lease(tmp_profile, workspace="WS", item_ids=[], tables=["T1"], owner="agent-a")
    assert r1["ok"]
    r2 = acquire_lease(tmp_profile, workspace="WS", item_ids=[], tables=["T1"], owner="agent-b")
    assert not r2["ok"]
    assert r2["conflict"] == r1["lease_id"]


# ==================== campaign ====================

def _write_campaign_manifest(tmp_path, targets_yaml):
    import yaml
    path = tmp_path / "campaign.yaml"
    path.write_text(yaml.safe_dump({"campaign_id": "c1", "targets": targets_yaml}), encoding="utf-8")
    return path


def test_topological_order_respects_dependencies():
    manifest = CampaignManifest(campaign_id="c1", targets=[
        {"name": "b", "depends_on": ["a"]},
        {"name": "a", "depends_on": []},
    ])
    order = _topological_order(manifest.targets)
    assert order.index("a") < order.index("b")


def test_topological_order_detects_cycle():
    manifest = CampaignManifest(campaign_id="c1", targets=[
        {"name": "a", "depends_on": ["b"]},
        {"name": "b", "depends_on": ["a"]},
    ])
    with pytest.raises(ValueError):
        _topological_order(manifest.targets)


def test_run_campaign_offline_seals_independent_targets(tmp_path, tmp_profile):
    path = _write_campaign_manifest(tmp_path, [
        {"name": "t1", "depends_on": []},
        {"name": "t2", "depends_on": []},
    ])
    result = run_campaign(tmp_profile, path, confirm_write=False, confirm_execute=False, fabric_client=None)
    assert result["status"] == "success"
    assert result["targets"]["t1"]["status"] == "success"
    assert result["targets"]["t2"]["status"] == "success"


def test_run_campaign_blocks_dependent_target_when_dependency_fails(tmp_path, tmp_profile):
    path = _write_campaign_manifest(tmp_path, [
        {"name": "t1", "manifest": str(tmp_path / "does_not_exist.yaml"), "depends_on": []},
        {"name": "t2", "depends_on": ["t1"]},
    ])
    result = run_campaign(tmp_profile, path, confirm_write=False, confirm_execute=False, fabric_client=None)
    assert result["status"] == "failed"
    assert result["targets"]["t1"]["status"] == "failed"
    assert result["targets"]["t2"]["status"] == "blocked"
