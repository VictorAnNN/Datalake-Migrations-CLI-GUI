"""Página "Diagnósticos Avançados": incorpora as lacunas do
fabric-fullctl-backlog.zip (3 incidentes reais) como funcionalidades
locais/offline no dashboard — rastreio de backlog, auditoria de Copy Job
Oracle NUMBER, leases (lock entre agentes), campanha multi-alvo (execute
campaign), inspeção de definições (hash triad) e classificador de logs.

IMPORTANTE: nenhuma ação nesta página faz uma chamada real ao Fabric/Oracle
por padrão. Onde uma fase dependeria de um client autenticado (wait, logs
reais, sql_endpoint), o resultado é sempre `skipped`/`manual_required` —
por instrução explícita, esta sessão não testa/aciona nenhum endpoint real.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[3]
PROJECT_ROOT = SRC_DIR.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pandas as pd
import streamlit as st

from dlctl.config import load_profile
from dlctl.core.campaign import run_campaign
from dlctl.core.copyjob_audit import mappings_inspect, oracle_number_audit
from dlctl.core.definitions_inspect import part_inspect
from dlctl.core.log_classifier import classify_log
from dlctl.core.state import (
    BacklogItem,
    CampaignRun,
    CampaignStep,
    acquire_lease,
    get_session,
    list_leases,
    release_lease,
    seed_backlog,
)
from sqlmodel import select

st.set_page_config(page_title="Diagnósticos Avançados — Constellation Migration Control", layout="wide", page_icon="🧩")
st.title("🧩 Diagnósticos Avançados (backlog fabric-fullctl)")
st.caption(
    "Funcionalidades incorporadas de 3 incidentes reais de produção — todas locais/offline nesta sessão. "
    "Nenhuma chamada real a Fabric/Oracle é feita a partir desta página."
)

profile_name = st.sidebar.text_input("Profile", value="ms_client_constellation", key="diag_profile_name")
try:
    profile = load_profile(profile_name)
except Exception as exc:
    st.error(f"Não foi possível carregar o profile '{profile_name}': {exc}")
    st.stop()

seed_backlog(profile)  # idempotente — garante que a tabela de rastreio está populada

(
    tab_backlog,
    tab_copyjob,
    tab_leases,
    tab_campaign,
    tab_definitions,
    tab_logs,
) = st.tabs([
    "📋 Backlog Tracker", "🔎 Auditoria Copy Job", "🔒 Leases", "🚀 Execute Campaign",
    "🧬 Definitions Inspect", "📜 Log Classifier",
])

# ==================== Backlog Tracker ====================
with tab_backlog:
    st.subheader("Rastreio das lacunas levantadas nos incidentes 1, 2 e Nota 3")
    with get_session(profile) as session:
        items = session.exec(select(BacklogItem)).all()
    df = pd.DataFrame([i.model_dump() for i in items])
    if not df.empty:
        col1, col2 = st.columns(2)
        prio_pick = col1.multiselect("Prioridade", options=sorted(df["priority"].unique()), default=list(sorted(df["priority"].unique())))
        status_pick = col2.multiselect("Status", options=sorted(df["status"].unique()), default=list(sorted(df["status"].unique())))
        df_f = df[df["priority"].isin(prio_pick) & df["status"].isin(status_pick)]
        st.dataframe(
            df_f[["priority", "origin", "gap", "proposal", "status", "implemented_in_dlctl"]].sort_values("priority"),
            use_container_width=True, height=500,
        )
        st.caption(f"Total: {len(df)} itens | Cobertos com algo no dlctl: {len(df[df['implemented_in_dlctl'] != ''])}")
    else:
        st.info("Backlog vazio — algo deu errado no seed.")

# ==================== Auditoria Copy Job ====================
with tab_copyjob:
    st.subheader("Auditoria semântica de mappings de Copy Job (Oracle NUMBER)")
    st.caption(
        "Incid. 1, P0: identificação de 970 colunas Oracle NUMBER feita por script ad hoc. "
        "Aqui: upload/seleção de um copyjob-content.json local (e, opcionalmente, um export de schema Oracle)."
    )
    definition_file = st.text_input("Caminho do copyjob-content.json", value="")
    schema_export_file = st.text_input("Caminho do export de schema Oracle (opcional, JSON [{table,column,data_type}])", value="")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Rodar mappings-inspect", type="secondary"):
            if not definition_file or not Path(definition_file).exists():
                st.error("Arquivo de definição não encontrado.")
            else:
                result = mappings_inspect(definition_file)
                st.write(f"Tabelas mapeadas: {result['table_count']}")
                st.json(result)
    with col2:
        if st.button("Rodar oracle-number-audit", type="primary"):
            if not definition_file or not Path(definition_file).exists():
                st.error("Arquivo de definição não encontrado.")
            else:
                outcome = oracle_number_audit(definition_file, schema_export_file or None)
                st.write(f"Colunas verificadas: {outcome.total_columns_checked}")
                if outcome.unmapped_tables:
                    st.error(f"Tabelas sem mapping: {outcome.unmapped_tables}")
                if outcome.unmapped_columns:
                    st.error(f"{len(outcome.unmapped_columns)} coluna(s) sem mapping:")
                    st.dataframe(outcome.unmapped_columns, use_container_width=True)
                if outcome.issues:
                    st.dataframe([i.__dict__ for i in outcome.issues], use_container_width=True)
                (st.success if outcome.ok else st.error)(
                    "Auditoria OK: nenhum problema bloqueante." if outcome.ok else "Auditoria com problemas bloqueantes."
                )

# ==================== Leases ====================
with tab_leases:
    st.subheader("Leases — lock leve entre agentes (Incid. 1, P0: 'sem lock entre agentes')")
    with st.form("form_lease_acquire"):
        owner = st.text_input("owner", value="dashboard-user")
        workspace_l = st.text_input("workspace", value="")
        item_ids_l = st.text_input("item_ids (CSV)", value="")
        tables_l = st.text_input("tables (CSV)", value="")
        ttl_l = st.number_input("TTL (segundos)", min_value=60, value=3600, step=60)
        acquire_btn = st.form_submit_button("Adquirir lease", type="primary")
    if acquire_btn:
        result = acquire_lease(
            profile, workspace=workspace_l,
            item_ids=[i for i in item_ids_l.split(",") if i], tables=[t for t in tables_l.split(",") if t],
            owner=owner, ttl_seconds=int(ttl_l),
        )
        if result["ok"]:
            st.success(f"Lease adquirida: {result['lease_id']}")
        else:
            st.warning(f"BLOCKED: {result['message']}")

    st.divider()
    leases = list_leases(profile, active_only=False)
    if leases:
        st.dataframe(leases, use_container_width=True)
        active_ids = [l["lease_id"] for l in leases if l["status"] == "active"]
        if active_ids:
            col_r1, col_r2 = st.columns(2)
            with col_r1:
                release_id = st.selectbox("Lease para liberar", options=active_ids)
            with col_r2:
                release_owner = st.text_input("owner (deve bater com o dono da lease)", value="dashboard-user")
            if st.button("Liberar lease"):
                result = release_lease(profile, release_id, release_owner)
                (st.success if result["ok"] else st.error)(result.get("message", "Liberada."))
                st.rerun()
    else:
        st.info("Nenhuma lease registrada ainda.")

# ==================== Execute Campaign ====================
with tab_campaign:
    st.subheader("Execute Campaign — orquestrador multi-alvo (Incid. 2, P0)")
    st.caption(
        "Manifesto YAML com múltiplos alvos e dependências (DAG). Fases por alvo: "
        "preflight -> publish -> execute -> wait -> logs -> classify -> delta -> sql_endpoint -> seal. "
        "Fases de rede real (wait/logs/sql_endpoint) sempre reportam manual_required nesta sessão."
    )
    manifests_dir = profile.paths.manifests_root
    campaign_files = sorted((manifests_dir / "campaign").glob("*.yaml")) if (manifests_dir / "campaign").exists() else []
    manifest_choice = None
    if campaign_files:
        rel_options = [str(p.relative_to(PROJECT_ROOT)) for p in campaign_files]
        picked = st.selectbox("Manifesto de campanha", options=rel_options)
        manifest_choice = PROJECT_ROOT / picked
        st.code(manifest_choice.read_text(encoding="utf-8"), language="yaml")
    else:
        st.info("Nenhum manifesto de campanha encontrado em manifests/campaign/. Crie um arquivo YAML lá (veja README).")

    confirm_write_c = st.checkbox("Confirmo escrita (--confirm-write)", key="campaign_confirm_write")
    confirm_execute_c = st.checkbox("Confirmo execução (--confirm-execute)", key="campaign_confirm_execute")
    if manifest_choice and st.button("🚀 Rodar campanha", type="primary"):
        steps_log = []

        def on_step(target, phase, status, detail):
            steps_log.append({"target": target, "phase": phase, "status": status, "detail": detail})

        with st.spinner("Executando campanha..."):
            result = run_campaign(
                profile, manifest_choice, confirm_write=confirm_write_c, confirm_execute=confirm_execute_c,
                fabric_client=None,  # nunca usar client real nesta sessão
                on_step=on_step,
            )
        emoji_map = {"success": "✅", "failed": "❌", "blocked": "🛑", "skipped": "⏭️"}
        for s in steps_log:
            st.write(f"{emoji_map.get(s['status'], '⏳')} **[{s['target']}/{s['phase']}]** {s['status']} — {s['detail']}")
        (st.success if result["status"] == "success" else st.error)(
            f"Campaign {result['status']}: {result['campaign_id']} — {result['summary']}"
        )

    st.divider()
    st.markdown("**Histórico de campanhas**")
    with get_session(profile) as session:
        campaigns = session.exec(select(CampaignRun).order_by(CampaignRun.started_at.desc())).all()
    if campaigns:
        st.dataframe([c.model_dump() for c in campaigns], use_container_width=True)

# ==================== Definitions Inspect ====================
with tab_definitions:
    st.subheader("Definitions Part Inspect — hash triad (Incid. 1, P2)")
    st.caption("Resolve a ambiguidade: aggregateDefinitionSha256 vs. encodedPayloadSha256 vs. decodedContentSha256.")
    def_payload_file = st.text_input("Caminho do JSON de definição (formato getDefinition)", value="")
    if st.button("Rodar part-inspect"):
        if not def_payload_file or not Path(def_payload_file).exists():
            st.error("Arquivo não encontrado.")
        else:
            result = part_inspect(def_payload_file)
            st.write(f"**aggregateDefinitionSha256**: `{result['aggregateDefinitionSha256']}`")
            st.dataframe(result["parts"], use_container_width=True)
            if result["semantic_summary"]:
                st.json(result["semantic_summary"])

# ==================== Log Classifier ====================
with tab_logs:
    st.subheader("Classificador phase-aware de logs (Incid. 2, P0)")
    st.caption("Assinatura desconhecida é sempre NEVER_PASS por padrão — nunca deixa passar silenciosamente.")
    log_text = st.text_area("Cole o conteúdo do log aqui", height=250)
    extract_exit = st.checkbox("Extrair apenas saída funcional (--extract-notebook-exit)", value=True)
    if st.button("Classificar log", type="primary"):
        if not log_text.strip():
            st.warning("Cole algum log primeiro.")
        else:
            outcome = classify_log(log_text, extract_notebook_exit=extract_exit)
            color_fn = {"PASS": st.success, "FAIL": st.error, "NEVER_PASS": st.warning}
            color_fn.get(outcome.overall, st.info)(f"Veredito geral: {outcome.overall} ({outcome.total_lines} linhas)")
            if outcome.unknown_lines:
                st.warning(f"{len(outcome.unknown_lines)} linha(s) com assinatura desconhecida:")
                st.code("\n".join(outcome.unknown_lines[:30]))
            if outcome.functional_exit:
                st.markdown("**Saída funcional (sem ruído de shutdown):**")
                st.code(outcome.functional_exit)
