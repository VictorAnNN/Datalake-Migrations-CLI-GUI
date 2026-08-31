"""dlctl.dashboard.app

Página de controle Streamlit: visão geral do pipeline, mapeamentos,
execuções/atividades, manifests e evidências. Lê diretamente o SQLite
(state/dlctl.db) e os arquivos de evidência gerados pelo CLI `dlctl`.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

# Garante que 'src' está no path quando rodado via `streamlit run`.
SRC_DIR = Path(__file__).resolve().parents[2]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlmodel import select

from dlctl.config import load_domains, load_profile
from dlctl.core.state import (
    ActivityLog,
    ManifestRecord,
    MappingRow,
    OwnershipRecord,
    PipelineRun,
    PipelineStep,
    get_session,
)

st.set_page_config(page_title="Constellation Migration Control", layout="wide", page_icon="🛰️")

DEMO_DATA_BANNER = (
    "🧪 **Dados simulados** — nenhuma ação real foi registrada ainda para este profile/domínio. "
    "Os gráficos e tabelas abaixo são apenas exemplos ilustrativos do que aparecerá aqui. Assim que "
    "você rodar qualquer ação real (pela página **Ações**, ou via `dlctl ...`), esta seção passa a "
    "mostrar automaticamente os seus dados reais, e este aviso desaparece."
)


def _demo_runs_dataframe() -> pd.DataFrame:
    """Execuções fictícias só para ilustrar o layout quando não há dados reais ainda."""
    now = datetime.utcnow()
    rows = [
        {"run_id": "demo_run_001", "domain": "ORDER_TRACKING", "status": "success",
         "started_at": now - timedelta(days=3), "finished_at": now - timedelta(days=3) + timedelta(minutes=40),
         "summary": "[Simulado] Bronze->Silver->Gold concluído com sucesso"},
        {"run_id": "demo_run_002", "domain": "ORDER_TRACKING", "status": "blocked",
         "started_at": now - timedelta(days=2), "finished_at": now - timedelta(days=2) + timedelta(minutes=5),
         "summary": "[Simulado] Bloqueado pelo Central Write Gate (--confirm-write ausente)"},
        {"run_id": "demo_run_003", "domain": "FINANCEIRO", "status": "failed",
         "started_at": now - timedelta(days=1), "finished_at": now - timedelta(days=1) + timedelta(minutes=12),
         "summary": "[Simulado] Falha na validação do Notebook Contract"},
        {"run_id": "demo_run_004", "domain": "FINANCEIRO", "status": "success",
         "started_at": now - timedelta(hours=6), "finished_at": now - timedelta(hours=5),
         "summary": "[Simulado] Execução completa, relatório conectado"},
    ]
    return pd.DataFrame(rows)


def _demo_steps_dataframe() -> pd.DataFrame:
    """Distribuição fictícia de status por passo, só para ilustrar o histograma."""
    step_names = [
        "identify_tables", "generate_silver", "validate_silver", "publish_silver",
        "execute_silver", "generate_gold", "publish_gold", "execute_gold",
    ]
    status_cycle = ["success", "success", "success", "blocked", "failed", "skipped"]
    rows = [
        {"step_name": name, "status": status_cycle[(i + j) % len(status_cycle)]}
        for i, name in enumerate(step_names) for j in range(4)
    ]
    return pd.DataFrame(rows)


def _demo_mappings_dataframe(layer: str) -> pd.DataFrame:
    """Linhas fictícias de mapeamento, só para ilustrar tabela/gráfico de pizza."""
    now = datetime.utcnow().isoformat()
    prefix = "SLV_" if layer == "bronze_to_silver" else "GLD_"
    statuses = ["spark_ready", "spark_ready", "needs_rewrite", "manual_review", "blocked"]
    rows = [
        {"domain": "ORDER_TRACKING" if i % 2 == 0 else "FINANCEIRO",
         "source_table": f"SRC_TABLE_{i:02d}", "target_table": f"{prefix}TABLE_{i:02d}",
         "status": statuses[i % len(statuses)], "sql_file": f"sql/table_{i:02d}.sql",
         "notes": "[Simulado] Exemplo ilustrativo", "updated_at": now}
        for i in range(6)
    ]
    return pd.DataFrame(rows)

st.sidebar.title("🛰️ Constellation Migration Control")
profile_name = st.sidebar.text_input(
    "Profile",
    value="ms_client_constellation",
    help="Nome do profile definido em config/profiles.yaml — controla qual "
         "workspace/credenciais/ambiente (DEV/HML/PRD) esta tela usa. "
         "Ex.: ms_client_constellation",
)

try:
    profile = load_profile(profile_name)
except Exception as exc:
    st.error(f"Não foi possível carregar o profile '{profile_name}': {exc}")
    st.stop()

st.sidebar.markdown(f"**Ambiente:** `{profile.environment}`")
st.sidebar.markdown(f"**allow_write:** `{profile.microsoft.allow_write}`")
st.sidebar.markdown(f"**Workspace:** `{profile.microsoft.default_workspace_name or '(não configurado)'}`")

domains = load_domains()
domain = st.sidebar.selectbox(
    "Domínio",
    options=["(todos)"] + list(domains.keys()),
    help="Filtra execuções e mapeamentos por domínio de negócio cadastrado "
         "em Configuração → Domínios. Escolha '(todos)' para não filtrar. "
         "Ex.: ORDER_TRACKING",
)
domain_filter = None if domain == "(todos)" else domain

st.sidebar.divider()
st.sidebar.markdown(
    "Use `dlctl pipeline run-order-tracking` para gerar novas execuções. "
    "Esta página é somente leitura do estado local (`state/dlctl.db`)."
)

st.title("Painel de Controle — Migração Constellation (Bronze → Silver → Gold → Fabric)")

with get_session(profile) as session:
    runs = session.exec(select(PipelineRun).order_by(PipelineRun.started_at.desc())).all()
    steps = session.exec(select(PipelineStep)).all()
    mappings = session.exec(select(MappingRow)).all()
    manifests = session.exec(select(ManifestRecord)).all()
    activities = session.exec(select(ActivityLog).order_by(ActivityLog.timestamp.desc()).limit(500)).all()
    ownerships = session.exec(select(OwnershipRecord)).all()

if domain_filter:
    runs = [r for r in runs if r.domain == domain_filter]
    mappings = [m for m in mappings if m.domain == domain_filter]

# ---------------- KPIs ----------------
col1, col2, col3, col4 = st.columns(4)
total_runs = len(runs)
success_runs = len([r for r in runs if r.status == "success"])
blocked_runs = len([r for r in runs if r.status == "blocked"])
failed_runs = len([r for r in runs if r.status == "failed"])

col1.metric("Execuções", total_runs)
col2.metric("Sucesso", success_runs)
col3.metric("Bloqueadas", blocked_runs)
col4.metric("Falhas", failed_runs)

tab_overview, tab_mappings, tab_runs, tab_manifests, tab_activity, tab_ownership = st.tabs(
    ["Visão Geral", "Mapeamentos", "Execuções & Passos", "Manifests", "Atividades", "Ownership/Rollback"]
)

# ---------------- Visão Geral ----------------
with tab_overview:
    has_real_runs = bool(runs)
    if not has_real_runs:
        st.warning(DEMO_DATA_BANNER)

    st.subheader("Status das execuções ao longo do tempo")
    if has_real_runs:
        df_runs = pd.DataFrame([r.model_dump() for r in runs])
    else:
        df_runs = _demo_runs_dataframe()
    fig = px.bar(df_runs, x="run_id", y=[1] * len(df_runs), color="status",
                 title="Execuções por status" + ("" if has_real_runs else " (simulado)"),
                 labels={"y": "quantidade"})
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(df_runs[["run_id", "domain", "status", "started_at", "finished_at", "summary"]],
                 use_container_width=True)
    if not has_real_runs:
        st.caption("Rode `dlctl pipeline run-order-tracking` (ou uma ação na página Ações) para gerar dados reais.")

    st.subheader("Distribuição de status por passo (todos os runs)")
    df_steps = pd.DataFrame([s.model_dump() for s in steps]) if steps else _demo_steps_dataframe()
    fig2 = px.histogram(df_steps, x="step_name", color="status", barmode="group",
                         title=None if steps else "(simulado)")
    fig2.update_layout(xaxis_tickangle=-30)
    st.plotly_chart(fig2, use_container_width=True)

# ---------------- Mapeamentos ----------------
with tab_mappings:
    st.subheader("Mapeamentos Bronze → Silver → Gold")
    has_real_mappings = bool(mappings)
    if not has_real_mappings:
        st.warning(DEMO_DATA_BANNER)

    layer_pick = st.radio(
        "Camada",
        options=["bronze_to_silver", "silver_to_gold"],
        horizontal=True,
        help="Qual etapa do pipeline mostrar: 'bronze_to_silver' (mappings/bronze_to_silver.csv) "
             "ou 'silver_to_gold' (mappings/silver_to_gold.csv).",
    )
    if has_real_mappings:
        df_map = pd.DataFrame([m.model_dump() for m in mappings])
        df_layer = df_map[df_map["layer"] == layer_pick]
    else:
        df_layer = _demo_mappings_dataframe(layer_pick)
    status_pick = st.multiselect(
        "Filtrar por status",
        options=sorted(df_layer["status"].unique()),
        default=list(sorted(df_layer["status"].unique())),
        help="Mostra só as linhas com o(s) status marcado(s). "
             "Ex.: 'spark_ready' (pronta para gerar), 'needs_rewrite', 'manual_review', 'blocked'.",
    )
    df_layer = df_layer[df_layer["status"].isin(status_pick)]
    st.dataframe(
        df_layer[["domain", "source_table", "target_table", "status", "sql_file", "notes", "updated_at"]],
        use_container_width=True,
    )
    fig3 = px.pie(df_layer, names="status",
                  title=f"Distribuição de status — {layer_pick}" + ("" if has_real_mappings else " (simulado)"))
    st.plotly_chart(fig3, use_container_width=True)
    if not has_real_mappings:
        st.caption("Rode `dlctl inventory silver` / `dlctl inventory gold` (ou a aba Inventário em Ações) para gerar dados reais.")

# ---------------- Execuções & Passos ----------------
with tab_runs:
    st.subheader("Detalhe de passos por execução")
    if runs:
        run_ids = [r.run_id for r in runs]
        selected_run = st.selectbox(
            "Selecione a execução",
            options=run_ids,
            help="ID da execução (run) do pipeline gerada por `dlctl pipeline run-order-tracking`. "
                 "Escolha uma para ver o passo a passo detalhado abaixo. Ex.: run_20260101_103000",
        )
        run_steps = [s for s in steps if s.run_id == selected_run]
        if run_steps:
            df_rs = pd.DataFrame([s.model_dump() for s in run_steps]).sort_values("step_index")
            color_map = {"success": "green", "failed": "red", "blocked": "orange", "skipped": "gray", "running": "blue", "pending": "lightgray"}
            st.dataframe(df_rs[["step_index", "step_name", "skill", "status", "detail", "started_at", "finished_at"]],
                         use_container_width=True)

            st.markdown("#### Linha do tempo do pipeline")
            for _, row in df_rs.iterrows():
                emoji = {"success": "✅", "failed": "❌", "blocked": "🛑", "skipped": "⏭️", "running": "🔄"}.get(row["status"], "⏳")
                st.write(f"{emoji} **[{row['step_index']}] {row['step_name']}** ({row['skill']}) — {row['status']}  \n_{row['detail']}_")
        else:
            st.info("Sem passos registrados para esta execução.")
    else:
        st.info("Nenhuma execução registrada ainda.")

# ---------------- Manifests ----------------
with tab_manifests:
    st.subheader("Manifests aplicados (Canonical Write Workflow)")
    if manifests:
        df_man = pd.DataFrame([m.model_dump() for m in manifests])
        st.dataframe(df_man[["manifest_id", "resource_type", "display_name", "environment",
                              "operation", "stage", "allow_write", "confirm_write", "updated_at"]],
                     use_container_width=True)
    else:
        st.info("Nenhum manifest processado ainda. Use `dlctl manifest validate|plan|dry-run|apply`.")

# ---------------- Atividades ----------------
with tab_activity:
    st.subheader("Log de atividades (equivalente à trilha de evidência)")
    if activities:
        df_act = pd.DataFrame([a.model_dump() for a in activities])
        level_pick = st.multiselect(
            "Nível",
            options=sorted(df_act["level"].unique()),
            default=list(sorted(df_act["level"].unique())),
            help="Filtra o log por severidade. Ex.: 'INFO' (informativo), 'WARN' (aviso, ex.: retry), "
                 "'BLOCKED' (gate de segurança recusou), 'ERROR' (falha real).",
        )
        df_act = df_act[df_act["level"].isin(level_pick)]
        st.dataframe(df_act[["timestamp", "level", "source", "run_id", "message"]], use_container_width=True)
    else:
        st.info("Nenhuma atividade registrada ainda.")

# ---------------- Ownership / Rollback ----------------
with tab_ownership:
    st.subheader("Recursos com ownership registrado (para rollback controlado)")
    if ownerships:
        df_own = pd.DataFrame([o.model_dump() for o in ownerships])
        st.dataframe(df_own, use_container_width=True)
    else:
        st.info("Nenhum recurso com ownership registrado ainda.")

st.divider()
st.caption(
    "Este painel reflete fielmente o estado local do dlctl (state/dlctl.db). "
    "Nenhuma escrita em Fabric/Oracle é feita a partir desta página — ela é somente leitura."
)
