"""dlctl.generators.fabric_lineage_export

Porta os demais artefatos do projeto de referência `Skill-LineageFabric`
(além do `lineage_tables_*.xlsx` / `Tabelas`+`Linhagem Tabelas` já gerado por
`dlctl.generators.lineage_generator`), a partir dos mesmos JSONs do Fabric
Scanner API (`--workspaces-input`):

- ``fabric_lineage_<batch>.xlsx`` — extrato bruto completo (7 abas: Read Me,
  Dataflows Gen1, Datasets, Lineage Simplified, Dataset Tables, PQ Sources,
  Oracle Tables), equivalente a `lineage_extractor.py` do projeto original.
- ``fabric_lineage_simplified_migration_<batch>.xlsx`` — formato enxuto para
  apresentar a migração (4 abas), equivalente a `lineage_formatter.py::create_simplified_migration`.
- ``fabric_lineage_powerquery_detailed_<batch>.xlsx`` — análise técnica das
  expressões Power Query/M (5 abas), equivalente a
  `lineage_formatter.py::create_powerquery_detailed`.
"""
from __future__ import annotations

import base64
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from dlctl.generators.lineage_generator import _load_json_files, _read_json

HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(bold=True, color="FFFFFF", name="Calibri", size=10)
EVEN_FILL = PatternFill("solid", fgColor="DCE6F1")
ODD_FILL = PatternFill("solid", fgColor="FFFFFF")


# ===========================================================================
# 1. Parsing de expressões Power Query / M (mesma lógica de lineage_extractor.py)
# ===========================================================================

def _extract_sql_tables(sql: str) -> list[dict]:
    tables = []
    if not sql:
        return tables
    sql_clean = sql.replace("#(lf)", "\n").replace("\\n", "\n")
    pattern = (
        r'\b(FROM|JOIN|INNER\s+JOIN|LEFT\s+JOIN|RIGHT\s+JOIN|'
        r'FULL\s+JOIN|CROSS\s+JOIN)\s+"?(\w+)"?\."?(\w+)"?'
    )
    for m in re.finditer(pattern, sql_clean, re.IGNORECASE):
        keyword = m.group(1).split()[0].upper()
        tables.append({"schema": m.group(2), "table": m.group(3), "usage": keyword})
    return tables


