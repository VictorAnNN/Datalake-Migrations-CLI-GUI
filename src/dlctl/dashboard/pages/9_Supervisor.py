"""Página de dashboard: Supervisor — diagnóstico geral do projeto.

Varre os artefatos reais em `input/lakehouse-dev` (notebooks) e
`input/Workspaces` (JSONs do Fabric Scanner API), cruza com `mappings/*.csv`
(Bronze/Silver/Gold) e `config/project_targets.yaml` (Dashboards/BI e Views/
processos intermediários) e mostra quanto do projeto já foi migrado — sem
fingir 100% quando não há meta configurada para uma categoria.
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
from dlctl.core import state as state_db
from dlctl.core.project_scan import export_supervisor_report, read_project_targets, scan_project, write_project_targets

st.set_page_config(page_title="Supervisor — Constellation Migration Control", layout="wide", page_icon="🧭")
st.title("🧭 Supervisor — Visão Geral do Projeto")
st.caption(
    "Diagnóstico geral do andamento da migração: quanto de Bronze/Silver/Gold/Dashboards/Views "
    "já existe de verdade (varredura real de `input/lakehouse-dev`) contra o que deveria existir no total "
    "(calculado olhando para tudo em `input/`: mappings/*.csv + linhagem de notebooks + Oracle refs + "
    "relatórios do Power BI; Views/Processos intermediários usa meta configurável abaixo)."
)

profile_name = st.sidebar.text_input(
    "Profile", value="ms_client_constellation", key="supervisor_profile",
    help="Profile de config/profiles.yaml usado para ler mappings/*.csv e o histórico salvo no state local.",
)
try:
    profile = load_profile(profile_name)
except Exception as exc:
    st.error(f"Não foi possível carregar o profile '{profile_name}': {exc}")
    st.stop()

col_run1, col_run2 = st.columns(2)
with col_run1:
    lakehouse_dev_input = st.text_input(
        "Pasta de notebooks (lakehouse-dev)", value="input/lakehouse-dev",
        help="Pasta com os notebooks .ipynb/.py sincronizados do Fabric, usada para contar o que já existe "
             "de Bronze/Silver/Gold/Controle/Qualidade de dados.",
    )
with col_run2:
    workspaces_input = st.text_input(
        "Pasta ou .zip com JSONs do Fabric Scanner API (opcional)", value="input/Workspaces",
        help="Alimenta a contagem real de Dashboards/BI (relatórios do Power BI/Fabric). Deixe em branco para pular.",
    )

only_referenced_workspaces = st.checkbox(
    "Considerar só workspaces referenciados em lakehouse-dev",
    value=False,
    help="Nem todo workspace de input/Workspaces faz parte deste projeto. Marque para descartar, do cálculo de "
         "Dashboards/BI e Gold, os workspaces que não têm nenhuma Dataset Table batendo com uma tabela conhecida "
         "em input/lakehouse-dev (Bronze/Silver/Gold).",
)

if st.button(
    "🔎 Rodar diagnóstico", type="primary",
    help="Varre input/lakehouse-dev e input/Workspaces e recalcula os percentuais. Somente leitura, não altera nada.",
):
    with st.spinner("Varrendo notebooks e workspaces..."):
        st.session_state["supervisor_result"] = scan_project(
            profile, lakehouse_dev_input=lakehouse_dev_input, workspaces_input=workspaces_input or None,
            only_referenced_workspaces=only_referenced_workspaces,
        )

result = st.session_state.get("supervisor_result")


if not result:
    st.info("Clique em **🔎 Rodar diagnóstico** acima para ver os números do projeto.")
else:
    st.caption(f"Última varredura: {result['generated_at']}")

    if result.get("workspaces_referenciados") is not None:
        st.info(
            f"🔎 Filtro ativo: **{len(result['workspaces_referenciados'])} de {result['workspaces_total']}** "
            "workspaces de `input/Workspaces` têm alguma Dataset Table batendo com lakehouse-dev e entraram no cálculo."
        )
        with st.expander("Ver workspaces considerados"):
            st.write(result["workspaces_referenciados"])

    st.markdown("#### 📊 % geral do projeto")
    st.progress(min(result["overall_percent"], 100) / 100)
    st.metric("Percentual geral (categorias com meta configurada)", f"{result['overall_percent']}%")
    if result["excluded_from_overall"]:
        st.warning(
            f"⚠️ Fora do % geral por falta de meta configurada: **{', '.join(result['excluded_from_overall'])}**. "
            "Configure as metas na seção 'Metas' abaixo para incluí-las."
        )

    st.markdown("---")
    st.markdown("#### 📋 Detalhe por categoria")
    cols = st.columns(len(result["categories"]))
    for col, cat in zip(cols, result["categories"]):
        with col:
            pct_label = f"{cat['percentual']}%" if cat["percentual"] is not None else "sem meta"
            esperado_label = cat["esperado"] if cat["esperado"] else "?"
            st.metric(cat["categoria"], f"{cat['existente']} / {esperado_label}", pct_label)

    summary_df = pd.DataFrame(result["categories"]).rename(columns={
        "categoria": "Categoria", "existente": "Existente", "esperado": "Esperado",
        "percentual": "%", "fonte_meta": "Fonte da meta",
    })
    st.dataframe(summary_df, use_container_width=True, hide_index=True)

    with st.expander("🗂️ Notebooks encontrados (detalhe por categoria)"):
        notebooks_df = pd.DataFrame(result["notebook_rows"])
        if notebooks_df.empty:
            st.info("Nenhum notebook encontrado em `input/lakehouse-dev`.")
        else:
            cat_pick = st.multiselect(
                "Filtrar por categoria", sorted(notebooks_df["categoria"].unique()),
                help="Filtra a lista de notebooks encontrados pela categoria detectada (Bronze/Silver/Gold/etc.).",
            )
            shown = notebooks_df[notebooks_df["categoria"].isin(cat_pick)] if cat_pick else notebooks_df
            st.dataframe(shown, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("#### 💾 Salvar esta visão")
    st.caption(
        "Exporta o diagnóstico atual para `manifests/dashboard/` (Excel com abas Resumo/Notebooks/Dashboards "
        "+ CSV do resumo) e guarda um registro no histórico abaixo — útil para acompanhar a evolução do "
        "projeto ao longo do tempo."
    )
    if st.button(
        "💾 Salvar esta visão", type="primary",
        help="Grava um snapshot deste diagnóstico (percentuais + notebooks + dashboards) em manifests/dashboard/ "
             "e no histórico do Supervisor.",
    ):
        from datetime import datetime
        batch_id = f"supervisor_{datetime.now():%Y%m%d_%H%M%S}"
        paths = export_supervisor_report(result, profile.paths.manifests_root / "dashboard", batch_id)
        state_db.save_supervisor_snapshot(
            profile, batch_id, result["overall_percent"], result["categories"],
            excel_path=paths["excel_path"], csv_path=paths["csv_path"],
        )
        st.success(f"✅ Visão salva (batch `{batch_id}`).")
        st.info(f"Excel: `{paths['excel_path']}`")
        st.info(f"CSV: `{paths['csv_path']}`")
        st.rerun()

st.markdown("---")
st.markdown("#### 🎯 Meta (Views/Processos intermediários)")
st.caption(
    "Bronze/Silver/Gold e Dashboards/BI são sempre calculados automaticamente a partir de `input/` "
    "(mappings + linhagem de notebooks + Oracle refs + cruzamento dashboard↔tabela Gold). "
    "Views/processos intermediários não têm uma fonte de verdade própria no projeto — defina a meta manualmente aqui."
)
current_targets = read_project_targets()
with st.form("form_supervisor_targets"):
    intermediate_target = st.number_input(
        "Meta de Views/Processos intermediários", min_value=0, value=current_targets["intermediate"] or 0, step=1,
        help="Total de notebooks de controle/config/qualidade de dados que deveriam existir. "
             "Use 0 para deixar sem meta (categoria fica de fora do % geral).",
    )
    submitted_targets = st.form_submit_button(
        "Salvar meta", type="primary",
        help="Grava a meta em config/project_targets.yaml. Rode o diagnóstico de novo para ver o efeito.",
    )
if submitted_targets:
    write_project_targets(intermediate_target or None)
    st.success("Meta salva em config/project_targets.yaml. Rode o diagnóstico novamente para atualizar os percentuais.")
    st.rerun()


st.markdown("---")
st.markdown("#### 🕒 Histórico de visões salvas")
snapshots = state_db.list_supervisor_snapshots(profile)
if not snapshots:
    st.info("Nenhuma visão salva ainda. Use o botão '💾 Salvar esta visão' acima.")
else:
    history_df = pd.DataFrame([{
        "Batch": s.batch_id, "Criado em": s.created_at, "% geral": f"{s.overall_percent}%",
        "Excel": s.excel_path, "CSV": s.csv_path,
    } for s in snapshots])
    st.dataframe(history_df, use_container_width=True, hide_index=True)
