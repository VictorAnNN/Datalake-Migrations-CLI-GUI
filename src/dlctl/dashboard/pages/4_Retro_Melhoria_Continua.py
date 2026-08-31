"""Página "Retro / Melhoria Contínua": analisa a telemetria do próprio dlctl
(ActivityLog, PipelineStep, ManifestRecord, CampaignStep, CommandInvocation)
e gera propostas de melhoria categorizadas, no mesmo formato do relatório
"Improvement Proposals (retro)". Fluxo de aprovação manual (Stage B):
nada é aplicado automaticamente — apenas marcado aprovado/rejeitado aqui.
"""
from __future__ import annotations

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[3]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pandas as pd
import streamlit as st

from dlctl.config import load_profile
from dlctl.core.retro import analyze, approve_proposal, reject_proposal, render_markdown_report
from dlctl.core.state import list_retro_proposals

st.set_page_config(page_title="Retro / Melhoria Contínua — Constellation Migration Control", layout="wide", page_icon="🔁")
st.title("🔁 Retro / Melhoria Contínua")
st.caption(
    "Analisa a telemetria do próprio dlctl e gera propostas de melhoria: repeated-failure, "
    "throttling, gate-friction (⚠ nunca enfraquecer o gate), prefer-resolver, "
    "skill-featured-unused e permission-gap. Aprovação é sempre manual (Stage B)."
)

profile_name = st.sidebar.text_input(
    "Profile", value="ms_client_constellation", key="retro_profile_name",
    help="Profile de config/profiles.yaml cuja telemetria (ActivityLog/PipelineStep/CommandInvocation) será analisada.",
)
try:
    profile = load_profile(profile_name)
except Exception as exc:
    st.error(f"Não foi possível carregar o profile '{profile_name}': {exc}")
    st.stop()

col_a, col_b = st.columns([1, 3])
with col_a:
    window_days = st.number_input(
        "Janela (dias)", min_value=1, value=90, step=1,
        help="Quantos dias para trás olhar no histórico ao procurar padrões. Ex.: 90 (últimos 3 meses).",
    )
    min_count = st.number_input(
        "Contagem mínima do sinal", min_value=1, value=3, step=1,
        help="Quantas ocorrências do mesmo padrão (ex.: mesma falha, mesmo retry) são necessárias para "
             "virar uma proposta. Ex.: 3 (evita propostas baseadas em 1 evento isolado).",
    )
    if st.button(
        "🔎 Rodar análise", type="primary",
        help="Analisa a telemetria própria do dlctl na janela informada e persiste novas propostas de melhoria. "
             "Equivalente a `dlctl retro analyze`. Nunca aplica nenhuma mudança sozinho.",
    ):
        summary = analyze(profile, window_days=int(window_days), min_count=int(min_count))
        st.session_state["retro_summary"] = summary
        st.success(f"Análise concluída: {summary['proposal_count']} proposta(s) em {summary['event_count']} evento(s).")

if "retro_summary" in st.session_state:
    s = st.session_state["retro_summary"]
    with col_b:
        st.info(f"Janela: {s['window_start']} .. {s['window_end']} | eventos: {s['event_count']} | propostas: {s['proposal_count']}")

st.divider()

proposals = list_retro_proposals(profile)
if not proposals:
    st.info("Nenhuma proposta ainda. Clique em 'Rodar análise' acima (ou use `dlctl retro analyze`).")
    st.stop()

df = pd.DataFrame(proposals)

col1, col2, col3 = st.columns(3)
category_pick = col1.multiselect(
    "Categoria", options=sorted(df["category"].unique()), default=list(sorted(df["category"].unique())),
    help="Filtra pelo tipo de sinal detectado. Ex.: repeated-failure, throttling, gate-friction, "
         "prefer-resolver, skill-featured-unused, permission-gap.",
)
risk_pick = col2.multiselect(
    "Risco", options=sorted(df["risk"].unique()), default=list(sorted(df["risk"].unique())),
    help="Filtra pelo nível de risco estimado da proposta. Ex.: low, medium, high.",
)
status_pick = col3.multiselect(
    "Status", options=sorted(df["status"].unique()), default=list(sorted(df["status"].unique())),
    help="Filtra pelo status de revisão humana. Ex.: pending, approved, rejected.",
)

df_f = df[df["category"].isin(category_pick) & df["risk"].isin(risk_pick) & df["status"].isin(status_pick)]

st.dataframe(
    df_f[["proposal_key", "category", "risk", "count", "status", "gate_change", "first_ts", "last_ts"]]
    .sort_values("count", ascending=False),
    use_container_width=True, height=350,
)

st.divider()
st.subheader("Revisar e aprovar/rejeitar")
if not df_f.empty:
    selected_key = st.selectbox(
        "Proposta", options=df_f["proposal_key"].tolist(),
        help="Chave única da proposta a revisar em detalhe abaixo (título, evidência, afetado).",
    )
    row = df_f[df_f["proposal_key"] == selected_key].iloc[0]

    if row["gate_change"]:
        st.warning(
            "⚠ **GATE-CHANGE**: esta proposta é sobre um gate de segurança que está funcionando "
            "corretamente. NÃO é uma proposta para enfraquecê-lo — releia a regra de segurança "
            "afetada antes de aprovar qualquer mudança de documentação/mensagem."
        )

    st.markdown(f"**{row['title']}**")
    st.write(f"Categoria: `{row['category']}` | Risco: `{row['risk']}` | Contagem: {row['count']} | Status atual: `{row['status']}`")
    st.write(f"Afetado: {row['affected']}")
    st.write(f"Proposta: {row['proposal_text']}")
    with st.expander("Evidência bruta"):
        st.code(row["evidence_json"], language="json")

    col_ap, col_rj = st.columns(2)
    with col_ap:
        if st.button(
            "✅ Aprovar", type="primary",
            help="Marca a proposta selecionada como aprovada (Stage B: só sinaliza concordância humana, "
                 "não aplica nenhuma mudança automaticamente).",
        ):
            approve_proposal(profile, selected_key)
            st.success("Marcada como aprovada.")
            st.rerun()
    with col_rj:
        if st.button(
            "❌ Rejeitar",
            help="Marca a proposta selecionada como rejeitada — ela deixa de aparecer como pendente, mas "
                 "continua no histórico.",
        ):
            reject_proposal(profile, selected_key)
            st.warning("Marcada como rejeitada.")
            st.rerun()

    st.caption(
        "Stage B: manual_required — uma proposta aprovada aqui NÃO aplica nenhuma mudança "
        "sozinha; ela só sinaliza que um humano concorda que vale a pena aplicá-la através do "
        "fluxo normal de edição -> testes -> sincronização."
    )

st.divider()
st.subheader("Relatório markdown")
if st.button(
    "📄 Gerar relatório completo",
    help="Monta o relatório markdown 'Improvement Proposals (retro)' com todas as propostas da última "
         "análise, pronto para baixar logo abaixo.",
):
    summary = st.session_state.get("retro_summary") or analyze(profile, window_days=int(window_days))
    report = render_markdown_report(profile, summary)
    st.session_state["retro_report"] = report

if "retro_report" in st.session_state:
    st.code(st.session_state["retro_report"], language="markdown")
    st.download_button(
        "⬇️ Baixar relatório (.md)", data=st.session_state["retro_report"],
        file_name="improvement_proposals_retro.md", mime="text/markdown",
        help="Baixa o relatório gerado acima como arquivo .md para compartilhar ou anexar em um ticket.",
    )
