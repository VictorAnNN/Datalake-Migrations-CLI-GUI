# 💡 Tooltips & Help Text — Guia Visual

A página de Copy Jobs agora tem tooltips (ícone de **?**) em pontos estratégicos para ajudar o usuário a entender:
- **O que fazer** (descrição do input)
- **Por que está bloqueado** (motivo da restrição)
- **Como desbloquear** (onde mudar a configuração)

---

## 📌 Onde Estão os Tooltips

### **Sidebar (Esquerdo)**

```
┌─────────────────────────────────────────┐
│ 🛰️ Constellation Migration Control      │
│                                         │
│ Profile: ms_client_constellation        │
│                                         │
│ Auth: az_cli                           │
│ Escopo: read_only (ou contributor)     │
│ Tenant: <tenant_id>                    │
│ allow_write: True / False              │
│                                         │
│ 🔒 ESCOPO READ_ONLY: Ações bloqueadas  │ ← ⚠️ Mensagem Detalhada
│    (Run, Apply estão desabilitados)      │
│    Vá em Configuração para mudar.        │
│                                         │
│ ⛔ ALLOW_WRITE DESABILITADO: Apply      │ ← ⚠️ Mensagem Detalhada
│    bloqueado. Ative em Configuração.    │
└─────────────────────────────────────────┘
```

---

### **Tab "List & Run"**

```
┌──────────────────────────────────────────────────────┐
│ Workspace                                         ?  │ ← TOOLTIP
│ [input field] 🌐 "Ex: default-workspace"            │
│   Tooltip: "Nome do workspace Fabric onde os Copy   │
│            Jobs estão. Ex: 'default-workspace'..."   │
│                                                     │
│ [Buscar Copy Jobs] ?                               │ ← TOOLTIP
│   Tooltip: "Conecta ao Fabric e lista todos os     │
│            Copy Jobs existentes neste workspace"    │
└──────────────────────────────────────────────────────┘

[Se permission_scope = read_only]
┌──────────────────────────────────────────────────────┐
│ 🔒 ESCOPO READ_ONLY: EXECUÇÃO BLOQUEADA             │ ← ERROR DETALHADO
│                                                     │
│ Seu nível de permissão não permite executar Copy   │
│ Jobs. Altere em:                                   │
│ Configuração → Microsoft Fabric → permission_scope │
│ ⚠️ Apenas administradores podem fazer isto.        │
└──────────────────────────────────────────────────────┘
```

---

### **Tab "Bulk Plan"**

```
┌──────────────────────────────────────────────────────┐
│ Workspace                                         ?  │ ← TOOLTIP
│ [input field] 🌐 "Se deixar em branco..."           │
│   Tooltip: "🌐 Nome do workspace no Fabric.         │
│            Se deixar em branco, roda 100% offline   │
│            (local-only), mostrando tudo como        │
│            'create'. Útil para validação."          │
│                                                     │
│ Diretório de Definições                           ?  │ ← TOOLTIP
│ [input field] 📁 "copyjob_definitions/bulk"        │
│   Tooltip: "📁 Caminho relativo contendo            │
│            *.copyjob.yaml. Padrão:                  │
│            'copyjob_definitions/bulk'"              │
│                                                     │
│ [📊 Executar Plan]                               ?  │ ← TOOLTIP
│   Tooltip: "Compara definições locais vs Fabric.    │
│            Mostra o que vai ser criado (🟢),        │
│            atualizado (🟡), ignorado (⚪),          │
│            ou bloqueado (🔴)"                       │
└──────────────────────────────────────────────────────┘
```

---

### **Tab "Bulk Apply"**

```
┌──────────────────────────────────────────────────────┐
│ Cole o JSON do plan                              ?   │ ← TOOLTIP
│ [textarea com placeholder]                          │
│   Tooltip: "📋 Cole o JSON completo que foi         │
│            exibido após rodar 'Bulk Plan'.          │
│            Este JSON é 'congelado' — se você        │
│            mudar definições locais, rode Plan       │
│            novamente."                              │
│                                                     │
│ Confirmações:                                       │
│ ☑ Confirmo escrita (--confirm-write)           ?    │ ← TOOLTIP
│   Tooltip: "☑️ Obrigatório: autoriza                │
│            criação/atualização de Copy Jobs.        │
│            Sem isto, o botão fica desabilitado."    │
│                                                     │
│ ☑ Confirmo produção (--confirm-production)     ?    │ ← TOOLTIP
│   Tooltip: "☑️ Adicional: se seu workspace for      │
│            PRD, VOCÊ DEVE marcar isto.              │
│            Se for DEV/HML, é opcional."             │
│                                                     │
│ [✅ Aplicar Plan]                              ?     │ ← TOOLTIP
│   Tooltip: "Cria/atualiza Copy Jobs no Fabric.      │
│            ⚠️ Desabilitado até você marcar          │
│            '--confirm-write' e colar JSON."         │
└──────────────────────────────────────────────────────┘

[Se read_only ou allow_write = False]
┌──────────────────────────────────────────────────────┐
│ 🔒 ESCOPO READ_ONLY: APLICAÇÃO BLOQUEADA            │ ← ERROR DETALHADO
│    Seu nível não permite criar/atualizar            │
│    Copy Jobs. Altere em:                            │
│    Configuração → Microsoft Fabric → permission     │
│                                                     │
│ ⛔ ALLOW_WRITE DESABILITADO                         │ ← ERROR DETALHADO
│    Ative em:                                        │
│    Configuração → Ambiente & Escrita → allow_write  │
└──────────────────────────────────────────────────────┘
```

---

### **Tab "Bulk Reconcile"**

