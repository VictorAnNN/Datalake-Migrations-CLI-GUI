# 🎨 Tooltips na Prática — Screenshots Textuais

## Como os Tooltips Aparecem na Página Copy Jobs

---

## 1️⃣ **Sidebar — Avisos Detalhados**

```
┌────────────────────────────────────────────────────┐
│          🛰️ Constellation Migration Control        │
├────────────────────────────────────────────────────┤
│                                                    │
│  Profile: ms_client_constellation                 │
│                                                    │
│  Auth: az_cli                                      │
│  Escopo: read_only                                │
│  Tenant: 123abc...                                │
│  allow_write: false                               │
│                                                    │
│  ┌──────────────────────────────────────────┐    │
│  │ 🔒 ESCOPO READ_ONLY: Ações Bloqueadas  │    │
│  │                                          │    │
│  │ Você tem permissão para:                 │    │
│  │ • Listar Copy Jobs                       │    │
│  │ • Planejar (Bulk Plan)                   │    │
│  │ • Reconciliar                            │    │
│  │                                          │    │
│  │ BLOQUEADO:                               │    │
│  │ ✗ Executar (Run) — sem permissão         │    │
│  │ ✗ Aplicar (Apply) — sem permissão        │    │
│  │                                          │    │
│  │ Para mudar: Configuração → Microsoft     │    │
│  │ Fabric → permission_scope = contributor  │    │
│  └──────────────────────────────────────────┘    │
│                                                    │
│  ┌──────────────────────────────────────────┐    │
│  │ ⛔ ALLOW_WRITE DESABILITADO              │    │
│  │                                          │    │
│  │ Operações de escrita (Apply) estão      │    │
│  │ bloqueadas neste profile.                │    │
│  │                                          │    │
│  │ Para ativar:                             │    │
│  │ Configuração → Ambiente & Escrita        │    │
│  │ → allow_write = ON                       │    │
│  └──────────────────────────────────────────┘    │
│                                                    │
└────────────────────────────────────────────────────┘
```

---

## 2️⃣ **Tab "List & Run" — Inputs com Tooltips**

```
┌─────────────────────────────────────────────────────┐
│ 📋 Copy Jobs — Gerenciamento ao Vivo               │
├─────────────────────────────────────────────────────┤
│                                                     │
│  1. List & Run    2. Plan    3. Apply    4. Recon  │
│                                                     │
│  Workspace  ❓                                       │
│  ┌─────────────────────────────┐                  │
│  │ [ex: default-workspace    ] │ 🌐 Nome do      │
│  └─────────────────────────────┘    workspace    │
│       ▲ Tooltip ao passar mouse      Fabric onde │
│       └─────────────────────────────── Copy Jobs │
│                                       existem    │
│                                                     │
│  ┌──────────────┐  ┌────────────────────────────┐  │
│  │ Buscar Copy  │  │ Conecta ao Fabric e lista  │  │
│  │ Jobs      ❓  │  │ todos os Copy Jobs...      │  │
│  └──────────────┘  └────────────────────────────┘  │
│       ▲ Tooltip         [Tooltip ao hover]        │
│       └──────────────────────────────────────────┘  │
│                                                     │
│  ✓ cpj_ap_invoices_1  (ID: abc-123-xyz)           │
│  ✓ cpj_ap_invoices_2  (ID: def-456-uvw)           │
│  ✓ cpj_ap_invoices_all (ID: ghi-789-rst)          │
│                                                     │
│  ☑ Confirmo execução (--confirm-execute)  ❓       │
│     └─ Tooltip: "☑️ Obrigatório: marca para..."   │
│                                                     │
│  ┌──────────────────┐                             │
│  │ 🚀 Executar Copy │  Desabilitado até marcar ❓ │
│  │ Job           ❓  │  Tooltip: "Dispara no      │
│  └──────────────────┘  Fabric. ⚠️ Desabilitado..." │
│       ▲                                             │
│       └─ Fica cinza até confirmar                 │
│                                                     │
└─────────────────────────────────────────────────────┘
```

---

## 3️⃣ **Tab "Bulk Plan" — Tooltips Informativos**

