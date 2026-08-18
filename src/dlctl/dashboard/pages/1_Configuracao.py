"""Pagina de Configuracao do dashboard: editar/adicionar conexoes, credenciais
e dominios diretamente pelo front-end, e testar as conexoes configuradas.
"""
from __future__ import annotations

import json as _json
import subprocess
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[3]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import streamlit as st

from dlctl.config import (
    PERMISSION_SCOPE_CONTRIBUTOR,
    PERMISSION_SCOPE_READ_ONLY,
    load_profile,
)
from dlctl.core.env_editor import (
    delete_domain,
    list_domains,
    read_env_for_form,
    secret_status,
    update_env,
    update_profile_flags,
    upsert_domain,
)

st.set_page_config(page_title="Configuracao -- Constellation Migration Control", layout="wide", page_icon="settings")
st.title("Configuracao de Conexoes e Ambiente")
st.caption(
    "Autenticacao via az CLI (`az account get-access-token`). "
    "Nenhuma credencial client_id/secret e necessaria -- basta ter o az CLI instalado e autenticado."
)

profile_name = st.text_input("Profile", value="ms_client_constellation", key="cfg_profile_name")

env_values = read_env_for_form()
secrets_ok = secret_status()

try:
    current_profile = load_profile(profile_name)
except Exception as exc:
    st.error(f"Erro ao carregar profile: {exc}")
    current_profile = None

tab_fabric, tab_oracle, tab_flags, tab_domains, tab_test = st.tabs(
    ["Microsoft Fabric", "Oracle Fusion", "Ambiente & Escrita", "Dominios", "Testar Conexoes"]
)

# ---------------- Fabric ----------------
with tab_fabric:
    st.subheader("Microsoft Fabric -- autenticacao via az CLI")

    # --- Status ao vivo da conta az ---
    st.markdown("#### Status do az CLI")
    az_account_info = None
    try:
        az_result = subprocess.run(
            ["az", "account", "show"], capture_output=True, text=True, timeout=10,
        )
        if az_result.returncode == 0:
            az_account_info = _json.loads(az_result.stdout)
            st.success(
                f"az CLI autenticado -- "
                f"conta: **{az_account_info.get('user', {}).get('name', '?')}** | "
                f"subscription: **{az_account_info.get('name', '?')}** | "
                f"tenant: `{az_account_info.get('tenantId', '?')}`"
            )
        else:
            st.warning("az CLI nao esta autenticado. Use o botao abaixo para fazer login.")
    except FileNotFoundError:
        st.error("az CLI nao encontrado. Instale em: https://aka.ms/installazurecli")
    except Exception as exc:
        st.warning(f"Nao foi possivel verificar az CLI: {exc}")

    # --- az login via front-end ---
    st.markdown("#### Login")
    tenant_for_login = st.text_input(
        "Tenant ID (opcional -- deixe em branco para usar o tenant padrao da conta az)",
        value=env_values.get("FABRIC_AZ_TENANT_ID", ""),
        key="fab_tenant_login",
        help="Se sua conta tem acesso a multiplos tenants, informe o ID do tenant Fabric aqui."
    )
    if st.button("Fazer az login (device code)", type="secondary"):
        with st.spinner("Aguardando autenticacao... Siga as instrucoes no terminal ou na janela que abrir."):
            from dlctl.auth.fabric_auth import az_login_device_code
            outcome = az_login_device_code(tenant_id=tenant_for_login or None)
        if outcome["ok"]:
            st.success(f"Login realizado com sucesso! Conta: {outcome.get('user', '?')}")
            st.rerun()
        else:
            st.error(f"Falha no az login: {outcome['message']}")

    st.divider()

    # --- Configuracao de workspace e permissao ---
    st.markdown("#### Configuracao do Workspace e Escopo de Permissao")
    with st.form("form_fabric"):
        workspace_name = st.text_input(
            "FABRIC_WORKSPACE_NAME",
            value=env_values.get("FABRIC_WORKSPACE_NAME", ""),
        )
        workspace_id = st.text_input(
            "FABRIC_WORKSPACE_ID",
            value=env_values.get("FABRIC_WORKSPACE_ID", ""),
        )
        az_tenant_id = st.text_input(
            "FABRIC_AZ_TENANT_ID (opcional)",
            value=env_values.get("FABRIC_AZ_TENANT_ID", ""),
            help="Tenant ID para passar a --tenant no az account get-access-token. Deixe vazio para usar o padrao do az."
        )

        current_scope = env_values.get("FABRIC_AZ_PERMISSION_SCOPE", PERMISSION_SCOPE_READ_ONLY)
        scope_options = [PERMISSION_SCOPE_READ_ONLY, PERMISSION_SCOPE_CONTRIBUTOR]
        scope_index = scope_options.index(current_scope) if current_scope in scope_options else 0
        permission_scope = st.selectbox(
            "Escopo de Permissao (FABRIC_AZ_PERMISSION_SCOPE)",
            options=scope_options,
            index=scope_index,
            help=(
                "read_only: somente inventario e geracao de notebooks local. "
                "contributor: permite write/execute/publish via API Fabric (requer role Contributor no workspace)."
            ),
        )
        if permission_scope == PERMISSION_SCOPE_READ_ONLY:
            st.info(
                "Modo read_only: acoes de escrita/execucao no Fabric ficam bloqueadas (disabled). "
                "Inventario, geracao de notebooks e dry-run continuam disponiveis."
            )
        else:
            st.warning(
                "Modo contributor: acoes de escrita/execucao habilitadas. "
                "Certifique-se de que sua conta az tem role Contributor (ou superior) no workspace Fabric."
            )

        submitted_fabric = st.form_submit_button("Salvar configuracao Fabric", type="primary")

    if submitted_fabric:
        updates = {
            "FABRIC_WORKSPACE_NAME": workspace_name,
            "FABRIC_WORKSPACE_ID": workspace_id,
            "FABRIC_AZ_PERMISSION_SCOPE": permission_scope,
        }
        if az_tenant_id:
            updates["FABRIC_AZ_TENANT_ID"] = az_tenant_id
        update_env(updates)
        st.success("Configuracao Fabric salva em .env")
        st.rerun()

