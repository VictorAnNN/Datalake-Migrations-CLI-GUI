"""Testes do motor de manifests (dlctl.core.manifest)."""
from __future__ import annotations

import json

import pytest
import yaml

from dlctl.core import manifest as manifest_engine
from dlctl.core.gates import GateContext, SecurityError


def _write_manifest(tmp_path, **overrides):
    data = {
        "manifest_id": "pp_example_20260702",
        "environment": "DEV",
        "operation": "ensure",
        "owner": "codex",
        "resource_type": "DataPipeline",
        "displayName": "pp_example",
        "description": "",
        "safety": {"allow_write": True, "delete_allowed": False, "allow_move_existing": True},
        "desired_state": {
            "displayName": "pp_example",
            "description": "",
            "folderPath": "pipelines/SUPRIMENTOS",
            "parameters": {},
        },
    }
    data.update(overrides)
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_validate_ok_for_well_formed_manifest(tmp_path):
    path = _write_manifest(tmp_path)
    m = manifest_engine.load_manifest(path)
    result = manifest_engine.validate(m)
    assert result.ok, result.issues


def test_validate_fails_when_allow_write_false(tmp_path):
    path = _write_manifest(tmp_path, safety={"allow_write": False, "delete_allowed": False, "allow_move_existing": False})
    m = manifest_engine.load_manifest(path)
    result = manifest_engine.validate(m)
    assert not result.ok
    assert any("allow_write" in i.message for i in result.issues)


def test_validate_detects_placeholder():
    with pytest.raises(Exception):
        # displayName placeholder deve falhar já na validação pydantic
        manifest_engine.DesiredState(displayName="PLACEHOLDER_NAME")


def test_validate_rejects_untyped_parameters(tmp_path):
    path = _write_manifest(tmp_path, desired_state={
        "displayName": "pp_example", "description": "", "folderPath": "pipelines/SUPRIMENTOS",
        "parameters": {"DOMAIN": "SUPRIMENTOS"},  # primitivo, deveria ser {value,type}
    })
    m = manifest_engine.load_manifest(path)
    result = manifest_engine.validate(m)
    assert not result.ok
    assert any("tipado" in i.message for i in result.issues)


def test_plan_without_fabric_client_defaults_to_create(tmp_path):
    path = _write_manifest(tmp_path)
    m = manifest_engine.load_manifest(path)
    result = manifest_engine.plan(m, fabric_client=None)
    assert result.action == "create"


def test_apply_blocked_without_confirm_write(tmp_path, tmp_profile):
    path = _write_manifest(tmp_path)
    m = manifest_engine.load_manifest(path)
    plan_result = manifest_engine.plan(m, fabric_client=None)
    gate = GateContext(profile=tmp_profile)
    with pytest.raises(SecurityError):
        manifest_engine.apply(m, plan_result, gate, confirm_write=False)


def test_apply_manual_required_without_fabric_client(tmp_path, tmp_profile):
    tmp_profile.microsoft.allow_write = True
    path = _write_manifest(tmp_path)
    m = manifest_engine.load_manifest(path)
    plan_result = manifest_engine.plan(m, fabric_client=None)
    gate = GateContext(profile=tmp_profile)
    result = manifest_engine.apply(m, plan_result, gate, confirm_write=True, fabric_client=None)
    assert result["status"] == "manual_required"