```
┌─────────────────────────────────────────────────────┐
│                    2. Bulk Plan                      │
├─────────────────────────────────────────────────────┤
│                                                     │
│  Workspace  ❓                                       │
│  ┌─────────────────────────────┐                  │
│  │ [deixe vazio ou preencha   ] │ 🌐 Nome do     │
│  └─────────────────────────────┘    workspace.    │
│                                      Se deixar    │
│  Tooltip ao hover:                   vazio,       │
│  "🌐 Nome do workspace Fabric.      roda         │
│   Se deixar em branco, o plano      100% offline │
│   roda 100% offline (local-only),   (local-only) │
│   mostrando tudo como 'create'.     ..."         │
│   Útil para validação..."                        │
│                                                     │
│  Diretório de Definições  ❓                        │
│  ┌─────────────────────────────┐                  │
│  │ copyjob_definitions/bulk    │ 📁 Caminho      │
│  └─────────────────────────────┘    relativo.    │
│                                      Padrão:      │
│  Tooltip: "📁 Caminho relativo      'copyjob...  │
│   contendo *.copyjob.yaml..."                     │
│                                                     │
│  Ações:                                            │
│  ┌──────────────────┐                             │
│  │ 📊 Executar Plan │  ❓ Tooltip:               │
│  └──────────────────┘  "Compara definições        │
│                         locais vs. Fabric.         │
│  Ao passar mouse:       Mostra o que vai ser       │
│  "Compara definições    criado (🟢), atualizado   │
│   locais vs. Fabric.    (🟡), ignorado (⚪),      │
│   Mostra o que vai      ou bloqueado (🔴)"       │
│   ser criado..."                                  │
│                                                     │
│  ✅ Plan concluído: 3 entrada(s)                   │
│                                                     │
│  🟢 cpj_ap_invoices_1 — create                    │
│  🟡 cpj_ap_invoices_2 — update                    │
│  ⚪ cpj_ap_invoices_all — noop                    │
│                                                     │
└─────────────────────────────────────────────────────┘
```

---

## 4️⃣ **Tab "Bulk Apply" — Bloqueio com Contexto**

```
┌─────────────────────────────────────────────────────┐
│                   3. Bulk Apply                      │
├─────────────────────────────────────────────────────┤
│                                                     │
│  [Se read_only ou allow_write=false]               │
│                                                     │
│  ┌──────────────────────────────────────────────┐  │
│  │ 🔒 ESCOPO READ_ONLY: APLICAÇÃO BLOQUEADA    │  │
│  │                                              │  │
│  │ Seu nível de permissão não permite          │  │
│  │ criar/atualizar Copy Jobs no Fabric.        │  │
│  │                                              │  │
│  │ Para resolver, altere em:                   │  │
│  │ ► Configuração                              │  │
│  │   ► Microsoft Fabric                        │  │
│  │     ► permission_scope = "contributor"      │  │
│  │                                              │  │
│  │ ⚠️ Apenas administradores têm acesso!       │  │
│  └──────────────────────────────────────────────┘  │
│                                                     │
│  [Se permission OK, mostra:]                       │
│                                                     │
│  Cole o JSON do plan  ❓                            │
│  ┌──────────────────────────────────────────────┐  │
│  │ {"definitions_dir": "...",                   │  │
│  │  "entries": [{...}, {...}],                  │  │
│  │  "plan_hash": "abc123..."}                   │  │
│  └──────────────────────────────────────────────┘  │
│                                                     │
│  Tooltip ao hover: "📋 Cole o JSON completo       │
│  que foi exibido após rodar 'Bulk Plan'.           │
│  Este JSON é 'congelado' — se você mudar          │
│  definições locais, precisa rodar Plan novamente"  │
│                                                     │
│  Confirmações:                                      │
│                                                     │
│  ☑ Confirmo escrita (--confirm-write)  ❓          │
│    Tooltip: "☑️ Obrigatório: autoriza            │
│             criação/atualização de Copy Jobs.     │
│             Sem isto, botão fica desabilitado."   │
│                                                     │
│  ☑ Confirmo produção (--confirm-production) ❓    │
│    Tooltip: "☑️ Adicional: se workspace for       │
│             PRD, VOCÊ DEVE marcar isto.           │
│             Se DEV/HML, é opcional."              │
│                                                     │
│  ┌──────────────────┐                             │
│  │ ✅ Aplicar Plan  │  ❓ Desabilitado até:      │
│  └──────────────────┘  marcar confirmações      │
│                        e colar JSON             │
│  Tooltip: "Cria/atualiza Copy Jobs no Fabric.     │
│  ⚠️ Desabilitado até você marcar                  │
│  '--confirm-write' e colar o JSON."              │
│                                                     │
└─────────────────────────────────────────────────────┘
```

