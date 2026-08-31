"""Página de dashboard: Dependências SharePoint.

Mostra a trilha dashboard/relatório -> dataset -> tabela do dataset -> fonte
SharePoint, extraída dos JSONs do Fabric Scanner API por
`dlctl.generators.lineage_generator.build_sharepoint_dependency_trail`, com
validação de existência de cada elo da cadeia — atende ao pedido de
"mapear quais datasets/dashboards precisam de SharePoint e validar o que
existe e o que não existe".
"""
from __future__ import annotations

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[3]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import networkx as nx
import pandas as pd
import streamlit as st
from sqlmodel import select

from dlctl.config import load_profile
from dlctl.core import state as state_db

st.set_page_config(page_title="Linhagem — Dependências SharePoint", layout="wide", page_icon="🧷")
st.title("🧷 Linhagem do Lakehouse — Dependências até o SharePoint")
st.caption(
    "Trilha dashboard/relatório → dataset → tabela do dataset → fonte SharePoint, "
    "extraída dos JSONs do Fabric Scanner API, com validação de existência de cada elo."
)

profile_name = st.sidebar.text_input("Profile", value="ms_client_constellation", key="lineage_sp_profile")
try:
    profile = load_profile(profile_name)
except Exception as exc:
    st.error(f"Não foi possível carregar o profile '{profile_name}': {exc}")
    st.stop()

with state_db.get_session(profile) as session:
    batches = session.exec(
        select(state_db.LineageBatch).where(state_db.LineageBatch.status == "success").order_by(state_db.LineageBatch.finished_at.desc())
    ).all()

if not batches:
    st.warning("Nenhuma geração de linhagem encontrada ainda. Rode `dlctl lineage generate --workspaces-input <pasta/zip>` primeiro.")
    st.stop()

batch_options = {f"{b.finished_at} — {b.batch_id} ({b.sharepoint_rows} linha(s) SharePoint)": b.batch_id for b in batches}
selected_label = st.sidebar.selectbox("Geração (batch)", options=list(batch_options.keys()))
batch_id = batch_options[selected_label]

rows = state_db.get_lineage_sharepoint(profile, batch_id)
if not rows:
    st.info(
        "Nenhuma dependência SharePoint encontrada neste batch. Isso é esperado se "
        "`--workspaces-input` não foi informado em `dlctl lineage generate`, ou se "
        "nenhum dataset/relatório escaneado usa SharePoint como fonte."
    )
    st.stop()

df = pd.DataFrame([row.model_dump(exclude={"id", "batch_id", "created_at"}) for row in rows])

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total de trilhas", len(df))
col2.metric("Existentes", int((df["exists_check"] == "existe").sum()))
col3.metric("Não encontradas", int((df["exists_check"] == "nao_encontrado").sum()))
col4.metric("Dashboards distintos", df.loc[df["report_name"] != "", "report_name"].nunique())

st.markdown("---")
col_a, col_b, col_c = st.columns(3)
workspace_filter = col_a.multiselect("Workspace", sorted(df["workspace"].unique()))
status_filter = col_b.multiselect("Existe?", sorted(df["exists_check"].unique()), default=[])
search = col_c.text_input("Buscar (dashboard/dataset/tabela/URL)")

filtered = df.copy()
if workspace_filter:
    filtered = filtered[filtered["workspace"].isin(workspace_filter)]
if status_filter:
    filtered = filtered[filtered["exists_check"].isin(status_filter)]
if search:
    term = search.casefold()
    mask = filtered.apply(lambda r: term in " ".join(str(v) for v in r.values).casefold(), axis=1)
    filtered = filtered[mask]

st.markdown("#### 📋 Trilhas de dependência")


def _status_badge(value: str) -> str:
    colors = {"existe": "🟢", "nao_encontrado": "🔴", "desconhecido": "⚪"}
    return f"{colors.get(value, '⚪')} {value}"


display_df = filtered.copy()
display_df["exists_check"] = display_df["exists_check"].apply(_status_badge)
display_df = display_df.rename(columns={
    "workspace": "Workspace", "report_name": "Dashboard/Relatório", "dataset_name": "Dataset",
    "dataset_table": "Tabela do Dataset", "sharepoint_reference": "Referência SharePoint",
    "chain_depth": "Profundidade da cadeia", "exists_check": "Existe?", "validation_note": "Nota de validação",
})
st.dataframe(display_df, use_container_width=True, hide_index=True)
st.caption(f"{len(filtered)} de {len(df)} trilha(s).")
st.download_button("⬇️ Baixar trilhas SharePoint (CSV)", filtered.to_csv(index=False).encode("utf-8"),
                    file_name=f"sharepoint_trail_{batch_id}.csv", mime="text/csv")

