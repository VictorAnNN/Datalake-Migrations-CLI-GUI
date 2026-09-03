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

O botão gera DOIS artefatos de uma vez: o original (acima) e um segundo,
"Escopo Estendido" (abaixo), que roda o MESMO processo mas também vasculha
`.tab`/`.vw`/`.dsx` (além de `.sql`/`.prc`) e as pastas '2. Camada Bronze'/
'6. Camada Gold' — seguido de um confronto lado a lado apontando as
diferenças de contagem e onde cada tabela extra foi encontrada.
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
    help="Reprocessa o Excel + scripts SQL de input/sharedpoint do zero e gera DOIS artefatos novos: o "
         "original (FROM/JOIN em .sql/.prc) e o estendido (também .tab/.vw/.dsx). Sem clicar aqui, a "
         "página carrega sempre os últimos artefatos já gerados (não reprocessa a cada acesso).",
):
    with st.spinner("Lendo Excel + vasculhando scripts em input/sharedpoint (artefato original)..."):
        scope = compute_global_scope(sharedpoint_input)
    with st.spinner("Vasculhando .sql/.prc/.tab/.vw/.dsx em input/sharedpoint (artefato estendido)..."):
        scope_extended = compute_global_scope(sharedpoint_input, extended=True)
    if not scope["excel_found"]:
        st.error(f"Excel não encontrado em `{scope['excel_path']}`.")
    else:
        batch_id = f"escopo_{datetime.now():%Y%m%d_%H%M%S}"
        paths = export_global_scope_report(scope, artifacts_dir, batch_id)
        paths_ext = export_global_scope_report(scope_extended, artifacts_dir, batch_id)
        st.session_state["scope_result"] = {
            **scope, "batch_id": batch_id,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "excel_path": paths["excel_path"],
        }
        st.session_state["scope_result_extended"] = {
            **scope_extended, "batch_id": batch_id,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "excel_path": paths_ext["excel_path"],
        }
        st.success(f"✅ Artefatos gerados: `{paths['excel_path']}` + `{paths_ext['excel_path']}`")

if "scope_result" not in st.session_state:
    latest = load_latest_scope_snapshot(artifacts_dir)
    if latest:
        st.session_state["scope_result"] = latest

if "scope_result_extended" not in st.session_state:
    latest_ext = load_latest_scope_snapshot(artifacts_dir, extended=True)
    if latest_ext:
        st.session_state["scope_result_extended"] = latest_ext

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

# ---------------------------------------------------------------------------
# Segundo artefato: escopo ESTENDIDO (também vasculha .prc/.tab/.vw/.dsx)
# ---------------------------------------------------------------------------
st.markdown("---")
st.markdown("### 🧬 Escopo Estendido (também vasculha `.prc`/`.tab`/`.vw`/`.dsx`)")
st.caption(
    "Mesmo processo do artefato acima, mas a busca por tabelas não mapeadas no Excel também abre "
    "arquivos `.tab`/`.vw` (DDL de tabela/view Oracle) e `.dsx` (jobs DataStage exportados), além das "
    "pastas '2. Camada Bronze' e '6. Camada Gold'."
)

if st.button(
    "🧬 Rodar diagnóstico estendido", key="run_extended_scope",
    help="Reprocessa só o artefato estendido (vasculha .sql/.prc/.tab/.vw/.dsx) sem recalcular o "
         "artefato original acima. Use para atualizar o confronto sem esperar o diagnóstico completo.",
):
    with st.spinner("Vasculhando .sql/.prc/.tab/.vw/.dsx em input/sharedpoint (artefato estendido)..."):
        scope_extended = compute_global_scope(sharedpoint_input, extended=True)
    if not scope_extended["excel_found"]:
        st.error(f"Excel não encontrado em `{scope_extended['excel_path']}`.")
    else:
        batch_id_ext = f"escopo_{datetime.now():%Y%m%d_%H%M%S}"
        paths_ext = export_global_scope_report(scope_extended, artifacts_dir, batch_id_ext)
        st.session_state["scope_result_extended"] = {
            **scope_extended, "batch_id": batch_id_ext,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "excel_path": paths_ext["excel_path"],
        }
        st.success(f"✅ Artefato estendido gerado: `{paths_ext['excel_path']}`")

result_ext = st.session_state.get("scope_result_extended")

if not result_ext:
    st.info(
        "Nenhum artefato estendido encontrado ainda. Clique em **🔎 Rodar diagnóstico** acima para gerar "
        "os dois artefatos (original + estendido) de uma vez."
    )