def _parse_m_expression(expr: str) -> list[dict]:
    if not expr or not expr.strip():
        return []
    sources: list[dict] = []
    expr_clean = expr.replace("#(lf)", "\n").replace('\\"', '"')

    for _ in re.finditer(r'PowerPlatform\.Dataflows', expr_clean, re.IGNORECASE):
        ws_m = re.search(r'workspaceId\s*=\s*"([^"]+)"', expr_clean)
        df_m = re.search(r'dataflowId\s*=\s*"([^"]+)"', expr_clean)
        ent_m = re.search(r'\[#"([^"]+)"\]', expr_clean) or re.search(r'entity\s*=\s*"([^"]+)"', expr_clean)
        sources.append({
            "source_type": "Dataflow Gen1", "server": "", "database": ws_m.group(1) if ws_m else "",
            "schema": "", "table": ent_m.group(1) if ent_m else "", "url": "", "path": "",
            "dataflow_workspace_id": ws_m.group(1) if ws_m else "", "dataflow_id": df_m.group(1) if df_m else "",
            "entity": ent_m.group(1) if ent_m else "", "usage": "", "sql": "", "raw": expr_clean[:400],
        })
        return sources

    for m in re.finditer(
        r'Oracle\.Database\s*\(\s*"([^"]+)"\s*(?:,\s*\[([^\]]*(?:\[[^\]]*\][^\]]*)*)\])?\s*\)',
        expr_clean, re.IGNORECASE | re.DOTALL,
    ):
        server = m.group(1)
        opts = m.group(2) or ""
        sql_m = re.search(r'Query\s*=\s*"((?:[^"\\]|\\.|\n)+)"', opts, re.DOTALL) \
            or re.search(r'Query\s*=\s*"((?:[^"\\]|\\.|\n)+)"', expr_clean, re.DOTALL)
        sql = sql_m.group(1).replace('\\"', '"') if sql_m else ""
        oracle_tables = _extract_sql_tables(sql)
        if oracle_tables:
            for t in oracle_tables:
                sources.append({
                    "source_type": "Oracle", "server": server, "database": "", "schema": t["schema"],
                    "table": t["table"], "url": "", "path": "", "dataflow_workspace_id": "", "dataflow_id": "",
                    "entity": "", "usage": t["usage"], "sql": sql[:600], "raw": m.group(0)[:400],
                })
        else:
            sources.append({
                "source_type": "Oracle", "server": server, "database": "", "schema": "", "table": "",
                "url": "", "path": "", "dataflow_workspace_id": "", "dataflow_id": "", "entity": "",
                "usage": "", "sql": sql[:600], "raw": m.group(0)[:400],
            })

    for m in re.finditer(
        r'Sql\.Database(?:s)?\s*\(\s*"([^"]+)"\s*(?:,\s*"([^"]+)")?\s*(?:,\s*\[([^\]]*)\])?\s*\)',
        expr_clean, re.IGNORECASE | re.DOTALL,
    ):
        server, db, opts = m.group(1), m.group(2) or "", m.group(3) or ""
        sql_m = re.search(r'Query\s*=\s*"((?:[^"\\]|\\.)+)"', opts, re.DOTALL)
        sql = sql_m.group(1).replace('\\"', '"') if sql_m else ""
        sql_tables = _extract_sql_tables(sql)
        if sql_tables:
            for t in sql_tables:
                sources.append({
                    "source_type": "SQL Server", "server": server, "database": db, "schema": t["schema"],
                    "table": t["table"], "url": "", "path": "", "dataflow_workspace_id": "", "dataflow_id": "",
                    "entity": "", "usage": t["usage"], "sql": sql[:600], "raw": m.group(0)[:400],
                })
        else:
            sources.append({
                "source_type": "SQL Server", "server": server, "database": db, "schema": "", "table": "",
                "url": "", "path": "", "dataflow_workspace_id": "", "dataflow_id": "", "entity": "",
                "usage": "", "sql": sql[:600], "raw": m.group(0)[:400],
            })

    for m in re.finditer(r'SharePoint\.\w+\s*\(\s*"([^"]+)"', expr_clean, re.IGNORECASE):
        sources.append({
            "source_type": "SharePoint", "server": "", "database": "", "schema": "", "table": "",
            "url": m.group(1), "path": "", "dataflow_workspace_id": "", "dataflow_id": "", "entity": "",
            "usage": "", "sql": "", "raw": m.group(0)[:400],
        })
    for m in re.finditer(r'Web\.Contents\s*\(\s*"([^"]+)"', expr_clean, re.IGNORECASE):
        sources.append({
            "source_type": "Web/API", "server": "", "database": "", "schema": "", "table": "",
            "url": m.group(1), "path": "", "dataflow_workspace_id": "", "dataflow_id": "", "entity": "",
            "usage": "", "sql": "", "raw": m.group(0)[:400],
        })
    for m in re.finditer(r'OData\.Feed\s*\(\s*"([^"]+)"', expr_clean, re.IGNORECASE):
        sources.append({
            "source_type": "OData", "server": "", "database": "", "schema": "", "table": "",
            "url": m.group(1), "path": "", "dataflow_workspace_id": "", "dataflow_id": "", "entity": "",
            "usage": "", "sql": "", "raw": m.group(0)[:400],
        })
    for m in re.finditer(
        r'(?:Excel\.Workbook|Csv\.Document)\s*\(\s*File\.Contents\s*\(\s*"([^"]+)"', expr_clean, re.IGNORECASE,
    ):
        sources.append({
            "source_type": "Excel/CSV/File", "server": "", "database": "", "schema": "", "table": "",
            "url": "", "path": m.group(1), "dataflow_workspace_id": "", "dataflow_id": "", "entity": "",
            "usage": "", "sql": "", "raw": m.group(0)[:400],
        })
    for m in re.finditer(r'AzureStorage\.\w+\s*\(\s*"([^"]+)"', expr_clean, re.IGNORECASE):
        sources.append({
            "source_type": "Azure Storage", "server": "", "database": "", "schema": "", "table": "",
            "url": m.group(1), "path": "", "dataflow_workspace_id": "", "dataflow_id": "", "entity": "",
            "usage": "", "sql": "", "raw": m.group(0)[:400],
        })
    for m in re.finditer(r'PostgreSQL\.Database\s*\(\s*"([^"]+)"\s*,\s*"([^"]+)"', expr_clean, re.IGNORECASE):
        sources.append({
            "source_type": "PostgreSQL", "server": m.group(1), "database": m.group(2), "schema": "", "table": "",
            "url": "", "path": "", "dataflow_workspace_id": "", "dataflow_id": "", "entity": "",
            "usage": "", "sql": "", "raw": m.group(0)[:400],
        })

    if not sources and expr_clean.strip():
        sources.append({
            "source_type": "Unknown/Other", "server": "", "database": "", "schema": "", "table": "",
            "url": "", "path": "", "dataflow_workspace_id": "", "dataflow_id": "", "entity": "",
            "usage": "", "sql": "", "raw": expr_clean[:400],
        })
    return sources


