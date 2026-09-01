"""Página de dashboard: Supervisor — diagnóstico geral do projeto.

Varre os artefatos reais em `input/lakehouse-dev` (notebooks) e
`input/Workspaces` (JSONs do Fabric Scanner API), cruza com `mappings/*.csv`
(Bronze/Silver/Gold) e `config/project_targets.yaml` (Dashboards/BI e Views/
processos intermediários) e mostra quanto do projeto já foi migrado — sem
fingir 100% quando não há meta configurada para uma categoria.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[3]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from dlctl.config import load_profile
from dlctl.core import state as state_db
from dlctl.core.project_scan import (
    export_supervisor_report,
    read_project_targets,
    read_workspace_domain_prefixes,
    scan_project,
    write_project_targets,
    write_workspace_domain_prefixes,
)

# Paleta "enterprise": tons sóbrios de azul-marinho/verde-petróleo/âmbar em vez de
# cores vivas de dashboard consumer — usada em todos os gráficos desta página.
COLOR_PRIMARY = "#13315C"     # navy — existente / série principal
COLOR_SECONDARY = "#5E7CA3"   # azul-aço — esperado / neutro
COLOR_SUCCESS = "#1F7A5C"     # verde-petróleo — concluído / promovido
COLOR_WARNING = "#C98B32"     # âmbar — pendente / atenção
COLOR_DANGER = "#A6434A"      # vermelho-tijolo — faltante / gap
COLOR_NEUTRAL = "#8492A6"     # cinza-ardósia — auxiliar
CATEGORY_COLOR_SEQUENCE = [COLOR_PRIMARY, COLOR_SECONDARY, COLOR_SUCCESS, COLOR_WARNING, COLOR_NEUTRAL, COLOR_DANGER, "#3E5C76"]
_MONTH_ABBREV_PT = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]


def _week_of_month_label(dt) -> str:
    week = (dt.day - 1) // 7 + 1
    return f"Sem {week}/{_MONTH_ABBREV_PT[dt.month - 1]}"


st.set_page_config(page_title="Supervisor — Constellation Migration Control", layout="wide", page_icon="🧭")
st.title("🧭 Supervisor — Visão Geral do Projeto")
st.caption(
    "Diagnóstico geral do andamento da migração: quanto de Bronze/Silver/Gold/Dashboards/Views "
    "já existe de verdade (varredura real de `input/lakehouse-dev` + `input/lakehouse-hml`, se informada) contra o "
    "que deveria existir no total (calculado olhando para tudo em `input/`: mappings/*.csv + linhagem de notebooks + "
    "Oracle refs + relatórios do Power BI; Views/Processos intermediários usa meta configurável abaixo)."
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

col_run1, col_run2, col_run3 = st.columns(3)
with col_run1:
    lakehouse_dev_input = st.text_input(
        "Pasta (lakehouse-dev)", value="input/lakehouse-dev",
        help="Pasta com os notebooks .ipynb/.py sincronizados do Fabric, usada para contar o que já existe "
             "de Bronze/Silver/Gold/Controle/Qualidade de dados.",
    )
with col_run2:
    lakehouse_hml_input = st.text_input(
        "Pasta (lakehouse-hml, opcional)", value="input/lakehouse-hml",
        help="Pasta com os notebooks sincronizados do workspace de Homologação (botão 'Puxar/atualizar notebooks do "
             "workspace HML' na página Ações). Quando existir, o 'existente' passa a ser a união DEV+HML e a página "
             "mostra o comparativo de quanto já foi promovido para HML. Deixe em branco para ignorar.",
    )
with col_run3:
    workspaces_input = st.text_input(
        "Pasta ou .zip com JSONs do Fabric (opcional)", value="input/Workspaces",
        help="Alimenta a contagem real de Dashboards/BI (relatórios do Power BI/Fabric). Deixe em branco para pular.",
    )

workspace_filter_choice = st.radio(
    "Quais workspaces de input/Workspaces contam para Dashboards/BI e Gold?",
    options=["Todos (sem filtro)", "Só por prefixo de domínio (recomendado)", "Só por tabela referenciada em lakehouse-dev"],
    index=1,
    horizontal=True,
    help="Nem todo workspace do tenant faz parte deste projeto. 'Por prefixo de domínio' é o mais preciso "
         "(compara pelo nome do workspace, ex.: OPER-, FINAN-, MASTER-DATA, ORDER-TRACKING); 'Por tabela "
         "referenciada' é um fallback baseado em bater nome de tabela, útil se os prefixos não são conhecidos.",
)
filter_by_domain_prefix = workspace_filter_choice == "Só por prefixo de domínio (recomendado)"
only_referenced_workspaces = workspace_filter_choice == "Só por tabela referenciada em lakehouse-dev"

with st.expander("⚙️ Prefixos de domínio usados no filtro por prefixo"):
    current_prefixes = read_workspace_domain_prefixes()
    st.caption(
        "Prefixos de nome de workspace que identificam os domínios de negócio já migrados em "
        "`input/lakehouse-dev` (ex.: OPER- cobre OPER-QSMS-*/OPER-SUPPLY-*, FINAN- cobre Financeiro/Controladoria)."
    )
    prefixes_text = st.text_input(
        "Prefixos (separados por vírgula)", value=", ".join(current_prefixes),
        help="Ex.: OPER-, FINAN-, MASTER-DATA, ORDER-TRACKING",
    )
    if st.button("Salvar prefixos", key="btn_save_prefixes"):
        new_prefixes = [p.strip() for p in prefixes_text.split(",") if p.strip()]
        write_workspace_domain_prefixes(new_prefixes)
        st.success("Prefixos salvos em config/project_targets.yaml. Rode o diagnóstico novamente para aplicar.")
        st.rerun()

if st.button(
    "🔎 Rodar diagnóstico", type="primary",
    help="Varre input/lakehouse-dev e input/Workspaces e recalcula os percentuais. Somente leitura, não altera nada.",
):
    with st.spinner("Varrendo notebooks e workspaces..."):
        st.session_state["supervisor_result"] = scan_project(
            profile, lakehouse_dev_input=lakehouse_dev_input, workspaces_input=workspaces_input or None,
            only_referenced_workspaces=only_referenced_workspaces, filter_by_domain_prefix=filter_by_domain_prefix,
            lakehouse_hml_input=lakehouse_hml_input or None,
        )

result = st.session_state.get("supervisor_result")


if not result:
    st.info("Clique em **🔎 Rodar diagnóstico** acima para ver os números do projeto.")
else:
    st.caption(f"Última varredura: {result['generated_at']}")

    if result.get("workspaces_referenciados") is not None:
        modo_label = "prefixo de domínio" if result["workspace_filter_mode"] == "domain_prefix" else "tabela referenciada em lakehouse-dev"
        st.info(
            f"🔎 Filtro ativo ({modo_label}): **{len(result['workspaces_referenciados'])} de {result['workspaces_total']}** "
            "workspaces de `input/Workspaces` entraram no cálculo de Dashboards/BI e Gold."
        )
        with st.expander("Ver workspaces considerados"):
            st.write(result["workspaces_referenciados"])

    st.markdown("#### 📊 % geral do projeto")
    col_gauge, col_bar = st.columns([1, 2])
    with col_gauge:
        gauge = go.Figure(go.Indicator(
            mode="gauge+number",
            value=result["overall_percent"],
            number={"suffix": "%"},
            gauge={
                "axis": {"range": [0, 100]},
                "bar": {"color": COLOR_PRIMARY},
                "steps": [
                    {"range": [0, 40], "color": "#E7D3D4"},
                    {"range": [40, 75], "color": "#EFE1C8"},
                    {"range": [75, 100], "color": "#D6E1D9"},
                ],
            },
        ))
        gauge.update_layout(height=220, margin=dict(l=20, r=20, t=20, b=10))
        st.plotly_chart(gauge, use_container_width=True)
    with col_bar:
        cat_df = pd.DataFrame(result["categories"])
        cat_df["esperado_num"] = cat_df["esperado"].fillna(0)
        bar_fig = go.Figure(data=[
            go.Bar(name="Existente", x=cat_df["categoria"], y=cat_df["existente"], marker_color=COLOR_PRIMARY),
            go.Bar(name="Esperado", x=cat_df["categoria"], y=cat_df["esperado_num"], marker_color=COLOR_SECONDARY),
        ])
        bar_fig.update_layout(barmode="group", height=260, margin=dict(l=20, r=20, t=20, b=10),
                               legend=dict(orientation="h", yanchor="bottom", y=1.02))
        st.plotly_chart(bar_fig, use_container_width=True)
    st.progress(min(result["overall_percent"], 100) / 100)
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

    col_pct, col_dist = st.columns(2)
    with col_pct:
        pct_df = pd.DataFrame([c for c in result["categories"] if c["percentual"] is not None])
        if pct_df.empty:
            st.info("Nenhuma categoria com meta configurada ainda para o gráfico de % por categoria.")
        else:
            pct_fig = px.bar(
                pct_df, x="categoria", y="percentual", text="percentual",
                labels={"categoria": "Categoria", "percentual": "% concluído"},
                title="% concluído por categoria", range_y=[0, 100],
            )
            pct_fig.update_traces(marker_color=COLOR_SUCCESS, texttemplate="%{text}%", textposition="outside")
            pct_fig.update_layout(height=280, margin=dict(l=20, r=20, t=40, b=10))
            st.plotly_chart(pct_fig, use_container_width=True)
    with col_dist:
        dist_counts = result["notebook_category_counts"]
        if not dist_counts:
            st.info("Nenhum notebook encontrado em `input/lakehouse-dev` para o gráfico de distribuição.")
        else:
            dist_fig = px.pie(
                names=list(dist_counts.keys()), values=list(dist_counts.values()),
                title="Distribuição dos notebooks existentes por categoria", hole=0.45,
                color_discrete_sequence=CATEGORY_COLOR_SEQUENCE,
            )
            dist_fig.update_layout(height=280, margin=dict(l=20, r=20, t=40, b=10))
            st.plotly_chart(dist_fig, use_container_width=True)

    if result["hml_enabled"]:
        st.markdown("---")
        st.markdown("#### 🧪 DEV vs HML — maturidade do projeto")
        st.caption(
            "Compara o que já existe em `input/lakehouse-dev` com o que já foi promovido para "
            "`input/lakehouse-hml` (mesmo notebook, casado pela pasta). O % geral do projeto acima já "
            "considera a união DEV+HML como 'existente' — esta seção mostra o detalhe dessa maturidade."
        )
        et = result["env_totals"]
        esperado_total = sum(c["esperado"] for c in result["categories"] if c["esperado"])
        faltam = max(esperado_total - et["existente_geral"], 0) if esperado_total else None
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Notebooks em DEV", et["existente_dev"])
        m2.metric("Promovidos p/ HML", et["existente_hml"])
        m3.metric("Meta do projeto (esperado)", esperado_total if esperado_total else "sem meta")
        m4.metric("Faltam p/ meta", faltam if faltam is not None else "-")
        st.caption(
            f"Do que já existe ({et['existente_geral']} notebook(s)), {et['promovidos_hml']} já foram promovidos "
            f"para HML e {et['existente_geral'] - et['promovidos_hml']} ainda estão só em DEV "
            f"({et['pct_hml']}% já promovido)." if et["pct_hml"] is not None else ""
        )

        env_df = pd.DataFrame(result["env_categories"])
        col_env_bar, col_env_pie = st.columns(2)
        with col_env_bar:
            env_bar = go.Figure(data=[
                go.Bar(name="Só em DEV", x=env_df["categoria"], y=env_df["somente_dev"], marker_color=COLOR_WARNING),
                go.Bar(name="Promovido p/ HML", x=env_df["categoria"], y=env_df["promovidos_hml"], marker_color=COLOR_SUCCESS),
            ])
            env_bar.update_layout(
                barmode="stack", height=340, margin=dict(l=20, r=20, t=50, b=60),
                title="Notebooks por categoria: só DEV vs. promovido para HML",
                legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5),
            )
            st.plotly_chart(env_bar, use_container_width=True)
        with col_env_pie:
            env_pie = px.pie(
                names=["Ainda não promovido", "Promovido p/ HML"],
                values=[et["existente_geral"] - et["promovidos_hml"], et["promovidos_hml"]],
                title="% do projeto já promovido para HML", hole=0.45,
                color_discrete_sequence=[COLOR_WARNING, COLOR_SUCCESS],
            )
            env_pie.update_layout(height=300, margin=dict(l=20, r=20, t=40, b=10))
            st.plotly_chart(env_pie, use_container_width=True)

        with st.expander("📋 Detalhe DEV vs HML por categoria"):
            st.dataframe(
                env_df.rename(columns={
                    "categoria": "Categoria", "existente_dev": "Existente DEV", "existente_hml": "Existente HML",
                    "existente_geral": "Total (união)", "promovidos_hml": "Promovido p/ HML",
                    "somente_dev": "Só em DEV", "pct_hml": "% promovido",
                }),
                use_container_width=True, hide_index=True,
            )
    elif lakehouse_hml_input:
        st.caption(
            f"ℹ️ Pasta HML `{lakehouse_hml_input}` não encontrada ainda — use o botão "
            "'Puxar/atualizar notebooks do workspace HML' na página Ações para sincronizar."
        )

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

    ordered = sorted(snapshots, key=lambda s: s.created_at)
    if len(ordered) >= 2:
        overall_df = pd.DataFrame({
            "data": pd.to_datetime([s.created_at for s in ordered]),
            "% geral": [s.overall_percent for s in ordered],
        })
        overall_df["período"] = overall_df["data"].apply(_week_of_month_label)
        weekly_df = (
            overall_df.groupby("período", sort=False)
            .agg(**{"% geral": ("% geral", "last"), "data": ("data", "max")})
            .reset_index()
            .sort_values("data")
        )
        if weekly_df["período"].nunique() >= 2:
            trend_df, period_order = weekly_df, list(weekly_df["período"])
        else:
            overall_df["período"] = overall_df["data"].dt.strftime("%d/%m")
            trend_df = (
                overall_df.groupby("período", sort=False)
                .agg(**{"% geral": ("% geral", "last"), "data": ("data", "max")})
                .reset_index()
                .sort_values("data")
            )
            period_order = list(trend_df["período"])

        overall_trend_fig = px.line(
            trend_df, x="período", y="% geral", markers=True,
            category_orders={"período": period_order},
            labels={"período": "Período"}, title="Evolução do % geral do projeto",
        )
        overall_trend_fig.update_traces(line_color=COLOR_PRIMARY, marker_color=COLOR_PRIMARY)
        overall_trend_fig.update_layout(height=280, margin=dict(l=20, r=20, t=40, b=10), yaxis_range=[0, 100])
        st.plotly_chart(overall_trend_fig, use_container_width=True)

        category_rows = []
        for s in ordered:
            try:
                cats = json.loads(s.summary_json)
            except (json.JSONDecodeError, TypeError):
                continue
            for c in cats:
                if c.get("percentual") is not None:
                    category_rows.append({"Data": s.created_at, "Categoria": c["categoria"], "%": c["percentual"]})
        if category_rows:
            cat_trend_fig = px.line(
                pd.DataFrame(category_rows), x="Data", y="%", color="Categoria", markers=True,
                title="Evolução do % por categoria", color_discrete_sequence=CATEGORY_COLOR_SEQUENCE,
            )
            cat_trend_fig.update_layout(height=320, margin=dict(l=20, r=20, t=40, b=10), yaxis_range=[0, 100])
            st.plotly_chart(cat_trend_fig, use_container_width=True)
    else:
        st.caption("Salve pelo menos 2 visões para ver os gráficos de evolução ao longo do tempo.")

