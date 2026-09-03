"""Página de dashboard: Supervisório — Linhagem de Dashboards.

Cópia da estética da página Supervisor, mas para o artefato de
`dlctl.core.dashboard_lineage` (cruza `input/Workspaces` + `input/scan` +
`input/sharedpoint`): descobre a linhagem completa Dashboard -> Dataset ->
(Dataflow) -> Tabela física -> Camada/Domínio de TODOS os dashboards do
tenant.

Sempre que a página abre, carrega o artefato `linhagem_dashboards_*.xlsx`
mais recente já gerado em `manifests/dashboard/` (não reprocessa do zero a
cada acesso) — clique em "🔎 Rodar diagnóstico" para recalcular e gerar um
artefato novo.
"""
from __future__ import annotations

import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[3]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import networkx as nx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from dlctl.config import load_profile
from dlctl.core.dashboard_lineage import (
    build_dashboard_lineage,
    export_dashboard_lineage_report,
    find_latest_lineage_excel,
)

# Mesma paleta "enterprise" da página Supervisor, duplicada aqui (páginas do
# dashboard são scripts independentes) em vez de importada, para não criar
# acoplamento entre páginas.
COLOR_PRIMARY = "#13315C"     # navy — série principal
COLOR_SECONDARY = "#5E7CA3"   # azul-aço — neutro
COLOR_SUCCESS = "#1F7A5C"     # verde-petróleo
COLOR_WARNING = "#C98B32"     # âmbar
COLOR_DANGER = "#A6434A"      # vermelho-tijolo
COLOR_NEUTRAL = "#8492A6"     # cinza-ardósia
CATEGORY_COLOR_SEQUENCE = [COLOR_PRIMARY, COLOR_SECONDARY, COLOR_SUCCESS, COLOR_WARNING, COLOR_NEUTRAL, COLOR_DANGER, "#3E5C76"]
CAMADA_LABEL_PT = {"bronze": "Bronze", "silver": "Prata", "gold": "Ouro"}
CAMADA_ORDER = {"bronze": 0, "silver": 1, "gold": 2}
GRAPH_DASHBOARD_COLOR = "#2E8B57"
GRAPH_DATASET_COLOR = "#2878C8"
GRAPH_DATAFLOW_COLOR = "#7C3AED"
CAMADA_NODE_COLOR = {"Bronze": "#D64545", "Silver": "#A7ADB7", "Gold": "#E0B323"}


def _camada_label(nome: str) -> str:
    return CAMADA_LABEL_PT.get(str(nome).strip().lower(), nome)


def _sort_camadas(items) -> list:
    return sorted(items, key=lambda kv: CAMADA_ORDER.get(str(kv[0]).strip().lower(), 99))


