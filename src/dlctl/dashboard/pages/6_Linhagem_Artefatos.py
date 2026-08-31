"""Página de dashboard: Artefatos de Linhagem.

Visualizador genérico dos demais artefatos gerados por `dlctl lineage
generate` — hoje: o catálogo "Tabelas" (30 colunas) e a própria "Linhagem
Tabelas" em formato tabular (com filtros/busca), complementando o Grafo
Isolado da página anterior.
"""
from __future__ import annotations

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[3]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pandas as pd
import streamlit as st
from sqlmodel import select

from dlctl.config import load_profile
from dlctl.core import state as state_db

st.set_page_config(page_title="Linhagem — Artefatos", layout="wide", page_icon="📋")
st.title("📋 Linhagem do Lakehouse — Artefatos")
st.caption(
    "Visualização tabular dos artefatos gerados por `dlctl lineage generate`: "
    "catálogo de Tabelas e Linhagem Tabelas (com as relações transitivas)."
)

profile_name = st.sidebar.text_input("Profile", value="ms_client_constellation", key="lineage_artifacts_profile")
try:
    profile = load_profile(profile_name)
except Exception as exc:
    st.error(f"Não foi possível carregar o profile '{profile_name}': {exc}")
    st.stop()

with state_db.get_session(profile) as session:
    batches = session.exec(
        select(state_db.LineageBatch).order_by(state_db.LineageBatch.started_at.desc())
    ).all()

if not batches:
    st.warning("Nenhuma geração de linhagem encontrada ainda. Rode `dlctl lineage generate` primeiro.")
    st.stop()

batch_options = {
    f"{b.started_at} — {b.batch_id} [{b.status}]": b.batch_id for b in batches
}
selected_label = st.sidebar.selectbox("Geração (batch)", options=list(batch_options.keys()))
batch_id = batch_options[selected_label]

selected_batch = next(b for b in batches if b.batch_id == batch_id)
if selected_batch.status != "success":
    st.warning(f"Este batch terminou com status '{selected_batch.status}': {selected_batch.summary}")

tab_catalog, tab_lineage, tab_batches = st.tabs(["🗂️ Tabelas (catálogo)", "🔗 Linhagem Tabelas", "🕒 Histórico de gerações"])

with tab_catalog:
    catalog_rows = state_db.get_lineage_catalog(profile, batch_id)
    if not catalog_rows:
        st.info("Nenhuma linha de catálogo (Tabelas) neste batch — normalmente vem de notebooks de configuração (`TABLE_CONFIG_ROWS_JSON`).")
    else:
        df = pd.DataFrame([row.model_dump(exclude={"id", "batch_id", "created_at"}) for row in catalog_rows])
        col1, col2, col3 = st.columns(3)
        domain_filter = col1.multiselect("Domínio", sorted(df["domain"].unique()))
        layer_filter = col2.multiselect("Camada Destino", sorted(df["target_layer"].unique()))
        search = col3.text_input("Buscar (tabela/fonte/sistema)")

        filtered = df.copy()
        if domain_filter:
            filtered = filtered[filtered["domain"].isin(domain_filter)]
        if layer_filter:
            filtered = filtered[filtered["target_layer"].isin(layer_filter)]
        if search:
            term = search.casefold()
            mask = filtered.apply(lambda r: term in " ".join(str(v) for v in r.values).casefold(), axis=1)
            filtered = filtered[mask]

        st.dataframe(filtered, use_container_width=True, hide_index=True)
        st.caption(f"{len(filtered)} de {len(df)} linha(s).")
        st.download_button("⬇️ Baixar Tabelas (CSV)", filtered.to_csv(index=False).encode("utf-8"),
                            file_name=f"tabelas_{batch_id}.csv", mime="text/csv")

with tab_lineage:
    dependency_rows = state_db.get_lineage_dependencies(profile, batch_id)
    if not dependency_rows:
        st.info("Nenhuma linha de Linhagem Tabelas neste batch.")
    else:
        df = pd.DataFrame([row.model_dump(exclude={"id", "batch_id", "created_at"}) for row in dependency_rows])
        col1, col2, col3, col4 = st.columns(4)
        domain_filter = col1.multiselect("Domínio", sorted(df["domain"].unique()), key="lin_domain")
        origin_filter = col2.multiselect("Camada Origem", sorted(df["source_layer"].unique()), key="lin_origin")
        dest_filter = col3.multiselect("Camada Destino", sorted(df["target_layer"].unique()), key="lin_dest")
        only_transitive = col4.checkbox("Somente transitivas", value=False)

        filtered = df.copy()
        if domain_filter:
            filtered = filtered[filtered["domain"].isin(domain_filter)]
        if origin_filter:
            filtered = filtered[filtered["source_layer"].isin(origin_filter)]
        if dest_filter:
            filtered = filtered[filtered["target_layer"].isin(dest_filter)]
        if only_transitive:
            filtered = filtered[filtered["is_transitive"]]

        st.dataframe(filtered, use_container_width=True, hide_index=True)
        st.caption(f"{len(filtered)} de {len(df)} linha(s) — {int(df['is_transitive'].sum())} transitiva(s) no total.")
        st.download_button("⬇️ Baixar Linhagem Tabelas (CSV)", filtered.to_csv(index=False).encode("utf-8"),
                            file_name=f"linhagem_tabelas_{batch_id}.csv", mime="text/csv")

with tab_batches:
    history_df = pd.DataFrame([{
        "batch_id": b.batch_id, "status": b.status, "iniciado_em": b.started_at, "finalizado_em": b.finished_at,
        "dependências": b.dependency_rows, "catálogo": b.catalog_rows, "sharepoint": b.sharepoint_rows,
        "resumo": b.summary,
    } for b in batches])
    st.dataframe(history_df, use_container_width=True, hide_index=True)
