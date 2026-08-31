"""Página de Configuração do dashboard: editar/adicionar conexões, credenciais
e domínios diretamente pelo front-end, e testar as conexões configuradas.
"""
from __future__ import annotations

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[3]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import streamlit as st

from dlctl.config import load_profile
from dlctl.core.env_editor import (
    delete_domain,
    list_domains,
    read_env_for_form,
    secret_status,
    update_env,
    update_profile_flags,
    upsert_domain,
)

st.set_page_config(page_title="Configuração — Constellation Migration Control", layout="wide", page_icon="⚙️")
st.title("⚙️ Configuração de Conexões e Ambiente")
st.caption(
    "Edite aqui as credenciais Fabric/Oracle e os parâmetros de ambiente. "
    "Segredos já salvos nunca são reexibidos — deixe o campo em branco para mantê-los inalterados."
)

profile_name = st.text_input("Profile", value="ms_client_constellation", key="cfg_profile_name")

env_values = read_env_for_form()
secrets_ok = secret_status()

tab_fabric, tab_oracle, tab_flags, tab_domains, tab_test = st.tabs(
    ["Microsoft Fabric", "Oracle Fusion", "Ambiente & Escrita", "Domínios", "Testar Conexões"]
)

# ---------------- Fabric ----------------
with tab_fabric:
    st.subheader("Microsoft Entra ID / Fabric")
    with st.form("form_fabric"):
        tenant_id = st.text_input("FABRIC_TENANT_ID", value=env_values.get("FABRIC_TENANT_ID", ""))
        client_id = st.text_input("FABRIC_CLIENT_ID", value=env_values.get("FABRIC_CLIENT_ID", ""))
        current_auth_mode = env_values.get("FABRIC_AUTH_MODE") or "azure_cli"
        auth_options = ["azure_cli", "device_code", "client_credentials"]
        auth_mode = st.selectbox(
            "FABRIC_AUTH_MODE", options=auth_options,
            index=auth_options.index(current_auth_mode) if current_auth_mode in auth_options else 0,
            help="azure_cli (recomendado): reaproveita a sessão do `az login`, sem precisar de App Registration.",
        )
        client_secret_placeholder = "já configurado — deixe em branco para manter" if secrets_ok.get("FABRIC_CLIENT_SECRET") else "não configurado"
        client_secret = st.text_input(f"FABRIC_CLIENT_SECRET ({client_secret_placeholder})", value="", type="password")
        workspace_name = st.text_input("FABRIC_WORKSPACE_NAME", value=env_values.get("FABRIC_WORKSPACE_NAME", ""))
        workspace_id = st.text_input("FABRIC_WORKSPACE_ID", value=env_values.get("FABRIC_WORKSPACE_ID", ""))
        submitted_fabric = st.form_submit_button("Salvar configuração Fabric", type="primary")
    if submitted_fabric:
        updates = {
            "FABRIC_TENANT_ID": tenant_id, "FABRIC_CLIENT_ID": client_id, "FABRIC_AUTH_MODE": auth_mode,
            "FABRIC_WORKSPACE_NAME": workspace_name, "FABRIC_WORKSPACE_ID": workspace_id,
        }
        if client_secret:
            updates["FABRIC_CLIENT_SECRET"] = client_secret
        update_env(updates)
        st.success("Configuração Fabric salva em .env")
        st.rerun()

# ---------------- Oracle ----------------
with tab_oracle:
    st.subheader("Oracle Fusion (banco + BI Publisher)")
    with st.form("form_oracle"):
        st.markdown("**Banco de dados**")
        dsn = st.text_input("ORACLE_DB_DSN", value=env_values.get("ORACLE_DB_DSN", ""))
        db_user = st.text_input("ORACLE_DB_USER", value=env_values.get("ORACLE_DB_USER", ""))
        db_pass_placeholder = "já configurado — deixe em branco para manter" if secrets_ok.get("ORACLE_DB_PASSWORD") else "não configurado"
        db_password = st.text_input(f"ORACLE_DB_PASSWORD ({db_pass_placeholder})", value="", type="password")

        st.markdown("**BI Publisher (SOAP)**")
        bip_url = st.text_input("ORACLE_BIP_BASE_URL", value=env_values.get("ORACLE_BIP_BASE_URL", ""))
        bip_user = st.text_input("ORACLE_BIP_USER", value=env_values.get("ORACLE_BIP_USER", ""))
        bip_pass_placeholder = "já configurado — deixe em branco para manter" if secrets_ok.get("ORACLE_BIP_PASSWORD") else "não configurado"
        bip_password = st.text_input(f"ORACLE_BIP_PASSWORD ({bip_pass_placeholder})", value="", type="password")
        submitted_oracle = st.form_submit_button("Salvar configuração Oracle", type="primary")
    if submitted_oracle:
        updates = {
            "ORACLE_DB_DSN": dsn, "ORACLE_DB_USER": db_user,
            "ORACLE_BIP_BASE_URL": bip_url, "ORACLE_BIP_USER": bip_user,
        }
        if db_password:
            updates["ORACLE_DB_PASSWORD"] = db_password
        if bip_password:
            updates["ORACLE_BIP_PASSWORD"] = bip_password
        update_env(updates)
        st.success("Configuração Oracle salva em .env")
        st.rerun()