def _result_to_frames(result: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    dash_df = pd.DataFrame(result["dashboard_rows"]).rename(columns={
        "workspace": "Workspace", "dashboard": "Dashboard/Relatório", "dataset": "Dataset",
        "tabela": "Tabela", "camada": "Camada", "dominio": "Domínio", "origem": "Origem",
    })
    dd_df = pd.DataFrame(result["dataset_dataflow_rows"]).rename(columns={
        "workspace": "Workspace", "tipo": "Tipo", "nome": "Nome",
        "tabela": "Tabela", "camada": "Camada", "dominio": "Domínio", "origem": "Origem",
    })
    up_df = pd.DataFrame(result.get("upstream_rows", [])).rename(columns={
        "tabela_origem": "Tabela Origem", "camada_origem": "Camada Origem",
        "tabela_destino": "Tabela Destino", "camada_destino": "Camada Destino",
    })
    mapped_df = pd.DataFrame(result.get("mapped_upstream_rows", [])).rename(columns={
        "tabela_origem": "Tabela Origem", "camada_origem": "Camada Origem",
        "tabela_destino": "Tabela Destino", "camada_destino": "Camada Destino",
    })
    crosswalk_df = pd.DataFrame(result.get("mapping_dashboard_rows", [])).rename(columns={
        "tabela_mapeada": "Tabela Mapeada", "tabela_rastreada": "Tabela Rastreada",
        "camada": "Camada", "workspace": "Workspace", "dashboard": "Dashboard/Relatório",
        "dataset": "Dataset", "status": "Status",
    })
    dataset_dataflow_df = pd.DataFrame(result.get("dataset_dataflow_links", [])).rename(columns={
        "dataset": "Dataset", "dataflow": "Dataflow", "workspace": "Workspace",
    })
    sharepoint_df = pd.DataFrame(result.get("sharepoint_rows", [])).rename(columns={
        "workspace": "Workspace", "dashboard": "Dashboard/Relatório", "dataset": "Dataset",
        "tipo": "Tipo", "fonte": "Fonte", "observacao": "Observação",
    })
    return dash_df, dd_df, up_df, mapped_df, crosswalk_df, sharepoint_df, dataset_dataflow_df, result["summary"]


def _load_from_excel(path: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    sheets = pd.read_excel(path, sheet_name=None)
    resumo_df = sheets.get("Resumo", pd.DataFrame())
    summary = {
        "total_dashboards": 0, "total_tabelas_distintas": 0, "tabelas_por_camada": {},
        "total_tabelas_consolidado": 0, "total_tabelas_excel_cliente": 0,
        "tabelas_por_camada_consolidado": {}, "tabelas_por_camada_excel_cliente": {},
        "tabelas_em_comum": 0, "tabelas_apenas_excel_cliente": 0,
        "tabelas_apenas_dashboards": 0,
        "tabelas_excel_sem_dashboard": 0,
        "dependencias_tabelas_excel_sem_dashboard": 0,
        "total_fontes_sharepoint_bronze": 0, "total_dashboards_com_sharepoint": 0,
    }
    for _, row in resumo_df.iterrows():
        metric, valor = row.get("Métrica"), row.get("Valor")
        if metric == "Total de dashboards/relatórios":
            summary["total_dashboards"] = int(valor)
        elif metric == "Total de tabelas físicas distintas":
            summary["total_tabelas_distintas"] = int(valor)
        elif isinstance(metric, str) and metric.startswith("Tabelas na camada "):
            summary["tabelas_por_camada"][metric.replace("Tabelas na camada ", "").strip()] = int(valor)
        elif metric == "Consolidado — tabelas únicas do Excel + dashboards":
            summary["total_tabelas_consolidado"] = int(valor)
        elif metric == "Tabelas únicas mapeadas no Excel do cliente":
            summary["total_tabelas_excel_cliente"] = int(valor)
        elif metric == "Tabelas em comum entre Excel e dashboards":
            summary["tabelas_em_comum"] = int(valor)
        elif metric == "Apenas no Excel do cliente":
            summary["tabelas_apenas_excel_cliente"] = int(valor)
        elif metric == "Apenas nos dashboards":
            summary["tabelas_apenas_dashboards"] = int(valor)
        elif metric == "Tabelas mapeadas pelo cliente sem ligação com dashboards":
            summary["tabelas_excel_sem_dashboard"] = int(valor)
        elif metric == "Dependências únicas dessas tabelas sem dashboards":
            summary["dependencias_tabelas_excel_sem_dashboard"] = int(valor)
        elif metric == "Fontes SharePoint na camada Bronze":
            summary["total_fontes_sharepoint_bronze"] = int(valor)
        elif metric == "Dashboards com fonte SharePoint":
            summary["total_dashboards_com_sharepoint"] = int(valor)
        elif isinstance(metric, str) and metric.startswith("Consolidado na camada "):
            summary["tabelas_por_camada_consolidado"][metric.replace("Consolidado na camada ", "").strip()] = int(valor)
        elif isinstance(metric, str) and metric.startswith("Excel do cliente na camada "):
            summary["tabelas_por_camada_excel_cliente"][metric.replace("Excel do cliente na camada ", "").strip()] = int(valor)
    dash_df = sheets.get("Linhagem Dashboards", pd.DataFrame()).fillna("")
    dd_df = sheets.get("Dataset e Dataflows", pd.DataFrame()).fillna("")
    up_df = sheets.get("Linhagem SQL (upstream)", pd.DataFrame()).fillna("")
    mapped_df = sheets.get("Dependências Mapeamento", pd.DataFrame()).fillna("")
    crosswalk_df = sheets.get("Mapping até Dashboards", pd.DataFrame()).fillna("")
    if "Camada Mapeada" not in crosswalk_df.columns and not crosswalk_df.empty:
        crosswalk_df["Camada Mapeada"] = crosswalk_df["Camada"]
    sharepoint_df = sheets.get("Fontes SharePoint Bronze", pd.DataFrame()).fillna("")
    dataset_dataflow_df = sheets.get("Dataset e Dataflow", pd.DataFrame()).fillna("")
    return dash_df, dd_df, up_df, mapped_df, crosswalk_df, sharepoint_df, dataset_dataflow_df, summary


st.set_page_config(page_title="Supervisório — Constellation Migration Control", layout="wide", page_icon="🕸️")
st.title("🕸️ Supervisório — Linhagem de Dashboards")
st.caption(
    "Descobre a linhagem de TODOS os dashboards/relatórios do tenant: Dashboard → Dataset → (Dataflow) → "
    "Tabela física → Camada/Domínio, cruzando `input/Workspaces` + `input/scan` (código M dos Dataflows) + "
    "`input/sharedpoint` (classificação de camada/domínio, de apoio)."
)

profile_name = st.sidebar.text_input(
    "Profile", value="ms_client_constellation", key="supervisorio_profile",
    help="Profile de config/profiles.yaml usado para localizar manifests/dashboard/ (onde os artefatos são salvos).",
)
try:
    profile = load_profile(profile_name)
except Exception as exc:
    st.error(f"Não foi possível carregar o profile '{profile_name}': {exc}")
    st.stop()

col_in1, col_in2, col_in3 = st.columns(3)
workspaces_input = col_in1.text_input(
    "Pasta Workspaces", value="input/Workspaces",
    help="Pasta/zip com os JSONs do Fabric Scanner API (Report -> Dataset -> Dataflow).",
)
scan_input = col_in2.text_input(
    "Pasta Scan (Dataflows)", value="input/scan",
    help="Pasta com os exports brutos de Dataflow (código M/Power Query embutido).",
)
sharedpoint_input = col_in3.text_input(
    "Pasta SharePoint", value="input/sharedpoint",
    help="Excel 'Projeto Lakehouse - Tabelas e Pipelines.xlsx' + scripts .sql/.prc/.tab/.vw/.dsx, usada só de apoio.",
)

artifacts_dir = profile.paths.manifests_root / "dashboard"

if st.button(
    "🔎 Rodar diagnóstico", type="primary",
    help="Reprocessa Workspaces + Scan + SharePoint do zero e gera um novo artefato. Sem clicar aqui, a "
         "página carrega sempre o último artefato já gerado (não reprocessa a cada acesso).",
):
    with st.spinner("Cruzando input/Workspaces + input/scan + input/sharedpoint..."):
        result = build_dashboard_lineage(workspaces_input, scan_input, sharedpoint_input)
    batch_id = f"linhagem_{datetime.now():%Y%m%d_%H%M%S}"
    paths = export_dashboard_lineage_report(result, artifacts_dir, batch_id)
    dash_df, dd_df, up_df, mapped_df, crosswalk_df, sharepoint_df, dataset_dataflow_df, summary = _result_to_frames(result)
    st.session_state["linhagem_result"] = {
        "dash_df": dash_df, "dd_df": dd_df, "up_df": up_df, "mapped_df": mapped_df,
        "crosswalk_df": crosswalk_df, "sharepoint_df": sharepoint_df, "dataset_dataflow_df": dataset_dataflow_df, "summary": summary,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "excel_path": paths["excel_path"],
    }
    st.success(f"✅ Artefato gerado: `{paths['excel_path']}`")

if "linhagem_result" not in st.session_state:
    latest_path = find_latest_lineage_excel(artifacts_dir)
    if latest_path:
        dash_df, dd_df, up_df, mapped_df, crosswalk_df, sharepoint_df, dataset_dataflow_df, summary = _load_from_excel(latest_path)
        st.session_state["linhagem_result"] = {
            "dash_df": dash_df, "dd_df": dd_df, "up_df": up_df, "mapped_df": mapped_df,
            "crosswalk_df": crosswalk_df, "sharepoint_df": sharepoint_df, "dataset_dataflow_df": dataset_dataflow_df, "summary": summary,
            "generated_at": pd.Timestamp(latest_path.stat().st_mtime, unit="s").strftime("%Y-%m-%d %H:%M:%S"),
            "excel_path": str(latest_path),
        }

result = st.session_state.get("linhagem_result")
if not result:
    st.info(
        "Nenhum artefato de linhagem encontrado ainda em `manifests/dashboard/`. Clique em **🔎 Rodar "
        "diagnóstico** acima para gerar o primeiro."
    )
    st.stop()

st.caption(f"Última geração: {result['generated_at']} — artefato: `{result['excel_path']}`")

dash_df: pd.DataFrame = result["dash_df"]
dd_df: pd.DataFrame = result["dd_df"]
up_df: pd.DataFrame = result.get("up_df", pd.DataFrame())
mapped_df: pd.DataFrame = result.get("mapped_df", pd.DataFrame())
crosswalk_df: pd.DataFrame = result.get("crosswalk_df", pd.DataFrame())
sharepoint_df: pd.DataFrame = result.get("sharepoint_df", pd.DataFrame())
dataset_dataflow_df: pd.DataFrame = result.get("dataset_dataflow_df", pd.DataFrame())
summary: dict = result["summary"]
camadas_ordenadas = _sort_camadas(summary["tabelas_por_camada"].items())

if dash_df.empty:
    st.info("Nenhuma linha de linhagem de dashboards no artefato carregado.")
    st.stop()

dash_df = dash_df.copy()
dash_df["_label"] = dash_df["Workspace"].astype(str) + " / " + dash_df["Dashboard/Relatório"].astype(str)
labels = sorted(dash_df["_label"].unique())
picked = [label for label in st.session_state.get("dashboard_filter", []) if label in labels]
filtered = dash_df[dash_df["_label"].isin(picked)] if picked else dash_df
tabelas_validas = filtered[filtered["Tabela"].astype(str) != ""]
dashboard_tables = set(tabelas_validas["Tabela"])
selected_datasets = set(filtered["Dataset"])
selected_dataflows = set(
    dataset_dataflow_df.loc[
        dataset_dataflow_df["Dataset"].isin(selected_datasets), "Dataflow"
    ]
) if not dataset_dataflow_df.empty else set()

if not crosswalk_df.empty:
    crosswalk_df = crosswalk_df.copy()
    crosswalk_df["_label"] = crosswalk_df["Workspace"].astype(str) + " / " + crosswalk_df["Dashboard/Relatório"].astype(str)
    crosswalk_selected = crosswalk_df[crosswalk_df["_label"].isin(picked)] if picked else crosswalk_df
else:
    crosswalk_selected = crosswalk_df

if not sharepoint_df.empty:
    sharepoint_df = sharepoint_df.copy()
    sharepoint_df["_label"] = sharepoint_df["Workspace"].astype(str) + " / " + sharepoint_df["Dashboard/Relatório"].astype(str)
    sharepoint_selected = sharepoint_df[sharepoint_df["_label"].isin(picked)] if picked else sharepoint_df
else:
    sharepoint_selected = sharepoint_df

client_tables = set(crosswalk_selected["Tabela Mapeada"]) if not crosswalk_selected.empty else set()
mapping_tables_with_dashboard = set(
    crosswalk_selected.loc[crosswalk_selected["Dashboard/Relatório"].astype(str) != "", "Tabela Mapeada"]
) if not crosswalk_selected.empty else set()
mapping_traced_tables = set(crosswalk_selected["Tabela Rastreada"]) if not crosswalk_selected.empty else set()
client_layers = {}
if not crosswalk_selected.empty:
    for _, row in crosswalk_selected.drop_duplicates("Tabela Mapeada").iterrows():
        client_layers[row["Tabela Mapeada"]] = row.get("Camada Mapeada", row.get("Camada", ""))

st.markdown("#### Modo dos cards totalizadores")
card_mode = st.radio(
    "Selecionar visão", ["Totais Gerais", "Tabelas Vinculadas a Dashboards", "Exclusivo Mapping do Cliente"],
    horizontal=True, label_visibility="collapsed",
)

if card_mode == "Totais Gerais":
    card_tables = dashboard_tables | client_tables | mapping_traced_tables
    card_layer_by_table = {row["Tabela"]: row["Camada"] for _, row in tabelas_validas.drop_duplicates("Tabela").iterrows()}
    card_layer_by_table.update({table: client_layers.get(table, "") for table in client_tables})
    card_dashboard_count = filtered["_label"].nunique()
    card_extra = None
elif card_mode == "Tabelas Vinculadas a Dashboards":
    card_tables = dashboard_tables
    card_layer_by_table = {row["Tabela"]: row["Camada"] for _, row in tabelas_validas.drop_duplicates("Tabela").iterrows()}
    card_dashboard_count = filtered.loc[filtered["Tabela"].astype(str) != "", "_label"].nunique()
    card_extra = None
else:
    card_tables = client_tables
    card_layer_by_table = client_layers
    card_dashboard_count = crosswalk_selected.loc[
        crosswalk_selected["Dashboard/Relatório"].astype(str) != "", "_label"
    ].nunique() if not crosswalk_selected.empty else 0
    card_extra = len(mapping_tables_with_dashboard)

card_layer_counts = Counter(card_layer_by_table.get(table, "") for table in card_tables)
card_layer_counts.pop("", None)
card_layer_items = _sort_camadas(card_layer_counts.items())

sharepoint_count = sharepoint_selected["Fonte"].nunique() if not sharepoint_selected.empty else 0
st.markdown("### Indicadores da visão selecionada")
card_cols = st.columns(2 + len(camadas_ordenadas) + (1 if card_extra is not None else 0) + 2)
with card_cols[0]:
    st.metric("Total de dashboards", int(card_dashboard_count))
with card_cols[1]:
    st.metric("Total de tabelas únicas", len(card_tables))
for col, (camada, _) in zip(card_cols[2:], camadas_ordenadas):
    with col:
        st.metric(_camada_label(camada), int(card_layer_counts.get(camada, 0)))
if card_extra is not None:
    with card_cols[2 + len(camadas_ordenadas)]:
        st.metric("Tabelas que chegam a dashboards", card_extra)
with card_cols[-1]:
    st.metric("Fontes SharePoint (Bronze)", int(sharepoint_count))
with card_cols[-2]:
    st.metric("Dataflows", len(selected_dataflows))

st.markdown("#### Distribuição por camada")
col_bar, col_pie = st.columns(2)
camada_chart_df = pd.DataFrame(
    [(camada, card_layer_counts.get(camada, 0)) for camada, _ in camadas_ordenadas],
    columns=["camada", "total"],
)
camada_chart_df["camada"] = camada_chart_df["camada"].map(_camada_label)
with col_bar:
    bar_fig = go.Figure(data=[go.Bar(x=camada_chart_df["camada"], y=camada_chart_df["total"], marker_color=COLOR_PRIMARY)])
    bar_fig.update_layout(height=320, margin=dict(l=20, r=20, t=40, b=40), title=f"Tabelas distintas por camada — {card_mode}")
    st.plotly_chart(bar_fig, use_container_width=True)
with col_pie:
    pie_fig = px.pie(
        camada_chart_df, names="camada", values="total", title=f"Distribuição das tabelas por camada — {card_mode}", hole=0.45,
        color_discrete_sequence=CATEGORY_COLOR_SEQUENCE,
    )
    pie_fig.update_layout(height=320, margin=dict(l=20, r=20, t=40, b=10))
    st.plotly_chart(pie_fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Linhagem de um (ou vários) dashboard(s)
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown("### 🎯 Linhagem de um (ou vários) dashboard(s)")
st.caption(
    "Escolha um ou mais dashboards para recalcular os cards acima (total de tabelas e por camada) só "
    "com o que ELES usam, e ver o rastreio da linhagem (Dashboard → Dataset → Tabela)."
)
st.multiselect(
    "Dashboard(s)/Relatório(s)", labels,
    key="dashboard_filter",
    help="Deixe vazio para visualizar o universo completo.",
)
graph_slot = st.empty()

# ---------------------------------------------------------------------------
# Visão consolidada: obrigação do cliente + necessidade dos dashboards
# ---------------------------------------------------------------------------
with st.expander("Visão consolidada do escopo", expanded=False):
    st.caption(
        "União deduplicada das tabelas mapeadas pelo cliente no Excel com as tabelas "
        "alcançadas pelo rastreio Dashboard → camadas."
    )
    consolidated_cols = st.columns(4)
    with consolidated_cols[0]:
        st.metric("Tabelas únicas consolidadas", summary.get("total_tabelas_consolidado", summary["total_tabelas_distintas"]))
    with consolidated_cols[1]:
        st.metric("Mapeadas no Excel do cliente", summary.get("total_tabelas_excel_cliente", 0))
    with consolidated_cols[2]:
        st.metric("Alcançadas pelos dashboards", summary["total_tabelas_distintas"])
    with consolidated_cols[3]:
        st.metric("Tabelas em comum", summary.get("tabelas_em_comum", 0))

    consolidated_layer_items = _sort_camadas(summary.get("tabelas_por_camada_consolidado", {}).items())
    layer_rows = []
    for camada, total in consolidated_layer_items:
        layer_rows.append({
            "Camada": _camada_label(camada),
            "Excel do cliente": summary.get("tabelas_por_camada_excel_cliente", {}).get(camada, 0),
            "Dashboards": summary.get("tabelas_por_camada", {}).get(camada, 0),
            "Consolidado único": total,
        })
    st.dataframe(pd.DataFrame(layer_rows), use_container_width=True, hide_index=True)
    st.caption(
        f"Somente no Excel: {summary.get('tabelas_apenas_excel_cliente', 0)} | "
        f"Somente nos dashboards: {summary.get('tabelas_apenas_dashboards', 0)}"
    )

distinct_sel = len(dashboard_tables)

st.dataframe(
    filtered.drop(columns=["_label"]), use_container_width=True, hide_index=True,
)
st.caption(f"{len(filtered)} linha(s) — {filtered['Dashboard/Relatório'].nunique()} dashboard(s), {distinct_sel} tabela(s) distinta(s).")
with graph_slot.container():
    st.markdown("#### 🕸️ Rastreio da linhagem (Dashboard → Dataset → Dataflow → Tabela)")
    graph = nx.DiGraph()
    for _, row in filtered.iterrows():
        dash_node = f"RPT::{row['Workspace']}::{row['Dashboard/Relatório']}"
        ds_node = f"DS::{row['Dataset']}"
        graph.add_node(dash_node, label=row["Dashboard/Relatório"], kind="dashboard")
        graph.add_node(ds_node, label=row["Dataset"], kind="dataset")
        graph.add_edge(dash_node, ds_node)
        if row["Tabela"]:
            tbl_node = f"TBL::{row['Tabela']}"
            graph.add_node(tbl_node, label=row["Tabela"], kind="tabela", camada=row["Camada"])
            linked_dataflows = set(
                dataset_dataflow_df.loc[
                    dataset_dataflow_df["Dataset"] == row["Dataset"], "Dataflow"
                ]
            ) if not dataset_dataflow_df.empty else set()
            if linked_dataflows:
                for dataflow in linked_dataflows:
                    df_node = f"DF::{row['Workspace']}::{dataflow}"
                    graph.add_node(df_node, label=dataflow, kind="dataflow")
                    graph.add_edge(ds_node, df_node)
                    graph.add_edge(df_node, tbl_node)
            else:
                graph.add_edge(ds_node, tbl_node)

    # Encadeia as tabelas entre si (Gold -> Silver -> Bronze) usando o
    # rastreio SQL/.vw/.tab — segue em várias passadas até estabilizar,
    # pra pegar cadeias com mais de um salto (Gold -> Silver -> Bronze).
    if up_df.empty and mapped_df.empty:
        graph_up_df = pd.DataFrame()
    else:
        graph_up_df = pd.concat([up_df, mapped_df], ignore_index=True).drop_duplicates(
            subset=["Tabela Origem", "Tabela Destino"]
        )
    if not graph_up_df.empty:
        for _ in range(10):
            tabelas_no_grafo = {n for n, d in graph.nodes(data=True) if d["kind"] == "tabela"}
            added = False
            for _, row in graph_up_df.iterrows():
                src_node, dst_node = f"TBL::{row['Tabela Origem']}", f"TBL::{row['Tabela Destino']}"
                if dst_node not in tabelas_no_grafo:
                    continue
                is_new = src_node not in graph
                graph.add_node(src_node, label=row["Tabela Origem"], kind="tabela", camada=row["Camada Origem"])
                graph.add_edge(src_node, dst_node)
                if is_new:
                    added = True
            if not added:
                break

    if graph.number_of_nodes() == 0:
        st.info("Nenhum nó para desenhar com a seleção atual.")
    else:
        try:
            pos = nx.spring_layout(graph, seed=42, k=0.6)
        except ModuleNotFoundError as exc:
            if exc.name != "scipy":
                raise
            pos = nx.circular_layout(graph)
        edge_x, edge_y = [], []
        for u, v in graph.edges():
            x0, y0 = pos[u]
            x1, y1 = pos[v]
            edge_x += [x0, x1, None]
            edge_y += [y0, y1, None]
        edge_trace = go.Scatter(x=edge_x, y=edge_y, mode="lines", line=dict(width=1, color="#B0B7C3"), hoverinfo="none")

        node_x, node_y, node_text, node_label, node_color = [], [], [], [], []
        for n, data in graph.nodes(data=True):
            x, y = pos[n]
            node_x.append(x)
            node_y.append(y)
            node_label.append(data["label"])
            node_text.append(f"{data['kind']}: {data['label']}")
            if data["kind"] == "tabela":
                node_color.append(CAMADA_NODE_COLOR.get(data.get("camada", ""), COLOR_DANGER))
            elif data["kind"] == "dataset":
                node_color.append(GRAPH_DATASET_COLOR)
            elif data["kind"] == "dataflow":
                node_color.append(GRAPH_DATAFLOW_COLOR)
            else:
                node_color.append(GRAPH_DASHBOARD_COLOR)
        node_trace = go.Scatter(
            x=node_x, y=node_y, mode="markers+text", text=node_label, textposition="top center",
            hovertext=node_text, hoverinfo="text",
            marker=dict(size=14, color=node_color, line=dict(width=1, color="white")),
        )
        fig = go.Figure(data=[edge_trace, node_trace])
        fig.update_layout(
            showlegend=False, height=580, margin=dict(l=10, r=10, t=40, b=10),
            xaxis=dict(visible=False), yaxis=dict(visible=False),
            title=(
                "Dashboard → Dataset → Dataflow → Tabela | "
                "Verde: Dashboard | Azul: Dataset | Violeta: Dataflow | "
                "Amarelo: Ouro | Prata: Silver | Vermelho: Bronze"
            ),
        )
        st.plotly_chart(fig, use_container_width=True)

with st.expander("📦 Dataset e Dataflows (agregado — tabelas expostas por cada dataset/dataflow)"):
    if picked:
        datasets_sel = set(filtered["Dataset"].unique())
        dd_show = dd_df[(dd_df["Nome"].isin(datasets_sel)) | (dd_df["Tipo"] == "Dataflow")]
    else:
        dd_show = dd_df
    st.dataframe(dd_show, use_container_width=True, hide_index=True)

with st.expander("📋 Dependências das tabelas mapeadas pelo cliente"):
    st.caption(
        "Relações descobertas ao procurar os arquivos .sql/.vw das tabelas do Excel, "
        "incluindo dependências que não alimentam nenhum dashboard conhecido."
    )
    st.dataframe(mapped_df, use_container_width=True, hide_index=True)

with st.expander("🔗 Mapping do cliente → camadas → dashboards"):
    st.caption(
        "Cruza cada tabela do Excel e suas dependências .sql/.vw com os dashboards "
        "que contêm o mesmo nome completo na linhagem direcional."
    )
    st.dataframe(crosswalk_df, use_container_width=True, hide_index=True)

with st.expander("🌐 Fontes SharePoint identificadas na camada Bronze"):
    st.caption(
        "Sites e URLs SharePoint presentes nos datasets; representam fontes de entrada "
        "que serão carregadas por ingestão para Bronze."
    )
    st.dataframe(sharepoint_selected.drop(columns=["_label"], errors="ignore"), use_container_width=True, hide_index=True)