def _classify_dependency(source_type: str) -> str:
    if source_type == "Dataflow Gen1":
        return "Dataflow Gen1 table"
    if source_type in ("Oracle", "SQL Server", "SharePoint", "Web/API", "OData", "Excel/CSV/File", "Azure Storage", "PostgreSQL"):
        return "Original source"
    return "Unknown/Other"


def _build_as_is(dep_type: str, row: dict) -> str:
    ds, tbl = row.get("dataset_name", "?"), row.get("dataset_table", "?")
    if dep_type == "Dataflow Gen1 table":
        df_name = row.get("source_dataflow_name") or row.get("dataflow_id", "?")
        ent = row.get("entity", "")
        src = f"Dataflow: {df_name}" + (f" / {ent}" if ent else "")
        return f"{src} → Dataset table: {tbl} → Dataset: {ds}"
    if dep_type == "Original source":
        parts = [p for p in [
            row.get("source_type", ""), row.get("server", ""),
            (row.get("schema", "") + "." + row.get("table", "")).strip(".") if row.get("table") else "",
            row.get("url", ""),
        ] if p]
        return " > ".join(parts) + f" → Dataset table: {tbl} → Dataset: {ds}"
    return f"Dataset table: {tbl} → Dataset: {ds}"


def _build_to_be(dep_type: str, row: dict) -> str:
    ds, tbl = row.get("dataset_name", "?"), row.get("dataset_table", "?")
    if dep_type == "Dataflow Gen1 table":
        df_name = row.get("source_dataflow_name") or row.get("dataflow_id", "?")
        ent = row.get("entity", "")
        lake = f"Lake: {row.get('schema', '')}.{row.get('table', '')}".rstrip(".")
        mat = f"Mat. View (ex-Dataflow): {df_name}" + (f".{ent}" if ent else "")
        return f"{lake} → {mat} → Dataset Direct Lake: {ds}"
    if dep_type == "Original source":
        schema, table, src_type = row.get("schema", ""), row.get("table", ""), row.get("source_type", "")
        lake = f"Lake: {schema}.{table}".rstrip(".") if table else f"Lake ({src_type})"
        mat = f"Mat. View (ex-Dataset table): {tbl}"
        return f"{lake} → {mat} → Dataset Direct Lake: {ds}"
    return f"Mat. View: {tbl} → Dataset Direct Lake: {ds}"


# ===========================================================================
# 2. Pipeline principal: JSONs -> 6 DataFrames brutos
# ===========================================================================

