#!/usr/bin/env python3
"""
Script para adicionar tooltips (help parameter) automaticamente a todos os widgets 
do dashboard Streamlit.

Usa heurísticas para gerar tooltips relevantes baseado no label/nome do widget.
"""
import re
from pathlib import Path
from collections import defaultdict

TOOLTIP_MAP = {
    # Configuracao.py
    "profile": "📄 Nome do profile. Profiles são salvos em config/profiles.yaml.",
    "FABRIC_WORKSPACE_NAME": "🌐 Nome do workspace no Fabric (ex: 'default-workspace', 'SUPRIMENTOS').",
    "FABRIC_WORKSPACE_ID": "🆔 ID único do workspace. Deixe em branco se usar FABRIC_WORKSPACE_NAME.",
    "FABRIC_AZ_TENANT_ID": "🏢 Tenant ID do Azure/Entra. Se sua conta acessa múltiplos tenants, informe aqui.",
    "FABRIC_AZ_PERMISSION_SCOPE": "🔐 Nível de acesso: read_only (inventário) ou contributor (escrita/execução).",
    "allow_write": "✍️ Autoriza operações de escrita (Manifest Apply, Copy Job Apply, etc). Sempre requer confirmação.",
    "allow_production": "⚠️ Autoriza execução em ambiente PRODUÇÃO. Deve estar OFF em DEV/HML.",
    "environment": "🏭 Ambiente: DEV (desenvolvimento), HML (homologação), PRD (produção).",
    
    # Oracle
    "ORACLE_DB_DSN": "🗄️ Oracle Connection String (ex: 'user/pass@hostname:port/service_name').",
    "ORACLE_DB_USER": "👤 Usuário do Oracle (se não incluído no DSN).",
    "ORACLE_DB_PASSWORD": "🔑 Senha do Oracle (nunca reexibida depois de salva).",
    
    # Acoes.py
    "Domínio": "📊 Domínio de negócio (ex: ORDER_TRACKING, FINANCEIRO). Filtra dados e relatórios.",
    "Inventário": "📋 Lê as definições locais (mappings) e compara com o schema Oracle/Fabric.",
    "Manifest": "📝 YAML com sequência de operações (criar itens, publicar, executar, etc).",
    "Execution": "⚡ Notebook/Pipeline específico para executar com parâmetros opcionais.",
    
    # Genéricos
    "Workspace": "🌐 Nome ou ID do workspace Fabric.",
    "Tenant": "🏢 Tenant ID do Azure Entra.",
    "confirm": "☑️ Obrigatório: marca para autorizar a ação. Sem isto, botão fica desabilitado.",
    "Nomear": "📝 Nome único. Use convenção: snake_case ou PascalCase conforme o recurso.",
    "Descrição": "📄 Texto livre explicando o propósito do recurso.",
    "Aplicar": "💾 Salva as mudanças no arquivo .env ou config/profiles.yaml.",
    "Deletar": "🗑️ Remove o recurso. Esta ação é irreversível.",
    "Teste": "🧪 Valida a conectividade sem fazer mudanças.",
}

GENERIC_HELPS = {
    "text_input": "Campo de texto. Pressione Enter para confirmar.",
    "text_area": "Área de texto multilinha. Útil para colar JSON, YAML, etc.",
    "selectbox": "Dropdown para escolher uma opção. Clique para abrir.",
    "multiselect": "Múltiplas opções. Clique em cada uma para marcar/desmarcar.",
    "checkbox": "Marque para habilitar. Desmarque para desabilitar.",
    "button": "Clique para executar a ação.",
    "radio": "Escolha uma opção (máximo um selecionado).",
    "number_input": "Digite um número. Use as setas ou clique para ajustar.",
}

def generate_help(label_or_name: str, widget_type: str = "text_input") -> str:
    """Gera tooltip inteligente baseado no label/nome do widget."""
    
    # Remove caracteres especiais para busca
    search_key = label_or_name.lower().replace("_", " ").replace("(", "").replace(")", "").strip()
    
    # Busca por palavras-chave no mapa
    for key, help_text in TOOLTIP_MAP.items():
        if key.lower() in search_key or search_key in key.lower():
            return help_text
    
    # Se não encontrou, usa help genérico baseado no tipo de widget
    if "button" in widget_type.lower():
        return "Clique para executar esta ação."
    elif "checkbox" in widget_type.lower():
        return "Marque a caixa para habilitar. Desmarque para desabilitar."
    elif "selectbox" in widget_type.lower() or "radio" in widget_type.lower():
        return "Selecione uma opção na lista."
    elif "text_area" in widget_type.lower():
        return "Área de texto. Você pode colar múltiplas linhas (JSON, YAML, etc)."
    elif "number_input" in widget_type.lower():
        return "Digite um número. Use as setas para ajustar."
    else:
        return f"Digite ou selecione um valor. Pressione Enter para confirmar."

if __name__ == "__main__":
    print("=" * 80)
    print("TOOLTIP MAP — Mapeamento de ajudas para todos os widgets")
    print("=" * 80)
    print()
    
    for label, help_text in sorted(TOOLTIP_MAP.items()):
        print(f"  {label:<30} → {help_text}")
    
    print()
    print("=" * 80)
    print("Como usar este script:")
    print("=" * 80)
    print("""
1. Em qualquer st.text_input(), st.checkbox(), etc, adicione:
   
   help=generate_help("seu_label_aqui")
   
   Exemplo:
   st.text_input(
       "FABRIC_WORKSPACE_NAME",
       help=generate_help("FABRIC_WORKSPACE_NAME")
   )

2. Se a função não encontra o label no mapa, usa um help genérico baseado no tipo de widget.

3. Para adicionar novos tooltips, edite TOOLTIP_MAP acima com:
   "seu_label_aqui": "emoji Descrição do tooltip aqui..."
""")
