"""Página de linhagem Fabric: gerar Excels, baixar artefatos e visualizar grafo."""
from __future__ import annotations

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[3]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pandas as pd
import streamlit as st

from dlctl.config import load_profile
from dlctl.core.lineage import (
    apply_lineage_filters,
    build_lineage_sankey_figure,
    generate_lineage_artifacts,
)

st.set_page_config(page_title="Linhagem Fabric", layout="wide", page_icon="🔗")
st.title("🔗 Linhagem Fabric")
st.caption("Gera os 3 arquivos Excel de linhagem e exibe grafo interativo com filtros para validação.")

profile_name = st.sidebar.text_input("Profile", value="ms_client_constellation", key="lineage_profile_name")
try:
    profile = load_profile(profile_name)
except Exception as exc:
    st.error(f"Não foi possível carregar o profile '{profile_name}': {exc}")
    st.stop()


@st.cache_data(show_spinner=False)
def _load_excel(path: str) -> dict[str, pd.DataFrame]:
    sheets: dict[str, pd.DataFrame] = {}
    xls = pd.ExcelFile(path)
    for name in xls.sheet_names:
        sheets[name] = xls.parse(name).fillna("")
    return sheets


st.sidebar.subheader("Geração")
input_path = st.sidebar.text_input(
    "Entrada (ZIP ou pasta JSON)",
    value="",
    help="Ex.: C:\\dados\\Workspaces.zip ou C:\\dados\\Workspaces",
)
default_out = profile.paths.state_root / "lineage"
output_dir = st.sidebar.text_input("Diretório de saída", value=str(default_out))

if st.sidebar.button("Gerar linhagem", type="primary"):
    if not input_path.strip():
        st.error("Informe o caminho de entrada (ZIP ou pasta).")
    else:
        try:
            artifacts = generate_lineage_artifacts(Path(input_path.strip()), Path(output_dir.strip()))
            st.session_state["lineage_artifacts"] = artifacts
            st.success("Arquivos de linhagem gerados com sucesso.")
        except Exception as exc:
            st.error(f"Falha ao gerar linhagem: {exc}")

artifacts = st.session_state.get("lineage_artifacts")
if not artifacts:
    st.info("Use a sidebar para gerar os arquivos. Após gerar, o grafo e os filtros aparecem aqui.")
    st.stop()

col_a, col_b, col_c = st.columns(3)
for col, label, file_path in (
    (col_a, "Original (7 abas)", artifacts.original_excel),
    (col_b, "Simplified Migration (4 abas)", artifacts.simplified_excel),
    (col_c, "PowerQuery Detailed (5 abas)", artifacts.detailed_excel),
):
    col.markdown(f"**{label}**")
    col.code(str(file_path))
    col.download_button(
        label="⬇️ Baixar",
        data=Path(file_path).read_bytes(),
        file_name=Path(file_path).name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

sheets = _load_excel(str(artifacts.original_excel))
lineage_df = sheets.get("Lineage Simplified", pd.DataFrame()).copy()
if lineage_df.empty:
    st.warning("Aba 'Lineage Simplified' não encontrada no arquivo original.")
    st.stop()

st.sidebar.subheader("Filtros do grafo")
ws_options = sorted(lineage_df["workspace_name"].dropna().astype(str).unique().tolist()) if "workspace_name" in lineage_df else []
sel_ws = st.sidebar.multiselect("Workspace", options=ws_options, default=[])
df_ws = lineage_df if not sel_ws else lineage_df[lineage_df["workspace_name"].isin(sel_ws)]
ds_options = sorted(df_ws["dataset_name"].dropna().astype(str).unique().tolist()) if "dataset_name" in df_ws else []
sel_ds = st.sidebar.multiselect("Dataset", options=ds_options, default=[])
dep_options = sorted(lineage_df["dependency_type"].dropna().astype(str).unique().tolist()) if "dependency_type" in lineage_df else []
sel_dep = st.sidebar.multiselect("Tipo de dependência", options=dep_options, default=dep_options)
src_options = sorted(lineage_df["source_type"].dropna().astype(str).unique().tolist()) if "source_type" in lineage_df else []
sel_src = st.sidebar.multiselect("Tipo de origem", options=src_options, default=[])
show_original = st.sidebar.toggle("Mostrar 'Original source'", value=True)
search_text = st.sidebar.text_input("Busca textual (dataset/tabela/origem)", value="")

filtered = apply_lineage_filters(
    lineage_df,
    workspaces=sel_ws,
    datasets=sel_ds,
    dependency_types=sel_dep,
    source_types=sel_src,
    include_original_sources=show_original,
)
if search_text.strip():
    query = search_text.strip().lower()
    mask = (
        filtered.get("dataset_name", pd.Series(dtype=str)).astype(str).str.lower().str.contains(query)
        | filtered.get("dataset_table", pd.Series(dtype=str)).astype(str).str.lower().str.contains(query)
        | filtered.get("source_dataflow_name", pd.Series(dtype=str)).astype(str).str.lower().str.contains(query)
        | filtered.get("table", pd.Series(dtype=str)).astype(str).str.lower().str.contains(query)
    )
    filtered = filtered[mask]

tab_graph, tab_table, tab_stats = st.tabs(["🔗 Grafo", "📋 Tabela", "📊 Estatísticas"])

with tab_graph:
    st.subheader("Grafo de linhagem")
    fig = build_lineage_sankey_figure(filtered, title=f"Linhagem Fabric ({len(filtered)} relações)")
    st.plotly_chart(fig, use_container_width=True)

with tab_table:
    st.subheader("Relações filtradas")
    st.dataframe(filtered, use_container_width=True, height=500)
    st.download_button(
        "⬇️ Baixar CSV filtrado",
        data=filtered.to_csv(index=False).encode("utf-8-sig"),
        file_name="lineage_filtered.csv",
        mime="text/csv",
    )

with tab_stats:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Workspaces", filtered["workspace_name"].nunique() if "workspace_name" in filtered else 0)
    c2.metric("Datasets", filtered["dataset_name"].nunique() if "dataset_name" in filtered else 0)
    c3.metric("Linhas de linhagem", len(filtered))
    c4.metric(
        "Origens distintas",
        filtered["source_type"].nunique() if "source_type" in filtered else 0,
    )

    if "dependency_type" in filtered and not filtered.empty:
        dep_counts = filtered["dependency_type"].value_counts().reset_index()
        dep_counts.columns = ["dependency_type", "count"]
        st.bar_chart(dep_counts, x="dependency_type", y="count")