st.markdown("---")
st.markdown("#### 🗺️ Grafo da trilha (destaca o que não foi encontrado)")

graph = nx.DiGraph()
for _, row in filtered.iterrows():
    report = row["report_name"] or None
    dataset = row["dataset_name"] or "(dataset não encontrado)"
    table = row["dataset_table"] or "(tabela não identificada)"
    sp_ref = row["sharepoint_reference"] or "(referência não resolvida)"
    missing = row["exists_check"] == "nao_encontrado"

    if report:
        graph.add_node(f"RPT::{report}", label=report, kind="report", missing=missing and not dataset)
        graph.add_node(f"DS::{dataset}", label=dataset, kind="dataset", missing=missing)
        graph.add_edge(f"RPT::{report}", f"DS::{dataset}")
    graph.add_node(f"DS::{dataset}", label=dataset, kind="dataset", missing=missing and row["dataset_name"] == "")
    graph.add_node(f"TBL::{dataset}::{table}", label=table, kind="table", missing=missing)
    graph.add_edge(f"DS::{dataset}", f"TBL::{dataset}::{table}")
    graph.add_node(f"SP::{sp_ref}", label=sp_ref[:40], kind="sharepoint", missing=row["sharepoint_reference"] == "")
    graph.add_edge(f"TBL::{dataset}::{table}", f"SP::{sp_ref}")

if graph.number_of_nodes() == 0:
    st.info("Nenhum nó para desenhar com os filtros atuais.")
else:
    import plotly.graph_objects as go

    kind_colors = {"report": "#7E57C2", "dataset": "#4CAF50", "table": "#2196F3", "sharepoint": "#FF9800"}
    kind_labels = {"report": "Dashboard/Relatório", "dataset": "Dataset", "table": "Tabela", "sharepoint": "SharePoint"}
    missing_color = "#E53935"

    layer_of_kind = {"report": 0, "dataset": 1, "table": 2, "sharepoint": 3}
    pos = {}
    buckets: dict[int, list[str]] = {}
    for node, data in graph.nodes(data=True):
        buckets.setdefault(layer_of_kind[data["kind"]], []).append(node)
    for layer_idx, nodes in buckets.items():
        for i, node in enumerate(sorted(nodes)):
            pos[node] = (layer_idx * 3.0, (i - (len(nodes) - 1) / 2) * 2.0)

    edge_x, edge_y = [], []
    for u, v in graph.edges():
        edge_x += [pos[u][0], pos[v][0], None]
        edge_y += [pos[u][1], pos[v][1], None]

    traces = [go.Scatter(x=edge_x, y=edge_y, mode="lines", line=dict(width=1.2, color="#AAAAAA"), hoverinfo="none", showlegend=False)]
    for kind, color in kind_colors.items():
        ok_nodes = [n for n, d in graph.nodes(data=True) if d["kind"] == kind and not d.get("missing")]
        missing_nodes = [n for n, d in graph.nodes(data=True) if d["kind"] == kind and d.get("missing")]
        if ok_nodes:
            traces.append(go.Scatter(
                x=[pos[n][0] for n in ok_nodes], y=[pos[n][1] for n in ok_nodes], mode="markers+text",
                name=kind_labels[kind], marker=dict(size=16, color=color, line=dict(color="white", width=1)),
                text=[graph.nodes[n]["label"][:24] for n in ok_nodes], textposition="top center", textfont=dict(size=9),
            ))
        if missing_nodes:
            traces.append(go.Scatter(
                x=[pos[n][0] for n in missing_nodes], y=[pos[n][1] for n in missing_nodes], mode="markers+text",
                name=f"{kind_labels[kind]} (não encontrado)", marker=dict(size=16, color=missing_color, symbol="x", line=dict(color="white", width=1)),
                text=[graph.nodes[n]["label"][:24] for n in missing_nodes], textposition="top center", textfont=dict(size=9),
            ))

    fig = go.Figure(data=traces)
    fig.update_layout(
        showlegend=True, legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="closest", margin=dict(l=20, r=20, t=40, b=20),
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        paper_bgcolor="#0E1117", plot_bgcolor="#0E1117", font=dict(color="white"), height=650,
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption("🔴 X vermelho = elo da cadeia não encontrado/resolvido (dataset ausente do scan, ou referência SharePoint não resolvida).")
