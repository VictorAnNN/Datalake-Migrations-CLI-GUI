"""Testes da feature de Linhagem do Lakehouse (integração Skill-LineageFabric):
parsing de notebooks, expansão transitiva, trilha SharePoint, persistência em
state.py e o grafo isolado (Mapa Isolado)."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from dlctl.core import lineage_graph
from dlctl.core import state as state_db
from dlctl.generators.lineage_generator import (
    build_sharepoint_dependency_trail,
    build_workspace_inventory,
    dependency_rows_from_dataframe,
    expand_transitive_lineage,
    export_lineage_excel,
    find_latest_lineage_excel,
    generate_lineage_artifacts,
    process_lakehouse_dev,
)


def _write_silver_notebook(root: Path, domain: str) -> None:
    nb_dir = root / domain / "silver_notebooks" / "nb_silver"
    nb_dir.mkdir(parents=True, exist_ok=True)
    (nb_dir / "notebook-content.py").write_text(
        """
WORKSPACE_NAME = "LAKEHOUSE-DEV"
TARGET_LAKEHOUSE_LOGICAL = "LH_SUPRIMENTOS"
TARGET_SCHEMA = "silver"
SILVER_TABLE = "DW_RECEIPT_ORDER_CF"
WRITE_MODE = "overwrite"
BRONZE_SOURCES = [
    {"lakehouse": "LH_SUPRIMENTOS", "schema": "bronze", "table": "RCV_SHIPMENT_HEADERS"},
    {"lakehouse": "LH_SUPRIMENTOS", "schema": "bronze", "table": "RCV_SHIPMENT_LINES"},
]
""",
        encoding="utf-8",
    )


def _write_gold_notebook(root: Path, domain: str) -> None:
    nb_dir = root / domain / "gold_notebooks" / "nb_gold"
    nb_dir.mkdir(parents=True, exist_ok=True)
    (nb_dir / "notebook-content.py").write_text(
        """
