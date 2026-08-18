# Rastreamento de Tooltips no Dashboard

## Status Geral
- **4_CopyJobs.py**: ✅ Completo (18+ tooltips)
- **1_Configuracao.py**: ⏳ Em progresso
- **2_Acoes.py**: ⏳ Pendente
- **3_Diagnosticos_Avancados.py**: ⏳ Pendente  
- **4_Retro_Melhoria_Continua.py**: ⏳ Pendente
- **app.py**: ⏳ Pendente

## 1_Configuracao.py

### Aba: Microsoft Fabric
- [ ] Line 39-44: `st.text_input("Profile")` - **DONE**
- [ ] Line 88-92: `st.text_input("Tenant para Login")` - **DONE**
- [ ] Line 109-112: `st.text_input("Workspace Name")` - **DONE**
- [ ] Line 114-117: `st.text_input("Workspace ID")` - **DONE**
- [ ] Line 119-122: `st.text_input("Tenant ID")` - **DONE**
- [ ] Line 128-135: `st.selectbox("Permission Scope")` - **DONE**
- [ ] Line 148-151: `st.form_submit_button("Salvar")` - **DONE**

### Aba: Oracle Fusion
- [ ] Database inputs (DSN, user, password)
- [ ] BIP inputs (base_url, user, password)
- [ ] Submit button

### Aba: Ambiente & Escrita
- [ ] Environment selectbox
- [ ] allow_write checkbox
- [ ] allow_production checkbox
- [ ] Submit button

### Aba: Domínios
- [ ] Domain inputs
- [ ] Add/delete buttons

### Aba: Testar Conexões
- [ ] Test buttons for different connections

## 2_Acoes.py

### Sidebar
- [ ] Profile text_input (line 40)
- [ ] Domain selectbox (line 58)

### Main Actions
- [ ] Rodar inventário Silver button
- [ ] Gerar notebooks Silver confirmations
- [ ] Gerar notebooks Gold confirmations
- [ ] Rodar execução button
- [ ] Pipeline router button

Total widgets: ~25

## 3_Diagnosticos_Avancados.py

- [ ] All diagnostic inputs and buttons
Total widgets: ~30

## 4_Retro_Melhoria_Continua.py

- [ ] All retro inputs and buttons
Total widgets: ~20

## app.py (Home page)

- [ ] Navigation help
- [ ] Main controls
Total widgets: ~10

---

## Estratégia de Implementação

1. **Fase 1 (COMPLETA)**: 4_CopyJobs.py com 18+ tooltips ✅
2. **Fase 2 (PRÓXIMA)**: Adicionar tooltips manuais em:
   - 1_Configuracao.py (faltam tabs Oracle, Ambiente, Domínios, Teste)
   - app.py (home page)
3. **Fase 3**: 2_Acoes.py
4. **Fase 4**: 3_Diagnosticos_Avancados.py
5. **Fase 5**: 4_Retro_Melhoria_Continua.py

## Padrão de Tooltip

Todos os tooltips seguem:
```python
help="🎯 Emoji + descrição clara (50-100 caracteres)"
```

Emojis padrão:
- 📄 Arquivo/nome
- 🆔 ID/identificador
- 🌐 Workspace/conexão
- 🏢 Tenant/empresa
- 📁 Diretório/path
- 📋 Ação/operação
- 💾 Salvar/confirmar
- 🔒 Bloqueado/permissão
- ✅ Confirmed/check
- ⚠️ Warning/aviso
- ▶️ Executar/play
- 🔍 Buscar/verificar
- 🚀 Deploy/produção