def process_workspaces_raw(workspaces_input: str) -> dict[str, pd.DataFrame]:
    """Varre os JSONs do Fabric Scanner API e produz as 6 tabelas brutas do
    extrator original: dataflows, datasets, lineage, dataset_tables,
    pq_sources, oracle_tables."""
    json_files = _load_json_files(workspaces_input)

    dataflows_rows: list[dict] = []
    datasets_rows: list[dict] = []
    lineage_rows: list[dict] = []
    dataset_tables: list[dict] = []
    pq_sources_rows: list[dict] = []
    oracle_rows: list[dict] = []
    df_name_index: dict[str, str] = {}

    for jf in json_files:
        data = _read_json(jf)
        if not data:
            continue

        for ws in data.get("workspaces", []):
            ws_id = ws.get("id", "unknown")
            ws_name = ws.get("name", ws_id)

            for df in ws.get("dataflows", []):
                df_id = df.get("objectId") or df.get("id", "")
                df_name = df.get("name", df_id)
                df_name_index[str(df_id).lower()] = df_name
                dataflows_rows.append({
                    "workspace_name": ws_name, "workspace_id": ws_id, "dataflow_name": df_name,
                    "dataflow_id": str(df_id).lower(), "generation": df.get("generation", 1),
                    "configured_by": df.get("configuredBy", ""), "modified_by": df.get("modifiedBy", ""),
                    "modified_date": df.get("modifiedDateTime", ""),
                })

            for ds in ws.get("datasets", []):
                ds_id = ds.get("id", "")
                ds_name = ds.get("name", ds_id)
                tables = ds.get("tables", [])
                datasets_rows.append({
                    "workspace_name": ws_name, "workspace_id": ws_id, "dataset_name": ds_name,
                    "dataset_id": str(ds_id).lower(), "table_count": len(tables),
                    "configured_by": ds.get("configuredBy", ""),
                    "default_storage_mode": ds.get("targetStorageMode", ""),
                })

                for tbl in tables:
                    tbl_name = tbl.get("name", "")
                    storage = tbl.get("storageMode", "")
                    src_list = tbl.get("source", [])
                    expr = ""
                    if isinstance(src_list, list) and src_list:
                        expr = src_list[0].get("expression", "") or ""
                    elif isinstance(src_list, str):
                        expr = src_list

                    dataset_tables.append({
                        "workspace_name": ws_name, "dataset_name": ds_name, "table_name": tbl_name,
                        "storage_mode": storage, "has_expression": bool(expr.strip()),
                        "expression_preview": expr[:300] if expr else "",
                    })

                    for src in _parse_m_expression(expr):
                        dep_type = _classify_dependency(src["source_type"])
                        src_df_id = src.get("dataflow_id", "")
                        src_df_name = df_name_index.get(src_df_id.lower(), src_df_id) if dep_type == "Dataflow Gen1 table" and src_df_id else ""

                        row = {
                            "workspace_name": ws_name, "workspace_id": ws_id, "dataset_name": ds_name,
                            "dataset_id": str(ds_id).lower(), "dataset_table": tbl_name,
                            "dependency_type": dep_type, "source_type": src["source_type"],
                            "source_dataflow_name": src_df_name, "dataflow_id": src_df_id,
                            "dataflow_workspace_id": src.get("dataflow_workspace_id", ""),
                            "entity": src.get("entity", ""), "server": src.get("server", ""),
                            "schema": src.get("schema", ""), "table": src.get("table", ""),
                            "url": src.get("url", ""), "path": src.get("path", ""),
                            "usage": src.get("usage", ""), "power_query_expression": expr,
                        }
                        row["as_is_path"] = _build_as_is(dep_type, row)
                        row["to_be_path"] = _build_to_be(dep_type, row)
                        lineage_rows.append(row)

                        pq_sources_rows.append({
                            "workspace_name": ws_name, "dataset_or_dataflow": "Dataset", "artifact_name": ds_name,
                            "table_or_entity": tbl_name, "source_type": src["source_type"],
                            "server": src.get("server", ""), "database": src.get("database", ""),
                            "schema": src.get("schema", ""), "table": src.get("table", ""),
                            "url": src.get("url", ""), "path": src.get("path", ""),
                            "raw_expression": src.get("raw", ""),
                        })

                        if src["source_type"] == "Oracle" and src.get("table"):
                            oracle_rows.append({
                                "workspace_name": ws_name, "artifact_name": ds_name, "entity_name": tbl_name,
                                "oracle_server": src.get("server", ""), "oracle_schema": src.get("schema", ""),
                                "oracle_table": src.get("table", ""), "usage_context": src.get("usage", ""),
                                "full_qualified": f"{src.get('schema', '')}.{src.get('table', '')}",
                            })

    return {
        "dataflows": pd.DataFrame(dataflows_rows),
        "datasets": pd.DataFrame(datasets_rows),
        "lineage": pd.DataFrame(lineage_rows),
        "dataset_tables": pd.DataFrame(dataset_tables),
        "pq_sources": pd.DataFrame(pq_sources_rows),
        "oracle_tables": pd.DataFrame(oracle_rows),
    }


# ===========================================================================
# 3. Formatação visual comum
# ===========================================================================

def _autofit_sheet(ws_sheet) -> None:
    for col_idx, col in enumerate(ws_sheet.iter_cols(), start=1):
        col_letter = get_column_letter(col_idx)
        max_len = 0
        for i, cell in enumerate(col):
            if i == 0:
                cell.font = HEADER_FONT
                cell.fill = HEADER_FILL
                cell.alignment = Alignment(horizontal="center", vertical="center")
            else:
                cell.fill = EVEN_FILL if i % 2 == 0 else ODD_FILL
            try:
                max_len = max(max_len, len(str(cell.value)) if cell.value else 0)
            except Exception:
                pass
        ws_sheet.column_dimensions[col_letter].width = min(max(max_len + 4, 12), 80)
    ws_sheet.freeze_panes = "A2"


def _finalize_workbook(output_path: Path) -> None:
    wb = load_workbook(output_path)
    for sheet_name in wb.sheetnames:
        _autofit_sheet(wb[sheet_name])
    wb.save(output_path)


# ===========================================================================
# 4. Formato 1: extrato bruto completo (7 abas)
# ===========================================================================

