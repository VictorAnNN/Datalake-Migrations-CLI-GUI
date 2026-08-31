"""Página de dashboard: Grafo Isolado de Linhagem.

Carrega o grafo COMPLETO diretamente do artefato Excel `Linhagem Tabelas`
(o mais recente gerado por `dlctl lineage generate`, ou um arquivo enviado
manualmente pelo usuário) e mostra-o de imediato na tela. A partir daí, o
usuário escolhe uma tabela/fonte e ativa o toggle "Grafico Isolado" para
focar apenas naquela linhagem (upstream/downstream) — a mesma regra do
relatório "Mapa Isolado" do Skill-LineageFabric, agora sem depender de
selecionar uma "geração/batch" no banco local.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[3]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pandas as pd
import streamlit as st

from dlctl.config import load_profile
from dlctl.core import lineage_graph
from dlctl.generators.lineage_generator import (
    dependency_rows_from_dataframe,
    find_latest_lineage_excel,
)

st.set_page_config(page_title="Linhagem — Grafo Isolado", layout="wide", page_icon="🔗")
st.title("🔗 Linhagem do Lakehouse — Grafo e Mapa Isolado")
st.caption(
    "O grafo completo é carregado a partir do artefato Excel `Linhagem Tabelas` "
    "(gerado por `dlctl lineage generate`, com detecção automática do mais recente, "
    "ou enviado manualmente abaixo). Selecione uma tabela/fonte e ative o "
    "**Gráfico Isolado** para focar apenas naquela linhagem."
)

profile_name = st.sidebar.text_input("Profile", value="ms_client_constellation", key="lineage_graph_profile")
try:
    profile = load_profile(profile_name)
except Exception as exc:
    st.error(f"Não foi possível carregar o profile '{profile_name}': {exc}")
    st.stop()

# ---------------------------------------------------------------------------
# Fonte dos dados: Excel mais recente (auto) ou upload manual do usuário
# ---------------------------------------------------------------------------
st.sidebar.header("📄 Fonte do grafo (Excel)")
uploaded_file = st.sidebar.file_uploader(
    "Enviar outro Excel de Linhagem Tabelas", type=["xlsx"],
    help="Precisa conter a aba 'Linhagem Tabelas' com as mesmas colunas do artefato gerado por `dlctl lineage generate`.",
)

excel_source = None
excel_label = ""
if uploaded_file is not None:
    excel_source = io.BytesIO(uploaded_file.getvalue())
    excel_label = f"📤 Enviado manualmente: {uploaded_file.name}"
else:
    latest_path = find_latest_lineage_excel(profile)
    if latest_path is not None:
        excel_source = latest_path
        excel_label = f"📁 Detectado automaticamente: {latest_path.name}"

if excel_source is None:
    st.warning(
        "Nenhum Excel de Linhagem encontrado em `manifests/lineage/`. Rode "
        "`dlctl lineage generate` (veja a página Ações ou o terminal) para gerar um, "
        "ou envie um arquivo `.xlsx` pela barra lateral."
    )
    st.stop()

try:
    lineage_df = pd.read_excel(excel_source, sheet_name="Linhagem Tabelas")
except Exception as exc:
    st.error(f"Não foi possível ler a aba 'Linhagem Tabelas' do Excel selecionado: {exc}")
    st.stop()

st.sidebar.success(excel_label)
if isinstance(excel_source, Path):
    st.sidebar.caption(f"Modificado em: {pd.Timestamp(excel_source.stat().st_mtime, unit='s')}")

if lineage_df.empty:
    st.warning("A aba 'Linhagem Tabelas' deste Excel está vazia.")
    st.stop()

dependency_rows = dependency_rows_from_dataframe(lineage_df)
graph = lineage_graph.build_dependency_graph(dependency_rows)

if graph.number_of_nodes() == 0:
    st.warning("Nenhum nó foi extraído deste Excel — confira se as colunas batem com o formato esperado.")
    st.stop()

# ---------------------------------------------------------------------------
# Filtro opcional por domínio (aplicado sobre o grafo completo)
# ---------------------------------------------------------------------------
domains = sorted({str(row.get("domain", "")).strip() for row in dependency_rows if str(row.get("domain", "")).strip()})
if domains:
    domain_filter = st.sidebar.multiselect("Filtrar por domínio", domains, default=[])
    if domain_filter:
        keep_nodes = {node for node, data in graph.nodes(data=True) if data.get("domain") in domain_filter}
        graph = graph.subgraph(keep_nodes).copy()

# ---------------------------------------------------------------------------
# Seleção de tabela/fonte + toggle "Gráfico Isolado"
# ---------------------------------------------------------------------------
st.sidebar.markdown("---")
st.sidebar.header("🎯 Selecionar tabela/fonte")
node_options = sorted({lineage_graph.node_option_label(graph, n) for n in graph.nodes})
node_to_option = {lineage_graph.node_option_label(graph, n): n for n in graph.nodes}

search_term = st.sidebar.text_input("Buscar por nome (tabela/schema/lakehouse)", placeholder="Ex.: PR_RECEIPT_ORDER")
filtered_options = [opt for opt in node_options if not search_term or search_term.casefold() in opt.casefold()]
selected_option = st.sidebar.selectbox("Tabela/fonte", options=["(nenhuma)"] + filtered_options)

isolate_toggle = st.sidebar.toggle(
    "🔎 Gráfico Isolado (focar apenas nesta linhagem)",
    value=False,
    disabled=(selected_option == "(nenhuma)"),
    help="Ative depois de escolher uma tabela/fonte acima para ver só o upstream/downstream dela.",
)
direction = st.sidebar.radio(
    "Direção do isolamento", ["Linhagem completa", "Downstream", "Upstream"], index=0,
    disabled=not isolate_toggle,
)

if isolate_toggle and selected_option != "(nenhuma)":
    node_id = node_to_option[selected_option]
    subgraph = lineage_graph.isolate_nodes(graph, [node_id], direction)
    isolated = True
    st.success(f"🔗 Gráfico Isolado de **{selected_option}** ({direction}) — {len(subgraph.nodes)} nó(s), {len(subgraph.edges)} relação(ões).")
else:
    subgraph = graph
    isolated = False
    if selected_option != "(nenhuma)":
        st.info(f"Tabela **{selected_option}** selecionada. Ative **Gráfico Isolado** na barra lateral para focar só nessa linhagem.")
    else:
        st.info(f"Exibindo o grafo completo do Excel — {len(graph.nodes)} nó(s), {len(graph.edges)} relação(ões).")

# ---------------------------------------------------------------------------
# Métricas + grafo + legenda + tabelas
# ---------------------------------------------------------------------------
col1, col2, col3, col4 = st.columns(4)
summary = lineage_graph.summarize_by_layer(subgraph)
col1.metric("Bronze", len(summary.get("bronze", [])))
col2.metric("Silver", len(summary.get("silver", [])))
col3.metric("Gold", len(summary.get("gold", [])))
col4.metric("Outra camada/Fonte", len(summary.get("other_layer", [])))

if len(subgraph.nodes) == 0:
    st.warning("Nenhum nó neste subgrafo.")
    st.stop()

MAX_NODES_WARNING = 250
if len(subgraph.nodes) > MAX_NODES_WARNING:
    st.warning(
        f"⚠️ {len(subgraph.nodes)} nós — acima do limite visual recomendado ({MAX_NODES_WARNING}). "
        "Use a busca + Gráfico Isolado para reduzir o escopo."
    )

file_label = uploaded_file.name if uploaded_file is not None else Path(excel_source).stem
with st.spinner("Desenhando o mapa..."):
    fig = lineage_graph.build_plotly_figure(
        subgraph,
        title=f"Gráfico Isolado — {selected_option}" if isolated else f"Mapa completo — {file_label}",
    )
st.plotly_chart(fig, use_container_width=True, config={
    "displayModeBar": True,
    "toImageButtonOptions": {"format": "png", "filename": "mapa_isolado_lineage", "height": 1080, "width": 1920, "scale": 2},
})

st.markdown("#### 📖 Legenda")
legend_cols = st.columns(len(lineage_graph.DATA_LAYER_ORDER))
for col, layer in zip(legend_cols, lineage_graph.DATA_LAYER_ORDER):
    color = lineage_graph.DATA_LAYER_COLORS[layer]
    label = lineage_graph.DATA_LAYER_LABELS[layer]
    col.markdown(
        f"<div style='background:{color};padding:8px 10px;border-radius:6px;"
        f"color:white;font-size:14px;font-weight:bold;text-align:center;'>{label}</div>",
        unsafe_allow_html=True,
    )

st.markdown("#### 📋 Tabelas no mapa (por camada)")
for layer in lineage_graph.DATA_LAYER_ORDER:
    tables = summary.get(layer, [])
    if not tables:
        continue
    with st.expander(f"{lineage_graph.DATA_LAYER_LABELS[layer]} ({len(tables)})"):
        st.write(", ".join(tables))

st.markdown("#### 🔀 Relações no mapa")
edge_rows = []
for source, target, data in subgraph.edges(data=True):
    source_data = subgraph.nodes[source]
    target_data = subgraph.nodes[target]
    edge_rows.append({
        "Camada Origem": source_data.get("data_layer", ""), "Tabela Origem": source_data.get("table", ""),
        "Camada Destino": target_data.get("data_layer", ""), "Tabela Destino": target_data.get("table", ""),
        "Tipo Dependência": data.get("dependency", ""),
    })
edges_df = pd.DataFrame(edge_rows)
st.dataframe(edges_df, use_container_width=True, hide_index=True)
if not edges_df.empty:
    st.download_button(
        "⬇️ Baixar relações (CSV)", edges_df.to_csv(index=False).encode("utf-8"),
        file_name=f"mapa_isolado_{file_label}.csv", mime="text/csv",
    )
