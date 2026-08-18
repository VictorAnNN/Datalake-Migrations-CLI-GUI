# 📋 Copy Jobs — Guia de Uso da Nova Página

## Localização
**Dashboard Streamlit** → página `4_CopyJobs.py` (aba lateral: "Copy Jobs — Gerenciamento ao Vivo")

---

## 🚀 Fluxo de Uso

### **1️⃣ Tab "List & Run"** — Listar e Executar Copy Jobs

**Quando usar:** Você quer ver quais Copy Jobs existem em um workspace e executar um específico.

**Passo a passo:**
1. Insira o **Workspace** (ex: `default-workspace`)
2. Clique em **"Buscar Copy Jobs"** → carrega a lista do Fabric
3. Selecione um Copy Job na dropdown
4. Marque **"Confirmo execução (--confirm-execute)"**
5. Clique em **"🚀 Executar Copy Job"**

**Resultado:** O Copy Job é disparado no Fabric. ID da instância aparece na resposta.

---

### **2️⃣ Tab "Bulk Plan"** — Planejar Definições em Lote

**Quando usar:** Você tem múltiplas definições locais (`*.copyjob.yaml`) e quer ver o que vai ser criado/atualizado/ignorado.

**Passo a passo:**
1. Insira o **Workspace** (opcional — deixe em branco para rodar offline)
2. Deixe o padrão **"Diretório de Definições"** = `copyjob_definitions/bulk` (ou customize)
3. Clique em **"📊 Executar Plan"**

**Resultado:** Tabela com entradas e ações:
- 🟢 **create** — será criado no Fabric
- 🟡 **update** — será atualizado (definição mudou)
- ⚪ **noop** — já existe e não mudou
- 🔴 **manual_required** — erro ou sem Fabric client

**Observação:** Se deixar Workspace vazio, roda em **offline-only** (tudo aparece como `create`).

---

### **3️⃣ Tab "Bulk Apply"** — Aplicar Plan (Criar/Atualizar)

**Quando usar:** Você rodou o Plan, aprovou a lista de mudanças, e quer criar/atualizar os Copy Jobs no Fabric.

**Passo a passo:**
1. Copie o **JSON do plan** (resultante da aba anterior) e cole na textarea
2. Marque **"Confirmo escrita (--confirm-write)"**
3. Marque **"Confirmo produção (--confirm-production)"** se for PRD
4. Clique em **"✅ Aplicar Plan"**

**Resultado:** Cada entrada do plan é processada. Você vê:
- `applied` — sucesso
- `noop` — não alterado
- `manual_required` — bloqueado (ex: sem client)
- `failed` — erro

**⚠️ Importante:** Apply **não executa** os Copy Jobs — só cria/atualiza as definições. Para executar, use a aba **"List & Run"**.

---

### **4️⃣ Tab "Bulk Reconcile"** — Comparar Local vs Fabric

**Quando usar:** Você quer saber o que falta/sobra entre o local e o Fabric.

**Passo a passo:**
1. Insira o **Workspace** (opcional — deixe em branco para offline)
2. Deixe o padrão **"Diretório de Definições"** = `copyjob_definitions/bulk`
3. Clique em **"🔍 Executar Reconcile"**

**Resultado:** Três listas:
- **Faltando no Fabric** — definições locais não aplicadas
- **Órfãs no Fabric** — Copy Jobs que existem no Fabric mas não têm definição local (nunca deletados automaticamente)
- **Duplicatas** — avisos sobre possíveis conflitos

---

## 🔐 Gating (Segurança)

| Permissão | Impacto |
|---|---|
| **`permission_scope = read_only`** | ❌ Run e Apply bloqueados → mensagem "Escopo read_only: execução bloqueada" |
| **`allow_write = false`** | ❌ Apply bloqueado → mensagem "allow_write desabilitado no profile" |
| **Checkbox `--confirm-execute`** | ❌ Run bloqueado sem marcar |
| **Checkbox `--confirm-write`** | ❌ Apply bloqueado sem marcar |

**Equivalência com CLI:**
- `streamlit run .\execute.py` (tab "List & Run" + Run) ≈ `dlctl copyjobs run --workspace X --name Y --confirm-execute`
- `streamlit run .\execute.py` (tab "Bulk Apply") ≈ `dlctl copyjobs bulk apply --plan plan.json --confirm-write`

---

## 📁 Arquivo de Estrutura

```
copyjob_definitions/
├── example_copyjob-content.json        # Definição exemplo
├── example_oracle_schema_export.json   # Schema exemplo
└── bulk/
    ├── cpj_ap_invoices_1.copyjob.yaml
    ├── cpj_ap_invoices_2.copyjob.yaml
    └── cpj_ap_invoices_all.copyjob.yaml
```

**Formato `.copyjob.yaml`:**
```yaml
display_name: cpj_ap_invoices_1
folder_path: copyjobs/SUPRIMENTOS      # pasta no Fabric
definition_file: ../example_copyjob-content.json  # ref. ao content.json
source_signature: "ORACLE:AP_INVOICES_ALL->LAKEHOUSE:..."
job_mode: Batch  # ou CDC (Change Data Capture)
```

---

## ❌ Erros Comuns

| Erro | Causa | Solução |
|---|---|---|
| "Diretório não encontrado" | Caminho relativo errado | Verifique `copyjob_definitions/bulk` existe |
| "Não foi possível conectar ao Fabric" | Credenciais vencidas ou inválidas | Execute `az login` no terminal ou vá em Configuração |
| "Escopo read_only: execução bloqueada" | Permission scope é `read_only` | Altere em Configuração → Microsoft Fabric → permission_scope |
| "allow_write desabilitado" | Profile tem `allow_write: false` | Altere em Configuração → Ambiente & Escrita |
| "JSON inválido no plan" | Paste malformado | Copie o JSON completo do resultado do Plan anterior |

---

## 💡 Dicas

1. **Sempre teste offline primeiro:** Deixe Workspace vazio na aba Plan/Reconcile para rodá-lo 100% local.
2. **Plan é imutável:** Uma vez gerado, o plan fica "congelado". Se mudar definições locais, ride Plan novamente.
3. **Nunca crie duplicatas:** O reconcile avisa sobre nomes com sufixo `_1, _2, _3` ou assinaturas iguais origem→destino.
4. **Órfãs não são deletadas:** Copy Jobs criados manualmente no Fabric (sem `*.copyjob.yaml` local) continuam lá após Apply. Use o Reconcile para achá-los.
5. **Audit antes de Apply:** Use Bulk Plan como "dry-run". Se houver problema, corrija local e rode Plan de novo.

---

## 📞 Equivalência CLI ↔ GUI

| Ação | CLI | GUI |
|---|---|---|
| Listar Copy Jobs | `dlctl copyjobs list --workspace X` | List & Run → "Buscar Copy Jobs" |
| Executar um Copy Job | `dlctl copyjobs run --workspace X --name Y --confirm-execute` | List & Run → seleciona + Run |
| Planejar bulk | `dlctl copyjobs bulk plan --definitions-dir X` | Bulk Plan → "Executar Plan" |
| Validar (dry-run) | `dlctl copyjobs bulk dry-run --plan X` | (implícito em Bulk Apply) |
| Aplicar bulk | `dlctl copyjobs bulk apply --plan X --confirm-write` | Bulk Apply → cola JSON + Apply |
| Reconciliar | `dlctl copyjobs bulk reconcile --definitions-dir X` | Bulk Reconcile → "Executar Reconcile" |
