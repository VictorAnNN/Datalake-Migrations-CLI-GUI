"""Testes dos geradores de notebooks Silver/Gold e dos validadores de gate."""
from __future__ import annotations

from pathlib import Path

from dlctl.core.mapping import MappingEntry
from dlctl.generators.gold_generator import generate_gold_notebook
from dlctl.generators.gold_generator import write_notebook as write_gold
from dlctl.generators.silver_generator import generate_silver_notebook
from dlctl.generators.silver_generator import write_notebook as write_silver
from dlctl.generators.validators import validate_gold_notebook, validate_silver_notebook

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_generate_and_validate_silver_notebook(tmp_path):
    entry = MappingEntry(
        domain="ORDER_TRACKING", layer="bronze_to_silver",
        source_table="BRZ_PO_HEADERS_ALL", target_table="SLV_PO_HEADERS",
        sql_file="sql/po_headers.sql", schema_file="schema/slv_po_headers.tab", status="spark_ready",
    )
    nb = generate_silver_notebook(entry, "Files/Bronze", "Tables/silver", project_root=PROJECT_ROOT)
    out_path = tmp_path / "SLV_PO_HEADERS.ipynb"
    write_silver(nb, out_path)

    outcome = validate_silver_notebook(out_path)
    assert outcome.ok, outcome.errors


def test_silver_notebook_rejects_pandas_injection(tmp_path):
    entry = MappingEntry(
        domain="X", layer="bronze_to_silver", source_table="A", target_table="B",
        sql_file="", schema_file="", status="spark_ready",
    )
    nb = generate_silver_notebook(entry, "Files/Bronze", "Tables/silver", project_root=PROJECT_ROOT)
    # injeta uma célula com pandas para provar que o validador pega
    import nbformat as nbf
    bad_cell = nbf.v4.new_code_cell(source="import pandas as pd")
    bad_cell["id"] = "bad0001"
    bad_cell["source"] = ["import pandas as pd"]
    nb["cells"].append(bad_cell)
    out_path = tmp_path / "B.ipynb"
    write_silver(nb, out_path)
    outcome = validate_silver_notebook(out_path)
    assert not outcome.ok
    assert any("pandas" in e.lower() for e in outcome.errors)


def test_generate_and_validate_gold_notebook(tmp_path):
    entry = MappingEntry(
        domain="ORDER_TRACKING", layer="silver_to_gold",
        source_table="SLV_PO_HEADERS", target_table="GLD_PR_REQUISITION",
        sql_file="sql/gold_pr_requisition.sql", schema_file="", status="spark_ready",
    )
    nb = generate_gold_notebook(entry, "Tables/silver", "Tables/gold", project_root=PROJECT_ROOT)
    out_path = tmp_path / "GLD_PR_REQUISITION.ipynb"
    write_gold(nb, out_path)

    outcome = validate_gold_notebook(out_path)
    assert outcome.ok, outcome.errors


def test_gold_notebook_rejects_empty_silver_path():
    entry = MappingEntry(
        domain="X", layer="silver_to_gold", source_table="A", target_table="B",
        sql_file="", schema_file="", status="spark_ready",
    )
    try:
        generate_gold_notebook(entry, "", "Tables/gold", project_root=PROJECT_ROOT)
        assert False, "deveria ter levantado ValueError para SILVER_PATH vazio"
    except ValueError as exc:
        assert "vazio" in str(exc)


def test_gold_notebook_rejects_placeholder_sql(tmp_path):
    entry = MappingEntry(
        domain="X", layer="silver_to_gold", source_table="A", target_table="B",
        sql_file="does_not_exist.sql", schema_file="", status="spark_ready",
    )
    nb = generate_gold_notebook(entry, "Tables/silver", "Tables/gold", project_root=PROJECT_ROOT)
    out_path = tmp_path / "B.ipynb"
    write_gold(nb, out_path)
    outcome = validate_gold_notebook(out_path)
    assert not outcome.ok
    assert any("placeholder" in e.lower() for e in outcome.errors)