WORKSPACE_NAME = "LAKEHOUSE-DEV"
# G1_HEADER_METADATA
GOLD_LAKEHOUSE_LOGICAL = "LH_SUPRIMENTOS"
GOLD_SCHEMA = "gold"
GOLD_TABLE = "PR_RECEIPT_ORDER"
DEPENDENCIES = [
    {"layer": "silver", "lakehouse": "LH_SUPRIMENTOS", "schema": "silver", "table": "DW_RECEIPT_ORDER_CF"},
]
""",
        encoding="utf-8",
    )


@pytest.fixture()
def lakehouse_dev_fixture(tmp_path):
    root = tmp_path / "lakehouse-dev"
    _write_silver_notebook(root, "SUPRIMENTOS")
    _write_gold_notebook(root, "SUPRIMENTOS")
    return root


def test_process_lakehouse_dev_parses_silver_and_gold(lakehouse_dev_fixture):
    result = process_lakehouse_dev(str(lakehouse_dev_fixture))
    linhagem = result["linhagem"]
    assert len(linhagem) == 3  # 2 bronze->silver + 1 silver->gold

    silver_rows = [r for r in linhagem if r["CAMADA_DESTINO"] == "silver"]
    assert {r["TABELA_ORIGEM"] for r in silver_rows} == {"RCV_SHIPMENT_HEADERS", "RCV_SHIPMENT_LINES"}
    assert all(r["TABELA_DESTINO"] == "DW_RECEIPT_ORDER_CF" for r in silver_rows)

    gold_rows = [r for r in linhagem if r["CAMADA_DESTINO"] == "gold"]
    assert len(gold_rows) == 1
    assert gold_rows[0]["TABELA_ORIGEM"] == "DW_RECEIPT_ORDER_CF"
    assert gold_rows[0]["TABELA_DESTINO"] == "PR_RECEIPT_ORDER"


def test_process_lakehouse_dev_empty_dir_returns_empty(tmp_path):
    result = process_lakehouse_dev(str(tmp_path / "does-not-exist"))
    assert result == {"tabelas": [], "linhagem": []}


def test_expand_transitive_lineage_bridges_bronze_to_gold(lakehouse_dev_fixture):
    linhagem = process_lakehouse_dev(str(lakehouse_dev_fixture))["linhagem"]
    expanded = expand_transitive_lineage(linhagem)

    transitive_rows = [r for r in expanded if r.get("_is_transitive")]
    assert len(transitive_rows) == 2  # os 2 bronzes agora também apontam direto para gold
    for row in transitive_rows:
        assert row["CAMADA_ORIGEM"] == "bronze"
        assert row["CAMADA_DESTINO"] == "gold"
        assert row["TABELA_DESTINO"] == "PR_RECEIPT_ORDER"
        assert "[TRANSITIVA]" in row["OBSERVACAO"]

    # relações diretas continuam intactas
    direct_rows = [r for r in expanded if not r.get("_is_transitive")]
    assert len(direct_rows) == 3


def test_expand_transitive_lineage_empty_input_is_empty():
    assert expand_transitive_lineage([]) == []


def _write_sharepoint_workspace_json(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "datasourceInstances": [],
        "workspaces": [
            {
                "id": "ws-1",
                "name": "SUPRIMENTOS WS",
                "datasets": [
                    {
                        "id": "ds-1",
                        "name": "Dataset Recebimento",
                        "tables": [
                            {
                                "name": "TabelaRecebimento",
                                "source": [{
                                    "expression": (
                                        'let\n Source = SharePoint.Files('
                                        '"https://contoso.sharepoint.com/sites/Suprimentos")\nin Source'
                                    )
                                }],
                            }
                        ],
                    }
                ],
                "reports": [
                    {"id": "rpt-1", "name": "Dashboard Recebimento", "datasetId": "ds-1"},
                    {"id": "rpt-2", "name": "Dashboard Orfao", "datasetId": "ds-missing"},
                ],
            }
        ],
    }
    (root / "workspace1.json").write_text(json.dumps(payload), encoding="utf-8")


def test_build_sharepoint_dependency_trail_detects_direct_and_report_chain(tmp_path):
    workspaces_root = tmp_path / "Workspaces"
    _write_sharepoint_workspace_json(workspaces_root)

    rows = build_sharepoint_dependency_trail(str(workspaces_root))

    direct = [r for r in rows if r["chain_depth"] == 0 and r["report_name"] == ""]
    assert len(direct) == 1
    assert direct[0]["exists_check"] == "existe"
    assert direct[0]["sharepoint_reference"] == "https://contoso.sharepoint.com/sites/Suprimentos"

    via_report = [r for r in rows if r["report_name"] == "Dashboard Recebimento"]
    assert len(via_report) == 1
    assert via_report[0]["exists_check"] == "existe"
    assert via_report[0]["chain_depth"] == 1

    orphan = [r for r in rows if r["report_name"] == "Dashboard Orfao"]
    assert len(orphan) == 1
    assert orphan[0]["exists_check"] == "nao_encontrado"


def test_build_sharepoint_dependency_trail_missing_root_returns_empty(tmp_path):
    assert build_sharepoint_dependency_trail(str(tmp_path / "missing")) == []


def test_build_workspace_inventory_flattens_all_item_types(tmp_path):
    workspaces_root = tmp_path / "Workspaces"
    _write_sharepoint_workspace_json(workspaces_root)

    rows = build_workspace_inventory(str(workspaces_root))
    by_type = {}
    for row in rows:
        by_type.setdefault(row["item_type"], []).append(row)

    assert len(by_type["Workspace"]) == 1
    assert by_type["Workspace"][0]["item_name"] == "SUPRIMENTOS WS"
    assert by_type["Workspace"][0]["workspace_id"] == "ws-1"

    assert len(by_type["Dataset"]) == 1
    assert by_type["Dataset"][0]["item_name"] == "Dataset Recebimento"
    assert "table_count=1" in by_type["Dataset"][0]["detail"]

    assert len(by_type["Dataset Table"]) == 1
    assert by_type["Dataset Table"][0]["item_name"] == "TabelaRecebimento"
    assert by_type["Dataset Table"][0]["parent_name"] == "Dataset Recebimento"

    assert len(by_type["Report"]) == 2
    report_names = {r["item_name"] for r in by_type["Report"]}
    assert report_names == {"Dashboard Recebimento", "Dashboard Orfao"}
    assert all(r["workspace"] == "SUPRIMENTOS WS" for r in rows)


def test_build_workspace_inventory_missing_root_returns_empty(tmp_path):
    assert build_workspace_inventory(str(tmp_path / "missing")) == []


def test_generate_lineage_artifacts_persists_workspace_inventory(tmp_profile, lakehouse_dev_fixture, tmp_path):
    workspaces_root = tmp_path / "Workspaces"
    _write_sharepoint_workspace_json(workspaces_root)

    result = generate_lineage_artifacts(
        tmp_profile, lakehouse_dev_input=str(lakehouse_dev_fixture), workspaces_input=str(workspaces_root),
    )

    assert result["workspace_item_rows"] > 0
    items = state_db.get_lineage_workspace_items(tmp_profile, result["batch_id"])
    assert len(items) == result["workspace_item_rows"]
    assert any(i.item_type == "Report" and i.item_name == "Dashboard Recebimento" for i in items)

    batch = state_db.latest_lineage_batch(tmp_profile)
    assert batch.workspace_item_rows == result["workspace_item_rows"]


def test_generate_lineage_artifacts_persists_and_exports(tmp_profile, lakehouse_dev_fixture, tmp_path):
    workspaces_root = tmp_path / "Workspaces"
    _write_sharepoint_workspace_json(workspaces_root)

    result = generate_lineage_artifacts(
        tmp_profile,
        lakehouse_dev_input=str(lakehouse_dev_fixture),
        workspaces_input=str(workspaces_root),
    )

    assert result["dependency_rows"] == 5  # 3 diretas + 2 transitivas
    assert result["sharepoint_rows"] == 3
    assert result["excel_path"] and Path(result["excel_path"]).exists()

    batch = state_db.latest_lineage_batch(tmp_profile)
    assert batch is not None
    assert batch.batch_id == result["batch_id"]
    assert batch.status == "success"

    dependencies = state_db.get_lineage_dependencies(tmp_profile, result["batch_id"])
    assert len(dependencies) == 5
    assert any(dep.is_transitive for dep in dependencies)

    sharepoint_rows = state_db.get_lineage_sharepoint(tmp_profile, result["batch_id"])
    assert {row.exists_check for row in sharepoint_rows} == {"existe", "nao_encontrado"}


def test_generate_lineage_artifacts_without_workspaces_input_skips_sharepoint(tmp_profile, lakehouse_dev_fixture):
    result = generate_lineage_artifacts(
        tmp_profile, lakehouse_dev_input=str(lakehouse_dev_fixture), workspaces_input=None,
    )
    assert result["sharepoint_rows"] == 0


def test_lineage_graph_isolate_upstream_and_downstream(lakehouse_dev_fixture):
    linhagem = process_lakehouse_dev(str(lakehouse_dev_fixture))["linhagem"]
    expanded = expand_transitive_lineage(linhagem)

    dependency_dicts = [{
        "source_layer": r["CAMADA_ORIGEM"], "source_lakehouse": r["LAKEHOUSE_ORIGEM"],
        "source_schema": r["SCHEMA_ORIGEM"], "source_table": r["TABELA_ORIGEM"],
        "target_layer": r["CAMADA_DESTINO"], "target_lakehouse": r["LAKEHOUSE_DESTINO"],
        "target_schema": r["SCHEMA_DESTINO"], "target_table": r["TABELA_DESTINO"],
        "dependency_type": r["TIPO_DEPENDENCIA"], "domain": r.get("Domínio", ""), "note": r.get("OBSERVACAO", ""),
    } for r in expanded]

    graph = lineage_graph.build_dependency_graph(dependency_dicts)

    gold_node = lineage_graph.layer_node_id("gold", "LH_SUPRIMENTOS", "gold", "PR_RECEIPT_ORDER")
    upstream = lineage_graph.isolate_nodes(graph, [gold_node], direction="Upstream")
    summary = lineage_graph.summarize_by_layer(upstream)
    assert "RCV_SHIPMENT_HEADERS" in summary["bronze"]
    assert "RCV_SHIPMENT_LINES" in summary["bronze"]
    assert "DW_RECEIPT_ORDER_CF" in summary["silver"]
    assert "PR_RECEIPT_ORDER" in summary["gold"]

    bronze_node = lineage_graph.layer_node_id("bronze", "LH_SUPRIMENTOS", "bronze", "RCV_SHIPMENT_HEADERS")
    downstream = lineage_graph.isolate_nodes(graph, [bronze_node], direction="Downstream")
    downstream_summary = lineage_graph.summarize_by_layer(downstream)
    assert "PR_RECEIPT_ORDER" in downstream_summary["gold"]


def test_lineage_graph_find_nodes_by_term(lakehouse_dev_fixture):
    linhagem = process_lakehouse_dev(str(lakehouse_dev_fixture))["linhagem"]
    dependency_dicts = [{
        "source_layer": r["CAMADA_ORIGEM"], "source_lakehouse": r["LAKEHOUSE_ORIGEM"],
        "source_schema": r["SCHEMA_ORIGEM"], "source_table": r["TABELA_ORIGEM"],
        "target_layer": r["CAMADA_DESTINO"], "target_lakehouse": r["LAKEHOUSE_DESTINO"],
        "target_schema": r["SCHEMA_DESTINO"], "target_table": r["TABELA_DESTINO"],
        "dependency_type": r["TIPO_DEPENDENCIA"],
    } for r in linhagem]
    graph = lineage_graph.build_dependency_graph(dependency_dicts)

    matches = lineage_graph.find_nodes_by_term(graph, "dw_receipt_order_cf")
    assert len(matches) == 1
    assert graph.nodes[matches[0]]["table"] == "DW_RECEIPT_ORDER_CF"


def test_dependency_rows_from_dataframe_builds_full_graph(lakehouse_dev_fixture):
    """A pagina Grafo Isolado le o Excel exportado; garante que o DataFrame
    reconstruido a partir dele produz o mesmo grafo que o batch original,
    incluindo deteccao de relacoes transitivas pela tag em OBSERVACAO."""
    linhagem = process_lakehouse_dev(str(lakehouse_dev_fixture))["linhagem"]
    expanded = expand_transitive_lineage(linhagem)

    from dlctl.generators.lineage_generator import COLS_LINEAGE_TABLES

    df = pd.DataFrame(expanded, columns=COLS_LINEAGE_TABLES)
    rows = dependency_rows_from_dataframe(df)

    assert len(rows) == len(expanded)
    transitive_count = sum(1 for r in rows if r["is_transitive"])
    assert transitive_count == 2

    graph = lineage_graph.build_dependency_graph(rows)
    gold_node = lineage_graph.layer_node_id("gold", "LH_SUPRIMENTOS", "gold", "PR_RECEIPT_ORDER")
    upstream = lineage_graph.isolate_nodes(graph, [gold_node], direction="Upstream")
    summary = lineage_graph.summarize_by_layer(upstream)
    assert "RCV_SHIPMENT_HEADERS" in summary["bronze"]
    assert "DW_RECEIPT_ORDER_CF" in summary["silver"]


def test_dependency_rows_from_dataframe_empty_returns_empty():
    from dlctl.generators.lineage_generator import COLS_LINEAGE_TABLES

    empty_df = pd.DataFrame(columns=COLS_LINEAGE_TABLES)
    assert dependency_rows_from_dataframe(empty_df) == []


def test_find_latest_lineage_excel_picks_most_recent(tmp_profile):
    lineage_dir = tmp_profile.paths.manifests_root / "lineage"
    lineage_dir.mkdir(parents=True, exist_ok=True)

    older = export_lineage_excel([], [], lineage_dir / "lineage_tables_batch_old.xlsx")
    import time
    time.sleep(0.05)
    newer = export_lineage_excel([], [], lineage_dir / "lineage_tables_batch_new.xlsx")

    found = find_latest_lineage_excel(tmp_profile)
    assert found == newer
    assert found != older


def test_find_latest_lineage_excel_missing_dir_returns_none(tmp_profile):
    assert find_latest_lineage_excel(tmp_profile) is None
