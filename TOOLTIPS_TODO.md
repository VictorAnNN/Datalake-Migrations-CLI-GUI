# 📋 Tooltips Necessários — Todas as Páginas do Dashboard

## Status: Implementação em Progresso

Este documento mapeia **TODOS** os widgets (inputs, botões, checkboxes, etc) que precisam de tooltips em cada página do dashboard.

---

## ✅ Páginas Já Feitas

### **4_CopyJobs.py** ✅ COMPLETO
- 18+ tooltips adicionados
- Todos os inputs, botões, checkboxes com `help`
- Bloqueios com contexto detalhado

### **1_Configuracao.py** ⚡ EM PROGRESSO (50%)
- ✅ Profile input
- ✅ Workspace Name, ID, Tenant inputs
- ✅ Permission Scope selectbox
- ✅ Botão Salvar Fabric
- ❌ Oracle inputs (DSN, User, Password)
- ❌ Flags (allow_write, allow_production, environment)
- ❌ Domains tab (inputs de domínios)
- ❌ Botões de teste

---

## 🔴 Páginas Faltando

### **2_Acoes.py** — Botões de Ação
**Widgets que faltam tooltips:**
- Domínio selectbox ❌
- Botão "Rodar inventário Silver" ❌
- Botão "Rodar inventário Gold" ❌
- Botão "Reconcile-scope" ❌
- Selectbox de Mapping/Silver ❌
- Botão "Gerar Silver" ❌
- Checkbox "Validar após gerar" ❌
- Selectbox de Gold ❌
- Botão "Gerar Gold" ❌
- Selectbox/Upload Manifesto ❌
- Checkboxes de confirmação (Write, Execute) ❌
- Botão "Validate" ❌
- Botão "Plan" ❌
- Botão "Dry-run" ❌
- Botão "Apply" ❌
- Text input de Notebook/Pipeline ❌
- Number inputs de parâmetros ❌
- Botão "Executar" ❌
- Etc...

**Total estimado:** 25+ widgets

### **3_Diagnosticos_Avancados.py** — Ferramentas
**Widgets que faltam tooltips:**
- Profile input ❌
- Selectbox de Prioridade ❌
- Selectbox de Status ❌
- Text inputs de copyjob/schema ❌
- Botões de Auditoria ❌
- Form de Lease (owner, workspace, item_ids, tables, TTL) ❌
- Botão Adquirir Lease ❌
- Selectbox de Lease para liberar ❌
- Input de owner para liberar ❌
- Botão Liberar Lease ❌
- Selectbox de Manifesto ❌
- Checkboxes de confirmação ❌
- Botão "Rodar Campanha" ❌
- Text input de arquivo de definição ❌
- Botões de inspect ❌
- Text area de log ❌
- Botão de classify ❌
- Etc...

**Total estimado:** 30+ widgets

### **4_Retro_Melhoria_Continua.py** — Análise
**Widgets que faltam tooltips:**
- Profile input ❌
- Botão "Rodar Análise" ❌
- Multiselect de categoria ❌
- Multiselect de severidade ❌
- Botões Aprovar/Rejeitar ❌
- Botão Download relatório ❌
- Etc...

**Total estimado:** 10+ widgets

### **app.py** (Main Page)
**Widgets que faltam tooltips:**
- Profile input ❌
- Domain selectbox ❌
- Tabs de seções ❌

**Total estimado:** 3 widgets

---

## 📊 Resumo

| Página | Status | Widgets | Tooltips |
|---|---|---|---|
| 4_CopyJobs.py | ✅ COMPLETO | 15 | 18+ |
| 1_Configuracao.py | ⚡ 50% | 20 | 5 (need 15 more) |
| 2_Acoes.py | ❌ 0% | 25 | 0 (need 25) |
| 3_Diagnosticos_Avancados.py | ❌ 0% | 30 | 0 (need 30) |
| 4_Retro_Melhoria_Continua.py | ❌ 0% | 10 | 0 (need 10) |
| app.py | ❌ 0% | 3 | 0 (need 3) |
| **TOTAL** | | **103** | **23 (need 83)** |

---

## 🎯 Tooltips Padrão por Tipo de Widget

```python
# Text Input
help="📝 Digite o valor aqui. Pressione Enter para confirmar."

# Text Area
help="📄 Texto multilinha. Útil para colar JSON, YAML, etc."

# Selectbox / Radio
help="🔽 Clique para escolher uma opção."

# Multiselect
help="✓ Clique em cada opção para marcar/desmarcar múltiplas seleções."

# Checkbox
help="☑️ Marque para habilitar. Desmarque para desabilitar."

# Button (Primary/Secondary)
help="🔘 Clique para executar esta ação."

# Number Input
help="🔢 Digite um número. Use as setas para ajustar."

# File Uploader
help="📂 Selecione um arquivo ou arraste aqui."

# Slider / Select Slider
help="⏱️ Deslize para ajustar o valor."
```

---

## 📝 Próximos Passos

### 1️⃣ Completar 1_Configuracao.py (5 tooltips mais)
- [ ] Oracle inputs
- [ ] Flags
- [ ] Domains section
- [ ] Test buttons

### 2️⃣ Adicionar tooltips 2_Acoes.py (25 tooltips)
- [ ] Domínio selectbox
- [ ] Botões de Inventário
- [ ] Inputs de Silver/Gold
- [ ] Manifesto
- [ ] Execution
- [ ] Pipeline

### 3️⃣ Adicionar tooltips 3_Diagnosticos_Avancados.py (30 tooltips)
- [ ] Profile
- [ ] Backlog filters
- [ ] Copyjob audit
- [ ] Leases
- [ ] Campaign
- [ ] Definitions
- [ ] Log Classifier

### 4️⃣ Adicionar tooltips 4_Retro_Melhoria_Continua.py (10 tooltips)
- [ ] Profile
- [ ] Analyze button
- [ ] Filters
- [ ] Approve/Reject buttons
- [ ] Download button

### 5️⃣ Adicionar tooltips app.py (3 tooltips)
- [ ] Profile
- [ ] Domain selectbox

---

## 💡 Estratégia de Implementação

### Opção A: Manual (Mais trabalho, mais preciso)
Editar cada arquivo `.py` e adicionar `help=` em cada widget.

**Tempo estimado:** 4-5 horas

### Opção B: Script Python (Mais rápido)
Criar um script que:
1. Varre todos os `.py`
2. Encontra widgets sem `help`
3. Adiciona `help` baseado no label

**Tempo estimado:** 1-2 horas

---

## ✨ Benefício Final

**Antes:**
```
Workspace [____]  ← Usuário não sabe o que preencher
```

**Depois:**
```
Workspace [____] ❓  ← Passa mouse, vê:
                     "🌐 Nome do workspace Fabric 
                      (ex: 'default-workspace')"
```

**Resultado:** Dashboard 100% autoexplicativo. Nenhum widget sem ajuda.
