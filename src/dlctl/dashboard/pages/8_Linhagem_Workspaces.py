"""Página de dashboard: Inventário de Workspaces (Power BI/Fabric).

Inventário achatado e pesquisável de tudo que existe nos JSONs do Fabric
Scanner API informados em `dlctl lineage generate --workspaces-input`:
Workspaces, Datasets, Dataset Tables, Dataflows e Reports/Dashboards —
respondendo perguntas como "em qual workspace está o dataset X?" ou "quais
relatórios existem no workspace Y?" sem precisar abrir os JSONs manualmente.
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

st.set_page_config(page_title="Linhagem — Inventário de Workspaces", layout="wide", page_icon="🔎")
st.title("🔎 Linhagem do Lakehouse — Inventário de Workspaces (Power BI/Fabric)")
st.caption(
    "Pesquise por Workspace, Dataset, Dataset Table, Dataflow ou Report/Dashboard "
    "diretamente nos JSONs do Fabric Scanner API informados em "
    "`dlctl lineage generate --workspaces-input <pasta/zip>`."
)

profile_name = st.sidebar.text_input(
    "Profile", value="ms_client_constellation", key="lineage_workspaces_profile",
    help="Profile de config/profiles.yaml usado para localizar as gerações de linhagem persistidas no state local.",
)
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
    st.warning(
        "Nenhuma geração de linhagem encontrada ainda. **Esta página não aparece vazia por acaso: "
        "os artefatos de Linhagem ainda não foram gerados (ou foram gerados sem informar a pasta/zip "
        "de workspaces).** Para gerar:\n\n"
        "1. Vá em **Ações** (menu lateral) → aba **'7. Linhagem (Azure CLI)'**;\n"
        "2. (Se ainda não tiver notebooks locais) clique em **'🔄 Puxar/atualizar notebooks do "
        "workspace (az login)'**;\n"
        "3. No formulário **'📊 Gerar artefatos de Linhagem'**, preencha o campo **'Pasta ou .zip com "
        "JSONs do Fabric Scanner API'** (obrigatório para este inventário de workspaces) e clique em "
        "**'⚙️ Gerar artefatos de Linhagem'**.\n\n"
        "Assim que o batch terminar com sucesso, volte/recarregue esta página. Equivalente via CLI: "
        "`dlctl lineage generate --workspaces-input <pasta/zip>`."
    )
    st.stop()

batch_options = {f"{b.finished_at} — {b.batch_id} ({b.workspace_item_rows} item(ns))": b.batch_id for b in batches}
selected_label = st.sidebar.selectbox(
    "Geração (batch)", options=list(batch_options.keys()),
    help="Escolha qual execução de `dlctl lineage generate --workspaces-input ...` visualizar.",
)
batch_id = batch_options[selected_label]

rows = state_db.get_lineage_workspace_items(profile, batch_id)
if not rows:
    st.info(
        "Nenhum item de inventário neste batch. Isso é esperado se "
        "`--workspaces-input` não foi informado em `dlctl lineage generate`, ou se "
        "a pasta/zip de JSONs não continha nenhum workspace válido."
    )
    st.stop()

df = pd.DataFrame([row.model_dump(exclude={"id", "batch_id", "created_at"}) for row in rows])

col1, col2, col3, col4 = st.columns(4)
col1.metric("Workspaces", int((df["item_type"] == "Workspace").sum()))
col2.metric("Datasets", int((df["item_type"] == "Dataset").sum()))
col3.metric("Dataflows", int((df["item_type"] == "Dataflow").sum()))
col4.metric("Reports/Dashboards", int((df["item_type"] == "Report").sum()))

st.markdown("---")
col_a, col_b, col_c = st.columns([1, 1, 2])
workspace_filter = col_a.multiselect(
    "Workspace", sorted(df["workspace"].unique()),
    help="Filtra o inventário pelo workspace Power BI/Fabric. Deixe vazio para ver todos.",
)
type_filter = col_b.multiselect(
    "Tipo", sorted(df["item_type"].unique()),
    help="Filtra pelo tipo de item. Ex.: Workspace, Dataset, Dataset Table, Dataflow, Report.",
)
search = col_c.text_input(
    "Buscar (workspace, dataset, dataflow, report, tabela...)",
    placeholder="Ex.: LAKEHOUSE-DEV, Dataset Recebimento, Dashboard...",
    help="Busca por texto parcial em qualquer coluna do item (nome, workspace, detalhe, etc.).",
)

filtered = df.copy()
if workspace_filter:
    filtered = filtered[filtered["workspace"].isin(workspace_filter)]
if type_filter:
    filtered = filtered[filtered["item_type"].isin(type_filter)]
if search:
    term = search.casefold()
    mask = filtered.apply(lambda r: term in " ".join(str(v) for v in r.values).casefold(), axis=1)
    filtered = filtered[mask]

st.markdown("#### 📋 Itens encontrados")
display_df = filtered.rename(columns={
    "workspace": "Workspace", "workspace_id": "Workspace ID", "item_type": "Tipo",
    "item_name": "Nome", "item_id": "ID", "parent_name": "Pertence a", "detail": "Detalhe",
    "source_file": "Arquivo de origem",
})
st.dataframe(display_df, use_container_width=True, hide_index=True)
st.caption(f"{len(filtered)} de {len(df)} item(ns).")
st.download_button(
    "⬇️ Baixar inventário (CSV)", filtered.to_csv(index=False).encode("utf-8"),
    file_name=f"workspace_inventory_{batch_id}.csv", mime="text/csv",
    help="Baixa os itens filtrados exibidos acima como arquivo .csv.",
)

st.markdown("---")
st.markdown("#### 🌳 Navegar por Workspace")
selected_workspace = st.selectbox(
    "Escolha um workspace para ver a árvore de itens", options=["(nenhum)"] + sorted(df["workspace"].unique()),
    help="Mostra Datasets/Dataflows/Reports pertencentes ao workspace escolhido, agrupados em árvore.",
)
if selected_workspace != "(nenhum)":
    ws_rows = df[df["workspace"] == selected_workspace]
    for item_type in ["Dataset", "Dataflow", "Report"]:
        subset = ws_rows[ws_rows["item_type"] == item_type]
        if subset.empty:
            continue
        with st.expander(f"{item_type} ({len(subset)})", expanded=(item_type == "Dataset")):
            for _, row in subset.iterrows():
                st.markdown(f"- **{row['item_name']}** — {row['detail']}")
                if item_type == "Dataset":
                    tables = ws_rows[(ws_rows["item_type"] == "Dataset Table") & (ws_rows["parent_name"] == row["item_name"])]
                    if not tables.empty:
                        st.markdown("  Tabelas: " + ", ".join(f"`{t}`" for t in tables["item_name"]))
