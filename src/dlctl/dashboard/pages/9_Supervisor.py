"""Página de dashboard: Supervisor — escopo TOTAL do projeto.

Fonte ÚNICA: `input/sharedpoint` (Excel "Projeto Lakehouse - Tabelas e
Pipelines.xlsx", aba "Tabelas" + scripts .sql/.prc em x_Estrutura/) — esta
página não olha para input/lakehouse-dev, input/lakehouse-hml nem
input/Workspaces. Responde: quantas tabelas ao todo, quantas por camada
(Bronze/Silver/Gold/outras) e quantos dashboards precisam ser migrados no
projeto inteiro.

Sempre que a página abre, carrega o artefato mais recente já gerado em
`manifests/dashboard/` (não reprocessa Excel/SQL a cada acesso) — clique em
"🔎 Rodar diagnóstico" para recalcular do zero e gerar um artefato novo.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[3]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from dlctl.config import load_profile
from dlctl.core.global_scope import (
    compute_global_scope,
    export_global_scope_report,
    list_scope_snapshots,
    load_latest_scope_snapshot,
)

# Paleta "enterprise": tons sóbrios de azul-marinho/verde-petróleo/âmbar em vez de
# cores vivas de dashboard consumer — usada em todos os gráficos desta página.
COLOR_PRIMARY = "#13315C"     # navy — série principal
COLOR_SECONDARY = "#5E7CA3"   # azul-aço — neutro
COLOR_SUCCESS = "#1F7A5C"     # verde-petróleo
COLOR_WARNING = "#C98B32"     # âmbar — descobertas via SQL
COLOR_DANGER = "#A6434A"      # vermelho-tijolo
COLOR_NEUTRAL = "#8492A6"     # cinza-ardósia
CATEGORY_COLOR_SEQUENCE = [COLOR_PRIMARY, COLOR_SECONDARY, COLOR_SUCCESS, COLOR_WARNING, COLOR_NEUTRAL, COLOR_DANGER, "#3E5C76"]

# Nomes de camada sempre em português na tela (a fonte/Excel usa Bronze/Silver/Gold
# em inglês) e ordem fixa Bronze -> Prata -> Ouro -> demais, em vez da ordem por contagem.
CAMADA_LABEL_PT = {"bronze": "Bronze", "silver": "Prata", "gold": "Ouro"}
CAMADA_ORDER = {"bronze": 0, "silver": 1, "gold": 2}


def _camada_label(nome: str) -> str:
    return CAMADA_LABEL_PT.get(nome.strip().lower(), nome)


def _ordenar_camadas(camadas: list[dict]) -> list[dict]:
    return sorted(camadas, key=lambda c: CAMADA_ORDER.get(c["camada"].strip().lower(), 99))

st.set_page_config(page_title="Supervisor — Constellation Migration Control", layout="wide", page_icon="🧭")
st.title("🧭 Supervisor — Escopo Total do Projeto")
st.caption(
    "Quantas tabelas (e dashboards) precisam ser migrados no projeto INTEIRO — fonte única: "
    "`input/sharedpoint` (Excel 'Projeto Lakehouse - Tabelas e Pipelines.xlsx', aba 'Tabelas' + tabelas "
    "descobertas via SQL em `x_Estrutura/`). Não depende de input/lakehouse-dev, lakehouse-hml nem Workspaces."
)

profile_name = st.sidebar.text_input(
    "Profile", value="ms_client_constellation", key="supervisor_profile",
    help="Profile de config/profiles.yaml usado para localizar manifests/dashboard/ (onde os artefatos são salvos).",
)
try:
    profile = load_profile(profile_name)
except Exception as exc:
    st.error(f"Não foi possível carregar o profile '{profile_name}': {exc}")
    st.stop()

sharedpoint_input = st.text_input(
    "Pasta SharePoint", value="input/sharedpoint",
    help="Pasta com 'Projeto Lakehouse - Tabelas e Pipelines.xlsx' (aba 'Tabelas') + x_Estrutura/ "
         "(scripts .sql/.prc vasculhados por tabelas referenciadas via FROM/JOIN que não estão no Excel).",
)

artifacts_dir = profile.paths.manifests_root / "dashboard"

if st.button(
    "🔎 Rodar diagnóstico", type="primary",
    help="Reprocessa o Excel + scripts SQL de input/sharedpoint do zero e gera um novo artefato. Sem clicar "
         "aqui, a página carrega sempre o último artefato já gerado (não reprocessa a cada acesso).",
):
    with st.spinner("Lendo Excel + vasculhando scripts SQL em input/sharedpoint..."):
        scope = compute_global_scope(sharedpoint_input)
    if not scope["excel_found"]:
        st.error(f"Excel não encontrado em `{scope['excel_path']}`.")
    else:
        batch_id = f"escopo_{datetime.now():%Y%m%d_%H%M%S}"
        paths = export_global_scope_report(scope, artifacts_dir, batch_id)
        st.session_state["scope_result"] = {
            **scope, "batch_id": batch_id,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "excel_path": paths["excel_path"],
        }
        st.success(f"✅ Artefato gerado: `{paths['excel_path']}`")

if "scope_result" not in st.session_state:
    latest = load_latest_scope_snapshot(artifacts_dir)
    if latest:
        st.session_state["scope_result"] = latest

result = st.session_state.get("scope_result")

if not result:
    st.info(
        "Nenhum artefato de escopo encontrado ainda em `manifests/dashboard/`. Clique em **🔎 Rodar "
        "diagnóstico** acima para gerar o primeiro, pesquisando somente em `input/sharedpoint`."
    )
    st.stop()

st.caption(f"Última geração: {result['generated_at']} — artefato: `{result['excel_path']}`")

dashboard_target = result.get("dashboard_target")
camadas_ordenadas = _ordenar_camadas(result["camadas"])
cols_scope = st.columns(len(camadas_ordenadas) + 1 + (1 if dashboard_target else 0))
with cols_scope[0]:
    st.metric("Total de tabelas", result["total_tabelas"])
for col, c in zip(cols_scope[1:], camadas_ordenadas):
    with col:
        extra = f"+{c['descobertas_sql']} via SQL" if c["descobertas_sql"] else None
        st.metric(_camada_label(c["camada"]), c["total"], extra, delta_color="off")
if dashboard_target:
    with cols_scope[-1]:
        st.metric("Total de dashboards", dashboard_target["total"], help=dashboard_target["fonte_texto"])

st.markdown("---")
col_bar, col_pie = st.columns(2)
with col_bar:
    camadas_df = pd.DataFrame(camadas_ordenadas)
    camadas_df["camada"] = camadas_df["camada"].map(_camada_label)
    camadas_df["existente_excel"] = camadas_df["total"] - camadas_df["descobertas_sql"]
    bar_fig = go.Figure(data=[
        go.Bar(name="No Excel", x=camadas_df["camada"], y=camadas_df["existente_excel"], marker_color=COLOR_PRIMARY),
        go.Bar(name="Descobertas via SQL", x=camadas_df["camada"], y=camadas_df["descobertas_sql"], marker_color=COLOR_WARNING),
    ])
    bar_fig.update_layout(
        barmode="stack", height=320, margin=dict(l=20, r=20, t=40, b=60),
        title="Tabelas por camada: Excel vs. descobertas via SQL",
        legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5),
    )
    st.plotly_chart(bar_fig, use_container_width=True)
with col_pie:
    pie_fig = px.pie(
        camadas_df, names="camada", values="total", title="Distribuição das tabelas por camada", hole=0.45,
        color_discrete_sequence=CATEGORY_COLOR_SEQUENCE,
    )
    pie_fig.update_layout(height=320, margin=dict(l=20, r=20, t=40, b=10))
    st.plotly_chart(pie_fig, use_container_width=True)

if result["descobertas_sql"]:
    with st.expander(f"🔍 {len(result['descobertas_sql'])} tabela(s) descoberta(s) via SQL (não estavam no Excel)"):
        descobertas_df = pd.DataFrame(result["descobertas_sql"])
        descobertas_df["camada"] = descobertas_df["camada"].map(_camada_label)
        st.dataframe(
            descobertas_df.rename(columns={
                "tabela": "Tabela", "camada": "Camada (por prefixo)", "dominio": "Domínio", "detalhe": "Encontrada em",
            })[["Tabela", "Camada (por prefixo)", "Domínio", "Encontrada em"]],
            use_container_width=True, hide_index=True,
        )

with st.expander("🗂️ Todas as tabelas do escopo (Excel + SQL)"):
    rows_df = pd.DataFrame(result["rows"])
    if rows_df.empty:
        st.info("Nenhuma tabela encontrada.")
    else:
        rows_df["camada"] = rows_df["camada"].map(_camada_label)
        cat_pick = st.multiselect(
            "Filtrar por camada", sorted(rows_df["camada"].unique()),
            help="Filtra a lista de tabelas pela camada (Bronze/Prata/Ouro/etc.).",
        )
        shown = rows_df[rows_df["camada"].isin(cat_pick)] if cat_pick else rows_df
        st.dataframe(
            shown.rename(columns={
                "tabela": "Tabela", "camada": "Camada", "dominio": "Domínio", "origem": "Origem", "detalhe": "Detalhe",
            })[["Tabela", "Camada", "Domínio", "Origem", "Detalhe"]],
            use_container_width=True, hide_index=True,
        )

st.markdown("---")
st.markdown("#### 🕒 Histórico de gerações")
snapshots = list_scope_snapshots(artifacts_dir)
if len(snapshots) < 2:
    st.caption("Gere pelo menos 2 artefatos (botão '🔎 Rodar diagnóstico') para ver a evolução do escopo ao longo do tempo.")
else:
    ordered = sorted(snapshots, key=lambda s: s["generated_at"])
    history_df = pd.DataFrame([{
        "Gerado em": s["generated_at"], "Total de tabelas": s["total_tabelas"],
        "Dashboards (meta)": s.get("dashboard_target", {}).get("total") if s.get("dashboard_target") else "-",
        "Artefato": s["excel_path"],
    } for s in ordered])
    st.dataframe(history_df, use_container_width=True, hide_index=True)

    trend_fig = px.line(
        history_df, x="Gerado em", y="Total de tabelas", markers=True,
        title="Evolução do total de tabelas no escopo",
    )
    trend_fig.update_traces(line_color=COLOR_PRIMARY, marker_color=COLOR_PRIMARY)
    trend_fig.update_layout(height=280, margin=dict(l=20, r=20, t=40, b=10))
    st.plotly_chart(trend_fig, use_container_width=True)


