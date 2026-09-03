"""dlctl.core.dashboard_lineage

Descobre a linhagem de TODOS os dashboards/relatórios do tenant, cruzando:
- `input/Workspaces` (Fabric Scanner API): Report -> Dataset -> tabelas do
  modelo, e/ou -> Dataflow (via `upstreamDataflows`/`targetDataflowId`);
- `input/scan` (exports brutos de Dataflow, com o código M/Power Query
  embutido): tabelas físicas realmente referenciadas via FROM/JOIN dentro de
  cada query do Dataflow — muito mais confiável que o nome do modelo do
  Dataset, que costuma ser um nome amigável dado pelo desenvolvedor;
- `input/sharedpoint` (Excel "Projeto Lakehouse..." + scripts .sql/.prc/
  .tab/.vw/.dsx, via `compute_global_scope(extended=True)`): usado só como
  apoio para saber a camada/domínio de cada tabela física já conhecida
  (tabelas que não aparecem lá caem no fallback de classificação por
  prefixo — DW_ -> Silver, DM_/PR_ -> Gold, resto -> Bronze).

Além disso, a partir de cada tabela resolvida (geralmente Gold), rastreia
PRA TRÁS via `dlctl.core.table_lineage_graph` (dependência tabela -> tabela
extraída dos mesmos scripts .sql/.prc/.tab/.vw de `input/sharedpoint`) até
achar as tabelas Silver/Bronze que a alimentam — por isso o total de
tabelas/camadas cresce em relação ao que vem só de Workspaces/Scan.

Quando o Dataset não usa Dataflow nenhum, cai no fallback de listar as
tabelas do próprio modelo Power BI (best-effort, sinalizado na coluna
'Origem' porque o nome pode não bater com o nome físico real)."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import openpyxl

from dlctl.core.global_scope import (
    _autofit,
    _classify_by_prefix,
    _extract_tables_from_sql,
    _norm,
    compute_global_scope,
    read_excel_tables,
)
from dlctl.core.table_lineage_graph import (
    build_mapped_table_dependency_graph,
    build_table_dependency_graph,
    trace_upstream,
)
from dlctl.generators.lineage_generator import _load_json_files, _read_json

_TRAILING_NUMBER_SUFFIX = re.compile(r"\s+\d+$")


def _normalize_dataflow_key(name: str) -> str:
    """Normaliza o nome de um Dataflow/arquivo de scan para comparação (ex.:
    o Dataflow real se chama 'CONTABIL', mas o arquivo exportado em
    input/scan foi salvo como 'CONTABIL 1.json' — o ' 1' é descartado)."""
    return _TRAILING_NUMBER_SUFFIX.sub("", _norm(name))


def _load_scan_dataflows(scan_input: str) -> dict[str, str]:
    """Carrega os JSONs de `input/scan` (exports de Dataflow com código M
    embutido) e indexa pelo nome normalizado -> conteúdo bruto do arquivo."""
    root = Path(scan_input)
    scans: dict[str, str] = {}
    if not root.exists():
        return scans
    for jf in sorted(root.glob("*.json")):
        try:
            content = jf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            name = json.loads(content).get("name") or jf.stem
        except (json.JSONDecodeError, AttributeError):
            name = jf.stem
        scans[_normalize_dataflow_key(name)] = content
    return scans


def build_dashboard_lineage(
    workspaces_input: str = "input/Workspaces",
    scan_input: str = "input/scan",
    sharedpoint_input: str = "input/sharedpoint",
) -> dict:
    """Monta a linhagem completa dashboard -> dataset -> (dataflow) -> tabela
    física -> camada/domínio, mais o resumo (total de dashboards, total de
    tabelas distintas, total por camada)."""
    datasets_by_id: dict[str, dict] = {}
    dataflows_by_id: dict[str, dict] = {}
    reports: list[dict] = []

    for jf in _load_json_files(workspaces_input):
        data = _read_json(jf)
        if not data:
            continue
        for ws in data.get("workspaces", []):
            ws_name = ws.get("name", ws.get("id", ""))
            for ds in ws.get("datasets", []):
                ds_id = str(ds.get("id", ""))
                tables = [t.get("name", "") for t in ds.get("tables", []) if t.get("name")]
                dataflow_ids = [
                    str(u.get("targetDataflowId", "")) for u in ds.get("upstreamDataflows", [])
                    if u.get("targetDataflowId")
                ]
                datasets_by_id[ds_id] = {
                    "name": ds.get("name", ds_id), "workspace": ws_name,
                    "tables": tables, "dataflow_ids": dataflow_ids,
                }
            for df in ws.get("dataflows", []):
                df_id = str(df.get("objectId") or df.get("id", ""))
                dataflows_by_id[df_id] = {"name": df.get("name", df_id), "workspace": ws_name}
            for rp in ws.get("reports", []):
                reports.append({
                    "workspace": ws_name, "name": rp.get("name", rp.get("id", "")),
                    "dataset_id": str(rp.get("datasetId", "")),
                })

    # Camada/domínio de apoio: reaproveita o escopo estendido (Excel +
    # scripts .sql/.prc/.tab/.vw/.dsx de input/sharedpoint) já classificado.
    scope = compute_global_scope(sharedpoint_input, extended=True)
    camada_by_table: dict[str, dict] = {}
    for r in scope.get("rows", []):
        camada_by_table.setdefault(_norm(r["tabela"]), {"camada": r["camada"], "dominio": r.get("dominio", "")})

    def _classify(table_name: str) -> tuple[str, str]:
        info = camada_by_table.get(table_name)
        if info:
            return info["camada"], info["dominio"]
        return _classify_by_prefix(table_name), ""

    # Grafo tabela -> tabela (dependência) extraído dos scripts de
    # input/sharedpoint, pra rastrear pra trás (Gold -> Silver -> Bronze)
    # a partir de qualquer tabela já resolvida. `camada_by_table` (Excel +
    # tudo já descoberto) alimenta o fallback de "nome do arquivo == tabela
    # conhecida" pros scripts .sql/.prc/.txt sem CREATE/INSERT explícito.
    upstream_by_table = build_table_dependency_graph(sharedpoint_input, known_tables=set(camada_by_table.keys()))
    excel_data = read_excel_tables(sharedpoint_input)
    excel_tables = set().union(*excel_data.get("tables_by_camada", {}).values())
    mapped_upstream = build_mapped_table_dependency_graph(sharedpoint_input, excel_tables)
    for target, sources in mapped_upstream.items():
        upstream_by_table.setdefault(target, set()).update(sources)
    mapped_upstream_rows = [
        {
            "tabela_origem": source, "camada_origem": _classify(source)[0],
            "tabela_destino": target, "camada_destino": _classify(target)[0],
        }
        for target, sources in mapped_upstream.items()
        for source in sources
    ]
    upstream_edges: set[tuple[str, str]] = set()

    # Tabelas físicas por Dataflow: extraídas do código M (FROM/JOIN) dos
    # arquivos de input/scan, casados pelo nome normalizado do Dataflow.
    scan_dataflows = _load_scan_dataflows(scan_input)
    tables_by_scan_key = {key: _extract_tables_from_sql(content) for key, content in scan_dataflows.items()}
    dataflow_tables: dict[str, set[str]] = {}
    for df_id, info in dataflows_by_id.items():
        key = _normalize_dataflow_key(info["name"])
        if key in tables_by_scan_key:
            dataflow_tables[df_id] = tables_by_scan_key[key]

    # Cache por dataset: (todas as tabelas achadas incl. rastreio upstream,
    # só as tabelas "diretas" antes do rastreio, texto de origem).
    resolved_cache: dict[str, tuple[set[str], set[str], str]] = {}

    def _resolve_dataset_tables(ds_id: str) -> tuple[set[str], set[str], str]:
        if ds_id in resolved_cache:
            return resolved_cache[ds_id]
        ds = datasets_by_id.get(ds_id)
        if not ds:
            resolved_cache[ds_id] = (set(), set(), "dataset não resolvido")
            return resolved_cache[ds_id]
        resolved: set[str] = set()
        for df_id in ds["dataflow_ids"]:
            resolved |= dataflow_tables.get(df_id, set())
        if resolved:
            origem = "via Dataflow (M-query)"
        elif ds["tables"]:
            resolved = {_norm(t) for t in ds["tables"]}
            origem = "direto no dataset (nome do modelo, pode não bater com o físico)"
        else:
            resolved_cache[ds_id] = (set(), set(), "sem fontes identificadas")
            return resolved_cache[ds_id]

        # Rastreia pra trás (Bronze/Silver) a partir das tabelas resolvidas
        # (normalmente Gold) via o grafo de dependência dos scripts.
        visited, edges = trace_upstream(resolved, upstream_by_table)
        upstream_edges.update(edges)
        resolved_cache[ds_id] = (visited, resolved, origem)
        return resolved_cache[ds_id]

    def _row_origem(t: str, base_origem: str, direct_tables: set[str]) -> str:
        if t in direct_tables:
            return base_origem
        return f"rastreio SQL/.vw/.tab (upstream — {base_origem})"

    dashboard_rows: list[dict] = []
    seen_dashboards: set[tuple[str, str]] = set()
    distinct_tables: set[str] = set()
    for rp in reports:
        ds = datasets_by_id.get(rp["dataset_id"])
        tables, direct_tables, origem = _resolve_dataset_tables(rp["dataset_id"])
        seen_dashboards.add((rp["workspace"], rp["name"]))
        dataset_name = ds["name"] if ds else "(não resolvido)"
        if not tables:
            dashboard_rows.append({
                "workspace": rp["workspace"], "dashboard": rp["name"], "dataset": dataset_name,
                "tabela": "", "camada": "", "dominio": "", "origem": origem,
            })
            continue
        for t in sorted(tables):
            camada, dominio = _classify(t)
            distinct_tables.add(t)
            dashboard_rows.append({
                "workspace": rp["workspace"], "dashboard": rp["name"], "dataset": dataset_name,
                "tabela": t, "camada": camada, "dominio": dominio,
                "origem": _row_origem(t, origem, direct_tables),
            })

    dataset_dataflow_rows: list[dict] = []
    for ds_id, ds in datasets_by_id.items():
        tables, direct_tables, origem = _resolve_dataset_tables(ds_id)
        if not tables:
            dataset_dataflow_rows.append({
                "workspace": ds["workspace"], "tipo": "Dataset", "nome": ds["name"],
                "tabela": "", "camada": "", "dominio": "", "origem": origem,
            })
            continue
        for t in sorted(tables):
            camada, dominio = _classify(t)
            dataset_dataflow_rows.append({
                "workspace": ds["workspace"], "tipo": "Dataset", "nome": ds["name"],
                "tabela": t, "camada": camada, "dominio": dominio,
                "origem": _row_origem(t, origem, direct_tables),
            })
    for df_id, info in dataflows_by_id.items():
        tables = dataflow_tables.get(df_id, set())
        if not tables:
            dataset_dataflow_rows.append({
                "workspace": info["workspace"], "tipo": "Dataflow", "nome": info["name"],
                "tabela": "", "camada": "", "dominio": "", "origem": "sem tabela extraída da M-query (ou sem export em input/scan)",
            })
            continue
        for t in sorted(tables):
            camada, dominio = _classify(t)
            dataset_dataflow_rows.append({
                "workspace": info["workspace"], "tipo": "Dataflow", "nome": info["name"],
                "tabela": t, "camada": camada, "dominio": dominio, "origem": "M-query (FROM/JOIN)",
            })

    excel_tables_by_layer = {
        camada: set(tables)
        for camada, tables in excel_data.get("tables_by_camada", {}).items()
    }
    client_tables = set().union(*excel_tables_by_layer.values()) if excel_tables_by_layer else set()
    client_layer_by_table = {
        table: camada
        for camada, tables in excel_tables_by_layer.items()
        for table in tables
    }
    combined_tables = distinct_tables | client_tables
    camada_totals = Counter(_classify(t)[0] for t in distinct_tables)
    client_layer_totals = Counter(client_layer_by_table.values())
    combined_layer_totals = Counter(_classify(t)[0] for t in combined_tables)

    upstream_rows = [
        {
            "tabela_origem": src, "camada_origem": _classify(src)[0],
            "tabela_destino": dst, "camada_destino": _classify(dst)[0],
        }
        for src, dst in sorted(upstream_edges)
    ]

    return {
        "dashboard_rows": dashboard_rows,
        "dataset_dataflow_rows": dataset_dataflow_rows,
        "upstream_rows": upstream_rows,
        "mapped_upstream_rows": sorted(
            mapped_upstream_rows,
            key=lambda row: (row["tabela_destino"], row["tabela_origem"]),
        ),
        "summary": {
            "total_dashboards": len(seen_dashboards),
            "total_tabelas_distintas": len(distinct_tables),
            "tabelas_por_camada": dict(camada_totals),
            "total_tabelas_excel_cliente": len(client_tables),
            "tabelas_por_camada_excel_cliente": dict(client_layer_totals),
            "total_tabelas_consolidado": len(combined_tables),
            "tabelas_por_camada_consolidado": dict(combined_layer_totals),
            "tabelas_em_comum": len(client_tables & distinct_tables),
            "tabelas_apenas_excel_cliente": len(client_tables - distinct_tables),
            "tabelas_apenas_dashboards": len(distinct_tables - client_tables),
        },
    }


def export_dashboard_lineage_report(result: dict, output_dir: Path, batch_id: str) -> dict[str, str]:
    """Exporta a linhagem para `manifests/dashboard/`: Excel com abas Resumo
    (totais), 'Linhagem Dashboards' (dashboard -> dataset -> tabela) e
    'Dataset e Dataflows' (agregado por dataset/dataflow, independente de
    quantos dashboards os usam)."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    excel_path = output_dir / f"linhagem_dashboards_{batch_id}.xlsx"

    wb = openpyxl.Workbook()
    ws_resumo = wb.active
    ws_resumo.title = "Resumo"
    ws_resumo.append(["Métrica", "Valor"])
    summary = result["summary"]
    ws_resumo.append(["Total de dashboards/relatórios", summary["total_dashboards"]])
    ws_resumo.append(["Total de tabelas físicas distintas", summary["total_tabelas_distintas"]])
    for camada, total in sorted(summary["tabelas_por_camada"].items()):
        ws_resumo.append([f"Tabelas na camada {camada}", total])
    ws_resumo.append([])
    ws_resumo.append(["Consolidado — tabelas únicas do Excel + dashboards", summary.get("total_tabelas_consolidado", 0)])
    ws_resumo.append(["Tabelas únicas mapeadas no Excel do cliente", summary.get("total_tabelas_excel_cliente", 0)])
    ws_resumo.append(["Tabelas únicas alcançadas pelos dashboards", summary.get("total_tabelas_distintas", 0)])
    ws_resumo.append(["Tabelas em comum entre Excel e dashboards", summary.get("tabelas_em_comum", 0)])
    ws_resumo.append(["Apenas no Excel do cliente", summary.get("tabelas_apenas_excel_cliente", 0)])
    ws_resumo.append(["Apenas nos dashboards", summary.get("tabelas_apenas_dashboards", 0)])
    for camada, total in sorted(summary.get("tabelas_por_camada_consolidado", {}).items()):
        ws_resumo.append([f"Consolidado na camada {camada}", total])
    for camada, total in sorted(summary.get("tabelas_por_camada_excel_cliente", {}).items()):
        ws_resumo.append([f"Excel do cliente na camada {camada}", total])
    _autofit(ws_resumo)

    ws_dash = wb.create_sheet("Linhagem Dashboards")
    ws_dash.append(["Workspace", "Dashboard/Relatório", "Dataset", "Tabela", "Camada", "Domínio", "Origem"])
    for r in result["dashboard_rows"]:
        ws_dash.append([r["workspace"], r["dashboard"], r["dataset"], r["tabela"], r["camada"], r["dominio"], r["origem"]])
    _autofit(ws_dash)

    ws_dd = wb.create_sheet("Dataset e Dataflows")
    ws_dd.append(["Workspace", "Tipo", "Nome", "Tabela", "Camada", "Domínio", "Origem"])
    for r in result["dataset_dataflow_rows"]:
        ws_dd.append([r["workspace"], r["tipo"], r["nome"], r["tabela"], r["camada"], r["dominio"], r["origem"]])
    _autofit(ws_dd)

    ws_up = wb.create_sheet("Linhagem SQL (upstream)")
    ws_up.append(["Tabela Origem", "Camada Origem", "Tabela Destino", "Camada Destino"])
    for r in result.get("upstream_rows", []):
        ws_up.append([r["tabela_origem"], r["camada_origem"], r["tabela_destino"], r["camada_destino"]])
    _autofit(ws_up)

    ws_mapped = wb.create_sheet("Dependências Mapeamento")
    ws_mapped.append(["Tabela Origem", "Camada Origem", "Tabela Destino", "Camada Destino"])
    for r in result.get("mapped_upstream_rows", []):
        ws_mapped.append([r["tabela_origem"], r["camada_origem"], r["tabela_destino"], r["camada_destino"]])
    _autofit(ws_mapped)

    wb.save(str(excel_path))
    return {"excel_path": str(excel_path)}


def find_latest_lineage_excel(output_dir: Path) -> Path | None:
    """Encontra o artefato `linhagem_dashboards_*.xlsx` mais recente já
    gerado em `output_dir` (manifests/dashboard/), para a tela carregar sem
    precisar reprocessar do zero a cada acesso."""
    output_dir = Path(output_dir)
    if not output_dir.exists():
        return None
    candidates = sorted(output_dir.glob("linhagem_dashboards_*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None