def write_fabric_lineage_full(data: dict[str, pd.DataFrame], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    all_ws_ids = set()
    for name in ("dataflows", "datasets"):
        if not data[name].empty and "workspace_id" in data[name].columns:
            all_ws_ids.update(data[name]["workspace_id"].dropna().unique())

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        readme = pd.DataFrame({
            "Item": ["Gerado em", "Workspaces únicos", "Dataflows Gen1", "Datasets",
                     "Tabelas de dataset", "Linhas de linhagem", "Fontes PQ únicas", "Tabelas Oracle únicas"],
            "Valor": [
                datetime.now().strftime("%Y-%m-%d %H:%M"), len(all_ws_ids), len(data["dataflows"]),
                len(data["datasets"]), len(data["dataset_tables"]), len(data["lineage"]),
                len(data["pq_sources"]), len(data["oracle_tables"]),
            ],
        })
        readme.to_excel(writer, sheet_name="Read Me", index=False)
        data["dataflows"].to_excel(writer, sheet_name="Dataflows Gen1", index=False)
        data["datasets"].to_excel(writer, sheet_name="Datasets", index=False)

        lineage_cols = [
            "workspace_name", "workspace_id", "dataset_name", "dataset_id", "dataset_table",
            "dependency_type", "source_type", "source_dataflow_name", "dataflow_id",
            "dataflow_workspace_id", "entity", "server", "schema", "table", "url", "path", "usage",
            "as_is_path", "to_be_path", "power_query_expression",
        ]
        df_lin = data["lineage"].reindex(columns=lineage_cols, fill_value="")
        df_lin["power_query_expression"] = df_lin["power_query_expression"].astype(str).str[:32000]
        df_lin.to_excel(writer, sheet_name="Lineage Simplified", index=False)

        data["dataset_tables"].to_excel(writer, sheet_name="Dataset Tables", index=False)
        data["pq_sources"].to_excel(writer, sheet_name="PQ Sources", index=False)
        data["oracle_tables"].to_excel(writer, sheet_name="Oracle Tables", index=False)

    _finalize_workbook(output_path)
    return output_path


# ===========================================================================
# 5. Formato 2: Simplified Migration (4 abas)
# ===========================================================================

def _immediate_source(row: dict) -> str:
    path, url, server, schema, table = row.get("path", ""), row.get("url", ""), row.get("server", ""), row.get("schema", ""), row.get("table", "")
    if path:
        return path
    if url:
        return url
    if server and table:
        return f"{server} → {schema}.{table}" if schema else f"{server} → {table}"
    return server or ""


def _immediate_source_type(row: dict) -> str:
    src_type, dep_type, path = row.get("source_type", ""), row.get("dependency_type", ""), row.get("path", "")
    if dep_type == "Dataflow Gen1 table":
        return "Dataflow Gen1 entity"
    if path and not pd.isna(path):
        return "Excel file" if any(ext in str(path).lower() for ext in ("xlsx", "xls")) else "File"
    if src_type == "Oracle":
        return "Oracle table"
    if src_type == "SQL Server":
        return "SQL Server table"
    if src_type == "SharePoint":
        return "SharePoint"
    if "Web" in str(src_type) or "API" in str(src_type):
        return "Web/API"
    if src_type == "OData":
        return "OData"
    return src_type or "Unknown"


def _source_detail(row: dict) -> str:
    if row.get("url") or row.get("path"):
        return ""
    parts = []
    if row.get("server"):
        parts.append(f"Server: {row['server']}")
    if row.get("schema"):
        parts.append(f"Schema: {row['schema']}")
    if row.get("table"):
        parts.append(f"Table: {row['table']}")
    return " | ".join(parts)


def _simplify_as_is(as_is_path) -> str:
    if not as_is_path or pd.isna(as_is_path):
        return ""
    parts = str(as_is_path).split("→")
    return f"{parts[0].strip()} → {parts[-1].strip()}" if len(parts) >= 2 else as_is_path


def _simplify_to_be(to_be_path) -> str:
    if not to_be_path or pd.isna(to_be_path):
        return ""
    return str(to_be_path).replace(
        "Mat. View (ex-Dataset table)", "Fabric materialized view/direct lake or migrated lake source",
    )


def create_simplified_migration(data: dict[str, pd.DataFrame], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        lineage_df = data["lineage"].copy()
        if lineage_df.empty:
            lineage_df = pd.DataFrame(columns=[
                "workspace_name", "workspace_id", "dataset_name", "dataset_id", "dataset_table",
                "source_type", "dependency_type", "server", "schema", "table", "url", "path",
                "as_is_path", "to_be_path", "power_query_expression",
            ])
        lineage_simplified = pd.DataFrame({
            "Workspace": lineage_df.get("workspace_name", ""),
            "Workspace ID": lineage_df.get("workspace_id", ""),
            "Dataset": lineage_df.get("dataset_name", ""),
            "Dataset ID": lineage_df.get("dataset_id", ""),
            "Dataset Table": lineage_df.get("dataset_table", ""),
            "Immediate Source Type": lineage_df.apply(_immediate_source_type, axis=1) if not lineage_df.empty else [],
            "Immediate Source": lineage_df.apply(_immediate_source, axis=1) if not lineage_df.empty else [],
            "Source Server": lineage_df.get("server", ""),
            "Source Schema": lineage_df.get("schema", ""),
            "Source Table": lineage_df.get("table", ""),
            "Source Detail": lineage_df.apply(_source_detail, axis=1) if not lineage_df.empty else [],
            "AS-IS Path": lineage_df.get("as_is_path", pd.Series(dtype=str)).apply(_simplify_as_is),
            "TO-BE Path": lineage_df.get("to_be_path", pd.Series(dtype=str)).apply(_simplify_to_be),
            "Power Query Expression (truncated)": lineage_df.get("power_query_expression", pd.Series(dtype=str)).astype(str).str[:2000],
        }).fillna("")
        lineage_simplified.to_excel(writer, sheet_name="Lineage Simplified", index=False)

        dataset_tables_df = data["dataset_tables"].copy()
        datasets_df = data["datasets"].copy()
        if not dataset_tables_df.empty and not datasets_df.empty:
            enhanced = dataset_tables_df.merge(
                datasets_df[["workspace_name", "workspace_id", "dataset_name", "dataset_id"]],
                on=["workspace_name", "dataset_name"], how="left",
            )
        else:
            enhanced = dataset_tables_df.assign(workspace_id="", dataset_id="")
        dataset_tables_simplified = pd.DataFrame({
            "Workspace": enhanced.get("workspace_name", ""),
            "Workspace ID": enhanced.get("workspace_id", ""),
            "Dataset": enhanced.get("dataset_name", ""),
            "Dataset ID": enhanced.get("dataset_id", ""),
            "Dataset Table": enhanced.get("table_name", ""),
            "Storage Mode": enhanced.get("storage_mode", ""),
            "Has Source Expression": enhanced.get("has_expression", pd.Series(dtype=bool)).apply(lambda x: "Yes" if x else "No") if not enhanced.empty else [],
        }).fillna("")
        dataset_tables_simplified.to_excel(writer, sheet_name="Dataset Tables", index=False)

        dataflows_df = data["dataflows"].copy()
        empty_dataflow_column = pd.Series(index=dataflows_df.index, dtype=str)
        dataflows_simplified = pd.DataFrame({
            "Workspace": dataflows_df.get("workspace_name", empty_dataflow_column),
            "Workspace ID": dataflows_df.get("workspace_id", empty_dataflow_column),
            "Dataflow Gen1": dataflows_df.get("dataflow_name", empty_dataflow_column),
            "Dataflow ID": dataflows_df.get("dataflow_id", empty_dataflow_column),
            "Generation": dataflows_df.get("generation", empty_dataflow_column),
        }).fillna("")
        dataflows_simplified.to_excel(writer, sheet_name="Dataflows Gen1", index=False)

        readme_df = pd.DataFrame({"Purpose": [
            "Simplified migration lineage for Power BI/Fabric datasets.",
            "Each row traces a dataset table to its immediate source category.",
            "",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Workspaces: {datasets_df['workspace_id'].nunique() if 'workspace_id' in datasets_df.columns else 0}",
            f"Datasets: {len(datasets_df)}",
            f"Lineage entries: {len(lineage_simplified)}",
        ]})
        readme_df.to_excel(writer, sheet_name="Read Me", index=False)

    _finalize_workbook(output_path)
    return output_path


# ===========================================================================
# 6. Formato 3: PowerQuery Detailed (5 abas)
# ===========================================================================

_CONNECTOR_PATTERNS = {
    "Oracle": r"Oracle\.Database", "SQL Server": r"Sql\.Database", "Excel": r"Excel\.Workbook",
    "CSV": r"Csv\.Document", "SharePoint": r"SharePoint\.", "Web": r"Web\.Contents",
    "OData": r"OData\.Feed", "Azure Storage": r"AzureStorage\.", "PostgreSQL": r"PostgreSQL\.Database",
    "Dataflow": r"PowerPlatform\.Dataflows", "File": r"File\.Contents",
}


def _extract_sql_simple(raw_expr) -> str:
    if not raw_expr or pd.isna(raw_expr):
        return ""
    match = re.search(r'Query\s*=\s*"([^"]+)"', str(raw_expr), re.IGNORECASE)
    return match.group(1)[:500] if match else ""


def _extract_connectors(expr) -> str:
    if not expr or pd.isna(expr):
        return ""
    expr_str = str(expr)
    connectors = [name for name, pattern in _CONNECTOR_PATTERNS.items() if re.search(pattern, expr_str, re.IGNORECASE)]
    return "; ".join(connectors)


def _count_source_objects(expr) -> int:
    if not expr or pd.isna(expr):
        return 0
    expr_str = str(expr)
    objects: set[str] = set()
    patterns = [
        (r'(?:FROM|JOIN)\s+"?(\w+)"?\."?(\w+)"?', lambda m: f"{m.group(1)}.{m.group(2)}"),
        (r'File\.Contents\s*\(\s*"([^"]+)"', lambda m: m.group(1)),
        (r'(?:Web\.Contents|SharePoint\.\w+|OData\.Feed)\s*\(\s*"([^"]+)"', lambda m: m.group(1)),
        (r'entity\s*=\s*"([^"]+)"', lambda m: m.group(1)),
    ]
    for pattern, extractor in patterns:
        for match in re.finditer(pattern, expr_str, re.IGNORECASE):
            try:
                objects.add(extractor(match))
            except Exception:
                pass
    return len(objects)


def create_powerquery_detailed(data: dict[str, pd.DataFrame], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        dataflows_df = data["dataflows"].copy()
        empty_dataflow_column = pd.Series(index=dataflows_df.index, dtype=str)
        pd.DataFrame({
            "Workspace": dataflows_df.get("workspace_name", empty_dataflow_column),
            "Workspace ID": dataflows_df.get("workspace_id", empty_dataflow_column),
            "Dataflow": dataflows_df.get("dataflow_name", empty_dataflow_column),
            "Dataflow ID": dataflows_df.get("dataflow_id", empty_dataflow_column),
            "Generation": dataflows_df.get("generation", empty_dataflow_column),
        }).fillna("").to_excel(writer, sheet_name="Dataflows Gen1", index=False)

        datasets_df = data["datasets"].copy()
        empty_dataset_column = pd.Series(index=datasets_df.index, dtype=str)
        pd.DataFrame({
            "Workspace": datasets_df.get("workspace_name", empty_dataset_column),
            "Workspace ID": datasets_df.get("workspace_id", empty_dataset_column),
            "Dataset": datasets_df.get("dataset_name", empty_dataset_column),
            "Dataset ID": datasets_df.get("dataset_id", empty_dataset_column),
            "Table Count": datasets_df.get("table_count", empty_dataset_column),
        }).fillna("").to_excel(writer, sheet_name="Datasets", index=False)

        pq_sources = data["pq_sources"].copy()
        datasets_lookup = datasets_df[["workspace_name", "workspace_id", "dataset_name", "dataset_id"]].copy() if not datasets_df.empty else pd.DataFrame(columns=["workspace_name", "workspace_id", "dataset_name", "dataset_id"])
        if not pq_sources.empty:
            pq_enhanced = pq_sources.merge(
                datasets_lookup, left_on=["workspace_name", "artifact_name"],
                right_on=["workspace_name", "dataset_name"], how="left",
            )
        else:
            pq_enhanced = pq_sources.assign(workspace_id="", dataset_id="")
        empty_pq_column = pd.Series(index=pq_enhanced.index, dtype=str)

        def _origin(row):
            path, url, server, db = row.get("path", ""), row.get("url", ""), row.get("server", ""), row.get("database", "")
            if path:
                return path
            if url:
                return url
            if server and db:
                return f"{server}/{db}"
            return server or ""

        lineage_sources = pd.DataFrame({
            "Workspace": pq_enhanced.get("workspace_name", empty_pq_column),
            "Workspace ID": pq_enhanced.get("workspace_id", empty_pq_column),
            "Dataset": pq_enhanced.get("artifact_name", empty_pq_column),
            "Dataset ID": pq_enhanced.get("dataset_id", empty_pq_column),
            "Table / Query": pq_enhanced.get("table_or_entity", empty_pq_column),
            "Source Type": pq_enhanced.get("source_type", empty_pq_column),
            "Origin": pq_enhanced.apply(_origin, axis=1) if not pq_enhanced.empty else [],
            "Server / Host": pq_enhanced.get("server", empty_pq_column),
            "Schema": pq_enhanced.get("schema", empty_pq_column),
            "Source Table": pq_enhanced.get("table", empty_pq_column),
            "SQL Query": pq_enhanced.get("raw_expression", pd.Series(dtype=str)).apply(_extract_sql_simple),
            "Power Query Expression": pq_enhanced.get("raw_expression", pd.Series(dtype=str)).astype(str).str[:2000],
        }).fillna("")
        lineage_sources.to_excel(writer, sheet_name="Lineage Sources", index=False)

        dataset_tables_df = data["dataset_tables"].copy()
        if not dataset_tables_df.empty:
            tables_with_expr = dataset_tables_df.merge(datasets_lookup, on=["workspace_name", "dataset_name"], how="left")
        else:
            tables_with_expr = dataset_tables_df.assign(workspace_id="", dataset_id="")

        lineage_df = data["lineage"].copy()
        if not lineage_df.empty:
            expr_lookup = lineage_df.groupby(["workspace_name", "dataset_name", "dataset_table"])["power_query_expression"].first().reset_index()
            source_type_lookup = lineage_df.groupby(["workspace_name", "dataset_name", "dataset_table"])["source_type"].first().reset_index()
            tables_with_full_expr = tables_with_expr.merge(
                expr_lookup, left_on=["workspace_name", "dataset_name", "table_name"],
                right_on=["workspace_name", "dataset_name", "dataset_table"], how="left",
            )
            tables_with_source = tables_with_full_expr.merge(
                source_type_lookup, left_on=["workspace_name", "dataset_name", "table_name"],
                right_on=["workspace_name", "dataset_name", "dataset_table"], how="left", suffixes=("", "_src"),
            )
        else:
            tables_with_full_expr = tables_with_expr.assign(power_query_expression="")
            tables_with_source = tables_with_full_expr
        empty_table_column = pd.Series(index=tables_with_source.index, dtype=str)

        query_analysis = pd.DataFrame({
            "Workspace": tables_with_source.get("workspace_name", empty_table_column),
            "Workspace ID": tables_with_source.get("workspace_id", empty_table_column),
            "Dataset": tables_with_source.get("dataset_name", empty_table_column),
            "Dataset ID": tables_with_source.get("dataset_id", empty_table_column),
            "Table / Query": tables_with_source.get("table_name", empty_table_column),
            "Expression Length": tables_with_source.get("power_query_expression", pd.Series(dtype=str)).apply(lambda x: len(str(x)) if x and not pd.isna(x) else 0),
            "Connector(s)": tables_with_source.get("power_query_expression", pd.Series(dtype=str)).apply(_extract_connectors),
            "Source Object Count": tables_with_source.get("power_query_expression", pd.Series(dtype=str)).apply(_count_source_objects),
            "Power Query Expression": tables_with_source.get("power_query_expression", pd.Series(dtype=str)).astype(str).str[:2000],
        }).fillna("")
        query_analysis.to_excel(writer, sheet_name="Query Analysis", index=False)

        steps_rows: list[dict] = []
        step_pattern = r'\s*([A-Za-z_#][\w\s#"]*?)\s*=\s*([^,\n]+(?:\([^)]*\))?)'
        for _, row in tables_with_full_expr.iterrows():
            expr = row.get("power_query_expression", "")
            if not expr or pd.isna(expr):
                continue
            expr_str = str(expr)
            for match in re.finditer(step_pattern, expr_str):
                step_name, step_expr = match.group(1).strip(), match.group(2).strip()
                funcs = re.findall(r'([A-Za-z_][\w\.]*)\s*\(', step_expr)
                steps_rows.append({
                    "Workspace": row.get("workspace_name", ""), "Dataset": row.get("dataset_name", ""),
                    "Table / Query": row.get("table_name", ""), "Step": step_name,
                    "Functions": "; ".join(set(funcs[:5])) if funcs else "", "Step Expression": step_expr[:500],
                })
        if steps_rows:
            pd.DataFrame(steps_rows).fillna("").to_excel(writer, sheet_name="Power Query Steps", index=False)
        else:
            pd.DataFrame(columns=["Workspace", "Dataset", "Table / Query", "Step", "Functions", "Step Expression"]).to_excel(
                writer, sheet_name="Power Query Steps", index=False,
            )

    _finalize_workbook(output_path)
    return output_path


def generate_all_fabric_lineage_formats(workspaces_input: str, output_dir: Path, batch_id: str) -> dict[str, str]:
    """Gera os 3 artefatos extras (full/simplified/detailed) de uma vez, a
    partir dos JSONs do Fabric Scanner API. Retorna os caminhos gerados."""
    data = process_workspaces_raw(workspaces_input)
    full_path = write_fabric_lineage_full(data, output_dir / f"fabric_lineage_{batch_id}.xlsx")
    simplified_path = create_simplified_migration(data, output_dir / f"fabric_lineage_simplified_migration_{batch_id}.xlsx")
    detailed_path = create_powerquery_detailed(data, output_dir / f"fabric_lineage_powerquery_detailed_{batch_id}.xlsx")
    return {
        "fabric_lineage_full_path": str(full_path),
        "simplified_migration_path": str(simplified_path),
        "powerquery_detailed_path": str(detailed_path),
    }