```
┌──────────────────────────────────────────────────────┐
│ Workspace                                         ?  │ ← TOOLTIP
│ [input field]                                       │
│   Tooltip: "🌐 Nome do workspace no Fabric.         │
│            Deixe em branco para rodar offline."     │
│                                                     │
│ Diretório de Definições                           ?  │ ← TOOLTIP
│ [input field]                                       │
│   Tooltip: "📁 Caminho relativo contendo            │
│            *.copyjob.yaml."                         │
│                                                     │
│ [🔍 Executar Reconcile]                          ?  │ ← TOOLTIP
│   Tooltip: "Compara: o que existe localmente        │
│            mas não no Fabric (missing),             │
│            o que existe no Fabric mas não           │
│            localmente (orphaned), e duplicatas."    │
└──────────────────────────────────────────────────────┘
```

---

## 🎯 Tipos de Tooltips

### **1. Informativo (input/botão)**
```
Workspace ?
Tooltip: "🌐 Nome do workspace Fabric onde os Copy Jobs estão..."
```
- Mostra **o que preencher** e **por quê**
- Sempre disponível (não tem restrição)

### **2. De Confirmação (checkbox)**
```
☑ Confirmo execução (--confirm-execute) ?
Tooltip: "☑️ Obrigatório: marca para autorizar.
         Sem isto, o botão fica desabilitado."
```
- Explica **o quê** a confirmação autoriza
- Avisa do impacto de **não marcar**

### **3. De Erro (st.error com detalhes)**
```
🔒 ESCOPO READ_ONLY: EXECUÇÃO BLOQUEADA
Seu nível não permite executar Copy Jobs.
Altere em: Configuração → Microsoft Fabric → permission_scope
⚠️ Apenas administradores podem fazer isto.
```
- Mostra **por quê** está bloqueado
- Aponta **exatamente onde** mudar (breadcrumb)
- Avisa se há **limitações** (ex: só admin)

### **4. De Aviso (st.warning em sidebar)**
```
🔒 Escopo read_only: Ações bloqueadas
Você tem permissão para: Listar, Planejar, Reconciliar
Você NÃO tem permissão para: Executar, Aplicar
Vá em Configuração para mudar.
```
- Resumo visual no sidebar
- Indica **o que pode/não pode fazer**

---

## 💻 Como Funciona Technicamente

### **Parâmetro `help` em Widgets Streamlit:**

```python
# Input com tooltip
workspace = st.text_input(
    "Workspace",
    help="🌐 Nome do workspace. Se deixar vazio, roda offline..."
)

# Checkbox com tooltip
confirm = st.checkbox(
    "Confirmo execução",
    help="☑️ Obrigatório: marca para autorizar..."
)

# Botão com tooltip
st.button(
    "🚀 Executar",
    help="Dispara o Copy Job. Desabilitado até confirmar..."
)
```

**Resultado:** Ícone `?` aparece ao lado do widget. Ao passar o mouse, tooltip exibe.

### **Mensagens Contextuais (st.error, st.warning):**

```python
if profile.microsoft.is_read_only:
    st.error(
        "🔒 **Escopo read_only: execução bloqueada.** "
        "Seu nível não permite. Altere em "
        "**Configuração → Microsoft Fabric → permission_scope**."
    )
```

**Resultado:** Caixa vermelha com contexto completo + caminho para solucionar.

---

## 🎨 Ícones Usados

| Ícone | Significado |
|---|---|
| 🌐 | Workspace (Fabric) |
| 📁 | Diretório/Caminho |
| 📋 | Plano/JSON |
| ☑️ | Confirmação obrigatória |
| ☑ | Confirmação recomendada |
| 🚀 | Ação de execução |
| 📊 | Ação de planejamento |
| 🔍 | Ação de busca/reconciliação |
| ✅ | Ação de aplicação/sucesso |
| 🔒 | Bloqueado (read_only) |
| ⛔ | Bloqueado (flag desabilitado) |
| ⚠️ | Aviso/Restrição |
| ℹ️ | Informação |

---

## 📝 Exemplos de Tooltips Completos

### **Exemplo 1: Workspace em Bulk Plan**
```
Workspace ?
Tooltip:
  "🌐 Nome do workspace no Fabric.
   
   Se deixar em branco, o plano roda 100% offline 
   (local-only), mostrando tudo como 'create'.
   Útil para validação antes de conectar."
```

### **Exemplo 2: Checkbox de Confirmação**
```
☑ Confirmo escrita (--confirm-write) ?
Tooltip:
  "☑️ Obrigatório: autoriza a criação/atualização 
   de Copy Jobs no Fabric.
   
   Sem esta confirmação, o botão 'Aplicar Plan'
   fica desabilitado por motivo de segurança."
```

### **Exemplo 3: Botão Bloqueado**
```
[🚀 Executar Copy Job] ?
Tooltip (quando desabilitado):
  "Dispara a execução do Copy Job no Fabric.
   
   ⚠️ DESABILITADO: Marque '--confirm-execute'
   para habilitar este botão."
```

---

## ✨ Benefícios para o Usuário

| Benefício | Como Ajuda |
|---|---|
| **Menos clicks** | Tooltip no hover = respostas rápidas |
| **Menos erros** | Aviso detalhado de por quê está bloqueado |
| **Autoexplicativo** | Cada campo sabe por quê existe |
| **Acesso rápido** | Breadcrumb "Configuração → ..." no erro |
| **Segurança clara** | Entende por quê confirmações são necessárias |

---

## 🚀 Próximas Melhorias (Opcionais)

1. **Ícones clicáveis** em vez de hover (melhor em mobile)
2. **Videoguia** embutido (link para tutorial)
3. **Histórico de tooltips** (o que você aprendeu hoje)
4. **Personalizables** (user pode desativar tooltips)