---

## 5️⃣ **Tab "Bulk Reconcile" — Tooltips de Busca**

```
┌─────────────────────────────────────────────────────┐
│                4. Bulk Reconcile                     │
├─────────────────────────────────────────────────────┤
│                                                     │
│  Workspace  ❓                                       │
│  Tooltip: "🌐 Nome do workspace no Fabric.        │
│            Deixe em branco para rodar offline."   │
│                                                     │
│  Diretório de Definições  ❓                        │
│  Tooltip: "📁 Caminho relativo contendo           │
│            *.copyjob.yaml."                       │
│                                                     │
│  ┌──────────────────────┐                         │
│  │ 🔍 Executar Reconcile │  ❓ Tooltip:           │
│  └──────────────────────┘  "Compara: o que        │
│                             existe localmente      │
│  Tooltip: "Compara:         mas não no Fabric      │
│  • Missing: local mas não   (missing), o que      │
│    no Fabric               existe no Fabric       │
│  • Orphaned: Fabric mas    mas não localmente    │
│    não local               (orphaned), e          │
│  • Duplicates: conflitos"   duplicatas"          │
│                                                     │
│  ✅ Reconciliação Concluída                        │
│                                                     │
│  📊 Local Count: 3                                 │
│  🌐 Live Comparado: Sim                            │
│  ⚠️ Duplicatas: 0                                  │
│                                                     │
│  ⚠️ Faltando no Fabric (1):                        │
│    - cpj_nova_cria                               │
│                                                     │
│  ℹ️ Órfãs no Fabric (1):                           │
│    (nunca deletadas automaticamente)              │
│    - cpj_antiga_manual                           │
│                                                     │
└─────────────────────────────────────────────────────┘
```

---

## 🎯 Interação com Tooltips

### **Mouse Hover (Desktop)**
```
Quando você passa o mouse sobre um ícone ❓:

1. O ícone fica destacado
2. Após ~500ms, um tooltip aparecer com texto branco em fundo cinzento
3. O tooltip desaparece quando você tira o mouse

Workspace  ❓    ← Passe o mouse aqui
          ▼
        ┌──────────────────────────────────┐
        │ 🌐 Nome do workspace Fabric...  │
        │                                  │
        │ Ex: 'default-workspace',         │
        │ 'SUPRIMENTOS', etc.              │
        └──────────────────────────────────┘
```

### **Mensagens de Erro (Bloqueio)**
```
Quando você tenta uma ação bloqueada:

┌─────────────────────────────────────────┐
│ 🔒 ESCOPO READ_ONLY: EXECUÇÃO BLOQUEADA │  ← Caixa vermelha
│                                         │
│ Seu nível não permite...                │  ← Contexto completo
│                                         │
│ Altere em: Configuração → ...           │  ← Breadcrumb
│                                         │
│ ⚠️ Apenas admin pode fazer isto         │  ← Aviso
└─────────────────────────────────────────┘
```

---

## 💡 Dicas de Uso

1. **Procure pelo ícone ❓** — se tem, passe o mouse!
2. **Leia antes de agir** — o tooltip explica o impacto
3. **Mensagens vermelhas** — leia com atenção (bloqueio)
4. **Mensagens amarelas** — avisos no sidebar sobre seu perfil
5. **Breadcrumbs** — seguem o caminho exato onde mudar

---

## 📊 Estatísticas de Tooltips

| Local | Qtd | Tipo |
|---|---|---|
| Sidebar | 2 | Warning (bloqueios) |
| List & Run | 4 | Input + Checkbox + Botão |
| Bulk Plan | 4 | Input + Botão + Info |
| Bulk Apply | 5 | Input + Checkboxes + Botão + Errors |
| Bulk Reconcile | 3 | Input + Botão |
| **Total** | **18+** | **Distribuídos** |

---

## ✨ Benefícios Realizados

✅ Usuário sabe **por quê** algo está bloqueado  
✅ Usuário sabe **exatamente onde** mudar (breadcrumb)  
✅ Usuário sabe **o que fazer** sem perguntar  
✅ Tooltips são **não-intrusivos** (só aparecem no hover)  
✅ Mensagens são **claras e específicas** (não genéricas)  
✅ Interface é **autoexplicativa** (menos documentação)