# ---------------- Oracle ----------------
with tab_oracle:
    st.subheader("Oracle Fusion (banco + BI Publisher)")
    with st.form("form_oracle"):
        st.markdown("**Banco de dados**")
        dsn = st.text_input("ORACLE_DB_DSN", value=env_values.get("ORACLE_DB_DSN", ""))
        db_user = st.text_input("ORACLE_DB_USER", value=env_values.get("ORACLE_DB_USER", ""))
        db_pass_placeholder = "ja configurado -- deixe em branco para manter" if secrets_ok.get("ORACLE_DB_PASSWORD") else "nao configurado"
        db_password = st.text_input(f"ORACLE_DB_PASSWORD ({db_pass_placeholder})", value="", type="password")

        st.markdown("**BI Publisher (SOAP)**")
        bip_url = st.text_input("ORACLE_BIP_BASE_URL", value=env_values.get("ORACLE_BIP_BASE_URL", ""))
        bip_user = st.text_input("ORACLE_BIP_USER", value=env_values.get("ORACLE_BIP_USER", ""))
        bip_pass_placeholder = "ja configurado -- deixe em branco para manter" if secrets_ok.get("ORACLE_BIP_PASSWORD") else "nao configurado"
        bip_password = st.text_input(f"ORACLE_BIP_PASSWORD ({bip_pass_placeholder})", value="", type="password")
        submitted_oracle = st.form_submit_button("Salvar configuracao Oracle", type="primary")
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
        st.success("Configuracao Oracle salva em .env")
        st.rerun()

# ---------------- Ambiente & gates ----------------
with tab_flags:
    st.subheader("Ambiente e permissoes de escrita (gates)")
    with st.form("form_flags"):
        environment = st.selectbox("Ambiente", options=["DEV", "HML", "PRD"],
                                    index=["DEV", "HML", "PRD"].index(current_profile.environment) if current_profile else 0)
        allow_write = st.checkbox("microsoft.allow_write (permite escritas gated)",
                                   value=current_profile.microsoft.allow_write if current_profile else False)
        allow_production = st.checkbox("microsoft.allow_production (obrigatorio em PRD)",
                                        value=current_profile.microsoft.allow_production if current_profile else False)
        st.info(
            "Isto so habilita a *possibilidade* de escrita no profile. Cada comando "
            "ainda exige `--confirm-write`/`--confirm-execute` (ou o checkbox equivalente "
            "na pagina Acoes) para realmente mutar algo."
        )
        submitted_flags = st.form_submit_button("Salvar ambiente/permissoes", type="primary")
    if submitted_flags:
        update_profile_flags(
            profile_name, allow_write=allow_write, allow_production=allow_production,
            workspace_name=env_values.get("FABRIC_WORKSPACE_NAME", ""),
            workspace_id=env_values.get("FABRIC_WORKSPACE_ID", ""),
            environment=environment,
        )
        st.success("Ambiente/permissoes atualizados em config/profiles.yaml")
        st.rerun()

# ---------------- Dominios ----------------
with tab_domains:
    st.subheader("Dominios de negocio (router constellation-order-tracking-etl)")
    domains = list_domains()
    if domains:
        st.dataframe(
            [{"dominio": k, **v} for k, v in domains.items()],
            use_container_width=True,
        )
    else:
        st.info("Nenhum dominio configurado ainda.")

    with st.form("form_domain"):
        st.markdown("**Adicionar / editar dominio**")
        d_key = st.text_input("Chave do dominio (ex.: ORDER_TRACKING)")
        d_desc = st.text_input("Descricao")
        d_folder = st.text_input("folder_path (ex.: pipelines/SUPRIMENTOS)")
        d_silver = st.text_input("silver_lakehouse")
        d_gold = st.text_input("gold_lakehouse")
        submitted_domain = st.form_submit_button("Salvar dominio", type="primary")
    if submitted_domain and d_key:
        upsert_domain(d_key, d_desc, d_folder, d_silver, d_gold)
        st.success(f"Dominio '{d_key}' salvo.")
        st.rerun()

    if domains:
        del_key = st.selectbox("Remover dominio", options=["(nenhum)"] + list(domains.keys()))
        if del_key != "(nenhum)" and st.button("Remover dominio selecionado", type="secondary"):
            delete_domain(del_key)
            st.success(f"Dominio '{del_key}' removido.")
            st.rerun()

# ---------------- Testar conexoes ----------------
with tab_test:
    st.subheader("Testar conexoes configuradas")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Testar Microsoft Fabric", type="primary"):
            try:
                from dlctl.connectors.fabric_api import FabricApiError, build_client_from_profile
                p = load_profile(profile_name)
                client = build_client_from_profile(p)
                workspaces = client.list_workspaces()
                st.success(f"OK: autenticado via az CLI, {len(workspaces)} workspace(s) visivel(eis).")
                st.json([w.get("displayName") for w in workspaces])
            except Exception as exc:
                st.error(f"Falha: {exc}")
    with col2:
        if st.button("Testar Oracle DB", type="primary"):
            try:
                from dlctl.connectors.oracle_connector import OracleDbConnector
                p = load_profile(profile_name)
                conn = OracleDbConnector(p)
                result = conn.test_connection()
                st.success(f"OK: {result}")
            except Exception as exc:
                st.error(f"Falha (ou manual_required): {exc}")
