from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from dlctl.core.lineage import apply_lineage_filters, build_lineage_sankey_figure, generate_lineage_artifacts


def _write_sample_scanner_json(root: Path) -> None:
    payload = {
        "workspaces": [
            {
                "id": "ws-1",
                "name": "Workspace A",
                "dataflows": [{"objectId": "df-1", "name": "Dataflow A", "generation": 1}],
                "datasets": [
                    {
                        "id": "ds-1",
                        "name": "Dataset A",
                        "tables": [
                            {
                                "name": "FactSales",
                                "source": [
                                    {
                                        "expression": 'let Source = Oracle.Database("ORCL", [Query="SELECT * FROM FINANCE.SALES"]) in Source'
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }
    (root / "scanner.json").write_text(json.dumps(payload), encoding="utf-8")


def test_generate_lineage_artifacts_creates_three_excels(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _write_sample_scanner_json(input_dir)

    artifacts = generate_lineage_artifacts(input_dir, tmp_path / "out")

    assert artifacts.original_excel.exists()
    assert artifacts.simplified_excel.exists()
    assert artifacts.detailed_excel.exists()

    original = pd.ExcelFile(artifacts.original_excel)
    assert "Lineage Simplified" in original.sheet_names
    lineage_df = original.parse("Lineage Simplified")
    assert not lineage_df.empty
    assert "dependency_type" in lineage_df.columns


def test_lineage_filters_and_graph(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _write_sample_scanner_json(input_dir)
    artifacts = generate_lineage_artifacts(input_dir, tmp_path / "out")
    lineage_df = pd.read_excel(artifacts.original_excel, sheet_name="Lineage Simplified")

    filtered = apply_lineage_filters(
        lineage_df,
        workspaces=["Workspace A"],
        datasets=["Dataset A"],
        dependency_types=["Original source"],
    )
    assert len(filtered) >= 1

    fig = build_lineage_sankey_figure(filtered, title="Teste")
    assert len(fig.data) == 1