else:
    st.caption(f"Última geração: {result_ext['generated_at']} — artefato: `{result_ext['excel_path']}`")

    camadas_ext_ordenadas = _ordenar_camadas(result_ext["camadas"])
    dashboard_target_ext = result_ext.get("dashboard_target")
    cols_ext = st.columns(len(camadas_ext_ordenadas) + 1 + (1 if dashboard_target_ext else 0))
    with cols_ext[0]:
        st.metric("Total de tabelas", result_ext["total_tabelas"])
    for col, c in zip(cols_ext[1:], camadas_ext_ordenadas):
        with col:
            extra = f"+{c['descobertas_sql']} via SQL/DDL/DSX" if c["descobertas_sql"] else None
            st.metric(_camada_label(c["camada"]), c["total"], extra, delta_color="off")
    if dashboard_target_ext:
        with cols_ext[-1]:
            st.metric("Total de dashboards", dashboard_target_ext["total"], help=dashboard_target_ext["fonte_texto"])

    if result_ext["descobertas_sql"]:
        with st.expander(f"🔍 {len(result_ext['descobertas_sql'])} tabela(s) descoberta(s) no modo estendido (não estavam no Excel)"):
            descobertas_ext_df = pd.DataFrame(result_ext["descobertas_sql"])
            descobertas_ext_df["camada"] = descobertas_ext_df["camada"].map(_camada_label)
            st.dataframe(
                descobertas_ext_df.rename(columns={
                    "tabela": "Tabela", "camada": "Camada (por prefixo)", "dominio": "Domínio",
                    "origem": "Origem", "detalhe": "Encontrada em",
                })[["Tabela", "Camada (por prefixo)", "Domínio", "Origem", "Encontrada em"]],
                use_container_width=True, hide_index=True,
            )

    # -----------------------------------------------------------------
    # Confronto: original vs. estendido
    # -----------------------------------------------------------------
    st.markdown("---")
    st.markdown("### ⚖️ Confronto: Artefato Original vs. Estendido")

    camadas_by_nome_orig = {c["camada"]: c for c in result["camadas"]}
    camadas_by_nome_ext = {c["camada"]: c for c in result_ext["camadas"]}
    todas_camadas = sorted(set(camadas_by_nome_orig) | set(camadas_by_nome_ext), key=lambda n: CAMADA_ORDER.get(n.strip().lower(), 99))

    confronto_rows = []
    for nome in todas_camadas:
        total_orig = camadas_by_nome_orig.get(nome, {}).get("total", 0)
        total_ext = camadas_by_nome_ext.get(nome, {}).get("total", 0)
        confronto_rows.append({
            "Camada": _camada_label(nome), "Total (Original)": total_orig,
            "Total (Estendido)": total_ext, "Diferença": total_ext - total_orig,
        })
    confronto_rows.append({
        "Camada": "TOTAL GERAL", "Total (Original)": result["total_tabelas"],
        "Total (Estendido)": result_ext["total_tabelas"],
        "Diferença": result_ext["total_tabelas"] - result["total_tabelas"],
    })
    confronto_df = pd.DataFrame(confronto_rows)
    confronto_df.insert(0, "", confronto_df["Diferença"].apply(lambda d: "🟡" if d != 0 else "🟢"))

    st.dataframe(confronto_df, use_container_width=True, hide_index=True)

    # Tabelas que só apareceram graças à busca estendida (.tab/.vw/.dsx ou
    # pastas extras) — não estavam nem no Excel, nem no artefato original.
    tabelas_originais = {r["tabela"] for r in result["rows"]}
    somente_no_estendido = [d for d in result_ext["descobertas_sql"] if d["tabela"] not in tabelas_originais]

    if not somente_no_estendido:
        st.success("Nenhuma tabela nova encontrada só pela busca estendida — os dois artefatos concordam.")
    else:
        st.warning(
            f"🆕 {len(somente_no_estendido)} tabela(s) só foram encontradas graças à busca estendida "
            "(.tab/.vw/.dsx ou pastas '2. Camada Bronze'/'6. Camada Gold') — sinalizado abaixo onde cada "
            "uma foi encontrada."
        )
        somente_df = pd.DataFrame(somente_no_estendido)
        somente_df["camada"] = somente_df["camada"].map(_camada_label)
        st.dataframe(
            somente_df.rename(columns={
                "tabela": "Tabela", "camada": "Camada (por prefixo)", "dominio": "Domínio",
                "origem": "Origem (tipo de arquivo)", "detalhe": "Onde foi encontrada",
            })[["Tabela", "Camada (por prefixo)", "Domínio", "Origem (tipo de arquivo)", "Onde foi encontrada"]],
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


