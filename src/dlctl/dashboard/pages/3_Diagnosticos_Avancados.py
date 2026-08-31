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

profile_name = st.sidebar.text_input(
    "Profile", value="ms_client_constellation", key="diag_profile_name",
    help="Profile de config/profiles.yaml usado por todos os diagnósticos desta página. Ex.: ms_client_constellation",
)
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
        prio_pick = col1.multiselect(
            "Prioridade", options=sorted(df["priority"].unique()), default=list(sorted(df["priority"].unique())),
            help="Filtra pela prioridade original do backlog. Ex.: P0 (crítico), P1, P2.",
        )
        status_pick = col2.multiselect(
            "Status", options=sorted(df["status"].unique()), default=list(sorted(df["status"].unique())),
            help="Filtra pelo status de tratamento do item no dlctl. Ex.: covered, partial, open.",
        )
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
    definition_file = st.text_input(
        "Caminho do copyjob-content.json", value="",
        placeholder="Ex.: copyjob_definitions/example_copyjob-content.json",
        help="Caminho local (relativo ou absoluto) do arquivo copyjob-content.json a ser auditado.",
    )
    schema_export_file = st.text_input(
        "Caminho do export de schema Oracle (opcional, JSON [{table,column,data_type}])", value="",
        placeholder="Ex.: copyjob_definitions/example_oracle_schema_export.json",
        help="Opcional: JSON com uma lista de {table, column, data_type} do Oracle, usado para "
             "detectar colunas NUMBER sem precisão/escala. Deixe em branco para pular essa checagem.",
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            "Rodar mappings-inspect", type="secondary",
            help="Lista as tabelas/colunas mapeadas no copyjob-content.json informado acima. Somente leitura, offline.",
        ):
            if not definition_file or not Path(definition_file).exists():
                st.error("Arquivo de definição não encontrado.")
            else:
                result = mappings_inspect(definition_file)
                st.write(f"Tabelas mapeadas: {result['table_count']}")
                st.json(result)
    with col2:
        if st.button(
            "Rodar oracle-number-audit", type="primary",
            help="Audita colunas Oracle NUMBER sem precisão/escala no copyjob (evita virarem 'Decimal gigante' "
                 "sem querer). Somente leitura, offline.",
        ):
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
        owner = st.text_input(
            "owner", value="dashboard-user",
            help="Identificador de quem está pedindo o lock (seu usuário ou nome do agente). Ex.: joao.silva",
        )
        workspace_l = st.text_input(
            "workspace", value="",
            placeholder="Ex.: LAKEHOUSE-DEV",
            help="Nome do workspace Fabric a proteger (opcional se você já informar item_ids/tables).",
        )
        item_ids_l = st.text_input(
            "item_ids (CSV)", value="",
            placeholder="Ex.: 3fa1..., 9bd2...",
            help="Lista de IDs de itens Fabric separados por vírgula que ficarão bloqueados por esta lease.",
        )
        tables_l = st.text_input(
            "tables (CSV)", value="",
            placeholder="Ex.: AP_INVOICES_ALL, PR_RECEIPT_ORDER",
            help="Lista de nomes de tabelas separadas por vírgula que ficarão bloqueadas por esta lease.",
        )
        ttl_l = st.number_input(
            "TTL (segundos)", min_value=60, value=3600, step=60,
            help="Tempo de vida da lease em segundos antes de expirar automaticamente. Ex.: 3600 (1 hora).",
        )
        acquire_btn = st.form_submit_button(
            "Adquirir lease", type="primary",
            help="Reserva um cadeado temporário sobre o workspace/itens/tabelas informados acima, bloqueando "
                 "outros owners de escrever neles até o TTL expirar ou a lease ser liberada.",
        )
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
                release_id = st.selectbox(
                    "Lease para liberar", options=active_ids,
                    help="ID da lease ativa a ser liberada (veja a tabela acima).",
                )
            with col_r2:
                release_owner = st.text_input(
                    "owner (deve bater com o dono da lease)", value="dashboard-user",
                    help="Precisa ser exatamente o mesmo 'owner' usado ao adquirir a lease, senão a liberação é recusada.",
                )
            if st.button(
                "Liberar lease",
                help="Libera a lease escolhida acima, desde que o 'owner' informado seja o mesmo que a adquiriu.",
            ):
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
        picked = st.selectbox(
            "Manifesto de campanha", options=rel_options,
            help="Arquivo .yaml em manifests/campaign/ com os alvos e dependências (DAG) da campanha. "
                 "Ex.: gold_order_tracking_completion.campaign.yaml",
        )
        manifest_choice = PROJECT_ROOT / picked
        st.code(manifest_choice.read_text(encoding="utf-8"), language="yaml")
    else:
        st.info("Nenhum manifesto de campanha encontrado em manifests/campaign/. Crie um arquivo YAML lá (veja README).")

    confirm_write_c = st.checkbox(
        "Confirmo escrita (--confirm-write)", key="campaign_confirm_write",
        help="Obrigatório para a fase 'publish' criar/atualizar itens no Fabric durante a campanha.",
    )
    confirm_execute_c = st.checkbox(
        "Confirmo execução (--confirm-execute)", key="campaign_confirm_execute",
        help="Obrigatório para a fase 'execute' disparar a execução real dos itens durante a campanha.",
    )
    if manifest_choice and st.button(
        "🚀 Rodar campanha", type="primary",
        help="Executa todas as fases (preflight->publish->execute->wait->logs->classify->delta->sql_endpoint->seal) "
             "para cada alvo do manifesto, na ordem do DAG, isolando falhas por dependência. Requer os checkboxes "
             "de confirmação marcados conforme as fases que forem tocar escrita/execução.",
    ):
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
    def_payload_file = st.text_input(
        "Caminho do JSON de definição (formato getDefinition)", value="",
        placeholder="Ex.: fabric_definitions/pp_silver_order_tracking_2h.definition.json",
        help="Caminho local do payload de definição (mesmo formato retornado por getDefinition do Fabric) "
             "a ser inspecionado.",
    )
    if st.button(
        "Rodar part-inspect",
        help="Calcula os 3 hashes (aggregate/encoded/decoded) do arquivo de definição informado acima. "
             "Somente leitura, offline.",
    ):
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
    log_text = st.text_area(
        "Cole o conteúdo do log aqui", height=250,
        placeholder="Ex.: cole aqui a saída do driver-log de uma execução de notebook/pipeline",
        help="Texto bruto do log a classificar. Cada linha é comparada contra assinaturas conhecidas de "
             "sucesso/falha; o que não for reconhecido conta como NEVER_PASS.",
    )
    extract_exit = st.checkbox(
        "Extrair apenas saída funcional (--extract-notebook-exit)", value=True,
        help="Se marcado, isola só a saída funcional do notebook (mtExit/exit_value), sem o ruído de shutdown do Spark.",
    )
    if st.button(
        "Classificar log", type="primary",
        help="Analisa o texto colado acima linha a linha e retorna PASS/FAIL/NEVER_PASS. Somente leitura, offline.",
    ):
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
