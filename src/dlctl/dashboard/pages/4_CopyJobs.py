"""
CopyJobs Management page for Fabric migrations.
Provides 4 operational tabs:
1. List & Run — Query workspace, list Copy Jobs, run one
2. Bulk Plan — Compare local vs Fabric
3. Bulk Apply — Apply bulk plan changes
4. Bulk Reconcile — Show missing/orphaned items
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[3]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import streamlit as st

from dlctl.config import load_profile
from dlctl.core.gates import GateContext, SecurityError
from dlctl.core.env_editor import read_env_for_form

st.set_page_config(
    page_title="CopyJobs -- Constellation Migration Control",
    layout="wide",
    page_icon="📋"
)

st.title("Gerenciamento de Copy Jobs")
st.caption(
    "Crie, edite, liste e execute Copy Jobs na Fabric via API. "
    "Operações de escrita requerem scope='contributor' no .env."
)

# Load environment and config
env_values = read_env_for_form()
profile_name = env_values.get("PROFILE_NAME", "ms_client_constellation")

try:
    current_profile = load_profile(profile_name)
    workspace_id = env_values.get("FABRIC_WORKSPACE_ID", "")
    workspace_name = env_values.get("FABRIC_WORKSPACE_NAME", "")
except Exception as exc:
    st.error(f"Erro ao carregar configuração: {exc}")
    st.stop()

# Display permission status
if current_profile.microsoft.is_read_only:
    st.sidebar.info("🔒 Permissão: read_only — operações de escrita bloqueadas")
else:
    st.sidebar.success("✅ Permissão: contributor — todas operações habilitadas")

# Tabs for different operations
tab1, tab2, tab3, tab4 = st.tabs(
    [
        "📋 Listar e Executar",
        "📝 Planejar (Bulk)",
        "✅ Aplicar (Bulk)",
        "🔍 Reconciliar (Bulk)"
    ]
)

# ============================================
# TAB 1: List & Run
# ============================================
with tab1:
    st.subheader("Listar e Executar Copy Jobs")
    
    col1, col2 = st.columns(2)
    with col1:
        workspace_input = st.text_input(
            "ID do Workspace",
            value=workspace_id,
            help="🆔 ID único do workspace Fabric. Se deixar em branco, use FABRIC_WORKSPACE_ID do .env."
        )
    with col2:
        list_jobs_btn = st.button(
            "Listar Copy Jobs",
            type="secondary",
            help="📋 Busca todos os Copy Jobs neste workspace."
        )
    
    if list_jobs_btn:
        if not workspace_input and not workspace_id:
            st.error("❌ Informe o ID do workspace")
        else:
            with st.spinner("Buscando Copy Jobs..."):
                ws_id = workspace_input or workspace_id
                try:
                    # Call dlctl copyjobs list <workspace_id>
                    result = subprocess.run(
                        ["python", "-m", "dlctl.cli", "copyjobs", "list", ws_id],
                        capture_output=True,
                        text=True,
                        timeout=30,
                        cwd=str(SRC_DIR)
                    )
                    if result.returncode == 0:
                        st.json(json.loads(result.stdout))
                    else:
                        st.error(f"Erro: {result.stderr}")
                except Exception as e:
                    st.error(f"Erro ao executar: {e}")
    
    st.divider()
    
    st.subheader("Executar um Copy Job")
    col1, col2, col3 = st.columns(3)
    with col1:
        job_id = st.text_input(
            "ID do Copy Job",
            help="🆔 Identificador único do Copy Job a executar."
        )
    with col2:
        confirm_execute = st.checkbox(
            "Confirmar execução",
            help="✅ Marca consentimento para executar (equivalente a --confirm-execute)"
        )
    with col3:
        run_btn = st.button(
            "Executar Job",
            type="primary",
            help="▶️ Inicia a execução do Copy Job no Fabric."
        )
    
    if run_btn:
        if not job_id:
            st.error("❌ Informe o ID do Copy Job")
        elif not confirm_execute:
            st.warning("⚠️ Marque 'Confirmar execução' para prosseguir")
        else:
            # Check permission first
            gate = GateContext(current_profile)
            try:
                gate.require_az_permission("run", "executar Copy Job")
            except SecurityError as e:
                st.error(f"🔒 Acesso negado: {e}")
                st.info("Sua conexão está em modo read_only. Altere em **Configuracao** > **Ambiente & Escrita**")
            else:
                with st.spinner(f"Executando Copy Job {job_id}..."):
                    try:
                        result = subprocess.run(
                            ["python", "-m", "dlctl.cli", "copyjobs", "run", job_id, "--confirm-execute"],
                            capture_output=True,
                            text=True,
                            timeout=60,
                            cwd=str(SRC_DIR)
                        )
                        if result.returncode == 0:
                            st.success(f"✅ Job executado com sucesso!\n{result.stdout}")
                        else:
                            st.error(f"❌ Erro: {result.stderr}")
                    except Exception as e:
                        st.error(f"❌ Erro ao executar: {e}")

# ============================================
# TAB 2: Bulk Plan
# ============================================
with tab2:
    st.subheader("Planejar Bulk (Comparar local vs Fabric)")
    
    col1, col2 = st.columns(2)
    with col1:
        plan_dir = st.text_input(
            "Diretório com Copy Jobs locais",
            value="definitions/copyjobs",
            help="📁 Caminho local contendo arquivos YAML/JSON de Copy Jobs (ex: definitions/copyjobs)"
        )
    with col2:
        plan_workspace = st.text_input(
            "ID do Workspace Fabric",
            value=workspace_id,
            help="🆔 ID do workspace para comparação. Deixe vazio para modo offline."
        )
    
    offline_mode = st.checkbox(
        "Modo offline (sem conexão Fabric)",
        value=False,
        help="⚠️ Se marcado, valida apenas localmente sem conectar ao Fabric."
    )
    
    plan_btn = st.button(
        "Gerar Plano de Bulk",
        type="secondary",
        help="📋 Compara definições locais com o Fabric e gera plano de mudanças."
    )
    
    if plan_btn:
        if not plan_dir:
            st.error("❌ Informe o diretório com Copy Jobs")
        else:
            with st.spinner("Gerando plano..."):
                try:
                    cmd = ["python", "-m", "dlctl.cli", "copyjobs", "bulk", "plan", plan_dir]
                    if plan_workspace and not offline_mode:
                        cmd.extend(["--workspace", plan_workspace])
                    if offline_mode:
                        cmd.append("--offline")
                    
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=60,
                        cwd=str(SRC_DIR)
                    )
                    if result.returncode == 0:
                        st.success("✅ Plano gerado com sucesso")
                        st.text(result.stdout)
                    else:
                        if offline_mode:
                            st.info("⚠️ Modo offline: validações locais apenas")
                            st.text(result.stdout)
                        else:
                            st.error(f"❌ Erro: {result.stderr}")
                except Exception as e:
                    st.error(f"❌ Erro: {e}")

# ============================================
# TAB 3: Bulk Apply
# ============================================
with tab3:
    st.subheader("Aplicar Bulk (Executar Plano)")
    
    col1, col2 = st.columns(2)
    with col1:
        apply_dir = st.text_input(
            "Diretório com Copy Jobs",
            value="definitions/copyjobs",
            help="📁 Caminho contendo plano de Copy Jobs."
        )
    with col2:
        apply_workspace = st.text_input(
            "ID do Workspace Fabric",
            value=workspace_id,
            help="🆔 Workspace onde aplicar o plano."
        )
    
    col1, col2, col3 = st.columns(3)
    with col1:
        confirm_write = st.checkbox(
            "Confirmar escrita",
            help="✅ Autoriza mudanças no Fabric (--confirm-write)"
        )
    with col2:
        confirm_production = st.checkbox(
            "Confirmar produção",
            help="🚀 Requerido para ambientes PRD (--confirm-production)"
        )
    with col3:
        apply_btn = st.button(
            "Aplicar Plano",
            type="primary",
            help="▶️ Executa o plano criado no Fabric."
        )
    
    if apply_btn:
        if not apply_dir or not apply_workspace:
            st.error("❌ Informe diretório e workspace")
        elif not confirm_write:
            st.warning("⚠️ Marque 'Confirmar escrita' para prosseguir")
        else:
            # Check permission
            gate = GateContext(current_profile)
            try:
                gate.require_az_permission("write", "aplicar plano de Copy Jobs")
            except SecurityError as e:
                st.error(f"🔒 Acesso negado: {e}")
                st.info("Sua conexão está em modo read_only. Altere em **Configuracao** > **Ambiente & Escrita**")
            else:
                with st.spinner("Aplicando plano..."):
                    try:
                        cmd = ["python", "-m", "dlctl.cli", "copyjobs", "bulk", "apply", apply_dir, 
                               "--workspace", apply_workspace, "--confirm-write"]
                        if confirm_production:
                            cmd.append("--confirm-production")
                        
                        result = subprocess.run(
                            cmd,
                            capture_output=True,
                            text=True,
                            timeout=120,
                            cwd=str(SRC_DIR)
                        )
                        if result.returncode == 0:
                            st.success("✅ Plano aplicado com sucesso!")
                            st.text(result.stdout)
                        else:
                            st.error(f"❌ Erro: {result.stderr}")
                    except Exception as e:
                        st.error(f"❌ Erro: {e}")

# ============================================
# TAB 4: Bulk Reconcile
# ============================================
with tab4:
    st.subheader("Reconciliar Bulk (Verificar Integridade)")
    
    col1, col2 = st.columns(2)
    with col1:
        recon_dir = st.text_input(
            "Diretório com Copy Jobs",
            value="definitions/copyjobs",
            help="📁 Caminho com definições locais."
        )
    with col2:
        recon_workspace = st.text_input(
            "ID do Workspace Fabric",
            value=workspace_id,
            help="🆔 Workspace para verificação."
        )
    
    recon_btn = st.button(
        "Executar Reconciliação",
        type="secondary",
        help="🔍 Identifica diferenças entre local e Fabric (faltantes, órfãos, etc)."
    )
    
    if recon_btn:
        if not recon_dir or not recon_workspace:
            st.error("❌ Informe diretório e workspace")
        else:
            with st.spinner("Reconciliando..."):
                try:
                    result = subprocess.run(
                        ["python", "-m", "dlctl.cli", "copyjobs", "bulk", "reconcile", recon_dir,
                         "--workspace", recon_workspace],
                        capture_output=True,
                        text=True,
                        timeout=60,
                        cwd=str(SRC_DIR)
                    )
                    if result.returncode == 0:
                        st.success("✅ Reconciliação concluída")
                        st.text(result.stdout)
                    else:
                        st.error(f"❌ Erro: {result.stderr}")
                except Exception as e:
                    st.error(f"❌ Erro: {e}")

# ============================================
# Footer
# ============================================
st.divider()
st.caption(
    "💡 **Dica**: Para operações em produção (PRD), certifique-se de que "
    "microsoft.allow_production=true está setado em Configuracao > Ambiente & Escrita"
)