# ---------------- Ambiente & gates ----------------
with tab_flags:
    st.subheader("Ambiente e permissões de escrita (gates)")
    try:
        current_profile = load_profile(profile_name)
    except Exception as exc:
        st.error(f"Erro ao carregar profile: {exc}")
        current_profile = None

    with st.form("form_flags"):
        environment = st.selectbox("Ambiente", options=["DEV", "HML", "PRD"],
                                    index=["DEV", "HML", "PRD"].index(current_profile.environment) if current_profile else 0)
        allow_write = st.checkbox("microsoft.allow_write (permite escritas gated)",
                                   value=current_profile.microsoft.allow_write if current_profile else False)
        allow_production = st.checkbox("microsoft.allow_production (obrigatório em PRD)",
                                        value=current_profile.microsoft.allow_production if current_profile else False)
        st.info(
            "Isto só habilita a *possibilidade* de escrita no profile. Cada comando "
            "ainda exige `--confirm-write`/`--confirm-execute` (ou o checkbox equivalente "
            "na página Ações) para realmente mutar algo."
        )
        submitted_flags = st.form_submit_button("Salvar ambiente/permissões", type="primary")
    if submitted_flags:
        update_profile_flags(
            profile_name, allow_write=allow_write, allow_production=allow_production,
            workspace_name=env_values.get("FABRIC_WORKSPACE_NAME", ""),
            workspace_id=env_values.get("FABRIC_WORKSPACE_ID", ""),
            environment=environment,
        )
        st.success("Ambiente/permissões atualizados em config/profiles.yaml")
        st.rerun()

# ---------------- Domínios ----------------
with tab_domains:
    st.subheader("Domínios de negócio (router constellation-order-tracking-etl)")
    domains = list_domains()
    if domains:
        st.dataframe(
            [{"domínio": k, **v} for k, v in domains.items()],
            use_container_width=True,
        )
    else:
        st.info("Nenhum domínio configurado ainda.")

    with st.form("form_domain"):
        st.markdown("**Adicionar / editar domínio**")
        d_key = st.text_input("Chave do domínio (ex.: ORDER_TRACKING)")
        d_desc = st.text_input("Descrição")
        d_folder = st.text_input("folder_path (ex.: pipelines/SUPRIMENTOS)")
        d_silver = st.text_input("silver_lakehouse")
        d_gold = st.text_input("gold_lakehouse")
        submitted_domain = st.form_submit_button("Salvar domínio", type="primary")
    if submitted_domain and d_key:
        upsert_domain(d_key, d_desc, d_folder, d_silver, d_gold)
        st.success(f"Domínio '{d_key}' salvo.")
        st.rerun()

    if domains:
        del_key = st.selectbox("Remover domínio", options=["(nenhum)"] + list(domains.keys()))
        if del_key != "(nenhum)" and st.button("Remover domínio selecionado", type="secondary"):
            delete_domain(del_key)
            st.success(f"Domínio '{del_key}' removido.")
            st.rerun()

# ---------------- Testar conexões ----------------
with tab_test:
    st.subheader("Testar conexões configuradas")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔎 Testar Microsoft Fabric", type="primary"):
            try:
                from dlctl.connectors.fabric_api import FabricApiError, build_client_from_profile
                p = load_profile(profile_name)
                client = build_client_from_profile(p)
                workspaces = client.list_workspaces()
                st.success(f"OK: autenticado, {len(workspaces)} workspace(s) visível(eis).")
                st.json([w.get("displayName") for w in workspaces])
            except Exception as exc:
                st.error(f"Falha: {exc}")
    with col2:
        if st.button("🔎 Testar Oracle DB", type="primary"):
            try:
                from dlctl.connectors.oracle_connector import OracleDbConnector
                p = load_profile(profile_name)
                conn = OracleDbConnector(p)
                result = conn.test_connection()
                st.success(f"OK: {result}")
            except Exception as exc:
                st.error(f"Falha (ou manual_required): {exc}")
