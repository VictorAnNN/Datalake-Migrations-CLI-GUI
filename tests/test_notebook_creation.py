from __future__ import annotations

import json
from pathlib import Path

import pytest

from dlctl.connectors.fabric_api import FabricClient
from dlctl.core.notebook_definition import (
    NotebookPlanError,
    build_definition,
    create_plan,
    load_and_verify_plan,
)
from dlctl.generators.silver_generator import generate_silver_notebook, write_notebook
from dlctl.core.mapping import MappingEntry


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _pilot(tmp_path: Path) -> Path:
    entry = MappingEntry(
        domain="ORDER_TRACKING", layer="bronze_to_silver",
        source_table="BRZ_PO_HEADERS_ALL", target_table="SLV_PO_HEADERS",
        sql_file="sql/po_headers.sql", schema_file="schema/slv_po_headers.tab", status="spark_ready",
    )
    path = tmp_path / "pilot.ipynb"
    write_notebook(
        generate_silver_notebook(entry, "Files/Bronze", "Tables/silver", PROJECT_ROOT),
        path,
    )
    return path


def test_definition_uses_official_ipynb_shape(tmp_path):
    definition = build_definition(_pilot(tmp_path))
    assert definition["format"] == "ipynb"
    assert len(definition["parts"]) == 1
    assert definition["parts"][0]["path"] == "notebook-content.ipynb"
    assert definition["parts"][0]["payloadType"] == "InlineBase64"


def test_plan_is_sealed_and_detects_notebook_drift(tmp_path):
    notebook = _pilot(tmp_path)
    plan = create_plan(
        notebook_path=notebook,
        display_name="codex_test_delete_me_notebook_pilot",
        environment="DEV",
        workspace_name="LAKEHOUSE-DEV",
        workspace_id="8d8431e6-ef28-4356-8ca3-6cce6f99e5c4",
        contract="silver",
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    assert load_and_verify_plan(plan_path)["displayName"] == plan["displayName"]
    notebook.write_bytes(notebook.read_bytes() + b" ")
    with pytest.raises(NotebookPlanError, match="mudou"):
        load_and_verify_plan(plan_path)


def test_plan_detects_tamper(tmp_path):
    notebook = _pilot(tmp_path)
    plan = create_plan(
        notebook_path=notebook,
        display_name="original",
        environment="DEV",
        workspace_name="LAKEHOUSE-DEV",
        workspace_id=None,
        contract="silver",
    )
    plan["displayName"] = "adulterado"
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(NotebookPlanError, match="Hash do plano"):
        load_and_verify_plan(plan_path)


def test_create_notebook_uses_specific_route_and_definition(tmp_profile, monkeypatch, tmp_path):
    client = FabricClient(tmp_profile, workspace_id="workspace-id")
    captured = {}

    class Response:
        status_code = 201
        headers = {}
        text = ""

        def json(self):
            return {"id": "notebook-id", "displayName": "pilot", "type": "Notebook"}

    def fake_request(method, path, is_write=False, **kwargs):
        captured.update(method=method, path=path, is_write=is_write, kwargs=kwargs)
        return Response()

    monkeypatch.setattr(client, "_request", fake_request)
    result = client.create_notebook("pilot", build_definition(_pilot(tmp_path)))
    assert result["status"] == "SUCCEEDED"
    assert captured["path"] == "/workspaces/workspace-id/notebooks"
    assert captured["is_write"] is True
    assert captured["kwargs"]["json"]["definition"]["format"] == "ipynb"
