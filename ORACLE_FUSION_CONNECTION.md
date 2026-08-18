# 🔗 Como Funciona a Conexão Oracle Fusion Atualmente

## 📊 Arquitetura de Conexão

O projeto usa **duas formas de conexão** com Oracle Fusion:

### 1️⃣ **Conexão Banco de Dados (OracleDbConnector)**
```
Você (CLI/GUI) 
    ↓
    OracleDbConnector (python-oracledb thin mode)
    ↓
    Oracle Fusion Database (via DSN/user/password)
```

**Configuração necessária (.env):**
```env
ORACLE_DB_DSN=oracle_host:1521/fusion_service
ORACLE_DB_USER=seu_usuario
ORACLE_DB_PASSWORD=sua_senha
```

**O que faz:**
- ✅ Conecta direto ao banco Oracle Fusion via TCP
- ✅ Executa queries de LEITURA (`SELECT`)
- ✅ Usado para validações/amostras durante desenvolvimento
- ✅ Não precisa de Oracle Client instalado (thin mode)

**Onde é usado:**
- `dlctl auth oracle-doctor` — Testa a conexão
- GUI → Configuração → Testar Conexões → "Testar Oracle DB"
- Potencial para queries de mapping/inventário

### 2️⃣ **Conexão BI Publisher (OracleBipConnector)**
```
Você (CLI/GUI)
    ↓
    OracleBipConnector (zeep SOAP client)
    ↓
    Oracle BI Publisher WSDL Service
    ↓
    Relatórios Fusion (CSV, PDF, etc)
```

**Configuração necessária (.env):**
```env
ORACLE_BIP_BASE_URL=https://seu_fusion_instance.oracle.com/xmlpserver
ORACLE_BIP_USER=seu_usuario_bip
ORACLE_BIP_PASSWORD=sua_senha_bip
```

**O que faz:**
- ✅ Conecta ao serviço SOAP do BI Publisher
- ✅ Executa relatórios pré-criados no Fusion
- ✅ Retorna dados em CSV, PDF, Excel, etc
- ✅ Usado para ingestão em massa (Bronze landing)

**Onde é usado:**
- Potencial para `nb_bipublisher_fusion` (notebooks genéricos)
- Ingestão de dados tabulares via relatórios

---

## 🔧 Arquivo Central: `oracle_connector.py`

**Localização:** `src/dlctl/connectors/oracle_connector.py`

### Classe 1: `OracleDbConnector`

```python
from dlctl.connectors.oracle_connector import OracleDbConnector
from dlctl.config import load_profile

# Carregar profile
profile = load_profile("ms_client_constellation")

# Criar conector
try:
    db_conn = OracleDbConnector(profile)
    
    # Testar conexão
    result = db_conn.test_connection()
    print(result)  # {"status": "ok", "server_time": "2025-01-15 10:30:00"}
    
    # Executar query de leitura
    rows = db_conn.fetch(
        "SELECT * FROM po_headers WHERE org_id = :org_id",
        {"org_id": 1},
        limit=100
    )
    for row in rows:
        print(row)  # {"PO_HEADER_ID": 123, "VENDOR_ID": 456, ...}
        
except OracleConnectorError as e:
    print(f"Erro: {e}")
    # Mensagens esperadas:
    # - "ORACLE_DB_DSN/USER/PASSWORD não configurados no .env"
    # - "Pacote 'oracledb' não instalado. Rode: pip install dlctl[oracle]"
```

### Classe 2: `OracleBipConnector`

```python
from dlctl.connectors.oracle_connector import OracleBipConnector
from dlctl.config import load_profile

# Carregar profile
profile = load_profile("ms_client_constellation")

try:
    bip_conn = OracleBipConnector(profile)
    
    # Testar conexão
    result = bip_conn.test_connection()
    print(result)  # {"status": "ok", "wsdl_operations": [list de operações]}
    
    # Executar relatório
    report_bytes = bip_conn.run_report(
        report_absolute_path="/Fusion Reports/PurchasingOrders",
        parameters={"P_ORG_ID": "1", "P_STATUS": "OPEN"},
        output_format="CSV"
    )
    
    # Salvar em disco
    with open("po_report.csv", "wb") as f:
        f.write(report_bytes)
        
except OracleConnectorError as e:
    print(f"Erro: {e}")
    # Mensagens esperadas:
    # - "ORACLE_BIP_BASE_URL/USER/PASSWORD não configurados no .env"
    # - "Pacote 'zeep' não instalado. Rode: pip install dlctl[oracle]"
```

---

## 🎯 Dependências Opcionais

As bibliotecas Oracle são **opcionais** e só precisam ser instaladas se usar Oracle:

```bash
# Instalar ambas as dependências Oracle
pip install dlctl[oracle]

# Ou instalar separadamente:
pip install oracledb  # para banco de dados
pip install zeep      # para BI Publisher SOAP
```

Se não estiverem instaladas, o CLI retorna um erro legível pedindo instalação.

---

## 🌐 Integração com o Código Existente

### No CLI

**Comando:** `dlctl auth oracle-doctor`

```python
# src/dlctl/commands/auth_cmds.py (linhas 52-64)
@app.command("oracle-doctor")
def oracle_doctor(profile: str = typer.Option(None, "--profile")):
    """Testa a conexão com o banco Oracle configurado no profile."""
    from dlctl.connectors.oracle_connector import OracleConnectorError, OracleDbConnector

    p = get_profile(profile)
    try:
        conn = OracleDbConnector(p)
        result = conn.test_connection()
        console.print(f"[green]OK[/green]: {result}")
    except OracleConnectorError as exc:
        console.print(f"[yellow]manual_required[/yellow]: {exc}")
        raise typer.Exit(code=1)
```

**Como usar:**
```bash
# Terminal
dlctl auth oracle-doctor --profile ms_client_constellation
```

### No GUI

**Página:** Configuração → Aba "Testar Conexões"

```python
# src/dlctl/dashboard/pages/1_Configuracao.py (linhas 323-332)
if st.button("Testar Oracle DB", type="primary", help="🧪 Valida conexão Oracle"):
    try:
        from dlctl.connectors.oracle_connector import OracleDbConnector
        p = load_profile(profile_name)
        conn = OracleDbConnector(p)
        result = conn.test_connection()
        st.success(f"OK: {result}")
    except Exception as exc:
        st.error(f"Falha (ou manual_required): {exc}")
```

**Como usar:**
1. Ir para **Configuracao**
2. Preencher dados Oracle (aba Oracle Fusion):
   - ORACLE_DB_DSN
   - ORACLE_DB_USER
   - ORACLE_DB_PASSWORD
   - ORACLE_BIP_BASE_URL
   - ORACLE_BIP_USER
   - ORACLE_BIP_PASSWORD
3. Clicar **"Testar Oracle DB"** button na aba "Testar Conexões"
4. Ver resultado (OK ou erro)

---

## 📋 Variáveis de Ambiente Necessárias

### Para Conexão Banco (Obrigatório se usar `OracleDbConnector`)

| Variável | Exemplo | Descrição |
|----------|---------|-----------|
| `ORACLE_DB_DSN` | `fusion.company.com:1521/FUSION` | Host:port/service_name |
| `ORACLE_DB_USER` | `apps` | Usuário do banco |
| `ORACLE_DB_PASSWORD` | `***` | Senha (armazenada segura) |

### Para BI Publisher (Obrigatório se usar `OracleBipConnector`)

| Variável | Exemplo | Descrição |
|----------|---------|-----------|
| `ORACLE_BIP_BASE_URL` | `https://fusion.company.com/xmlpserver` | URL base do BI Publisher |
| `ORACLE_BIP_USER` | `bip_user` | Usuário BIP |
| `ORACLE_BIP_PASSWORD` | `***` | Senha BIP (armazenada segura) |

### Armazenamento

As senhas são salvas em `.env` no **root do projeto**:
```
Datalake-Migrations-CLI-GUI/
├── .env ← aqui (senhas guardadas aqui)
├── .gitignore (ignora .env automaticamente)
├── src/
│   └── dlctl/
│       ├── config.py (lê do .env)
│       └── connectors/
│           └── oracle_connector.py
```

---

## ⚙️ Como Funciona Internamente

### Thin Mode (Sem Oracle Client)

```python
# oracle_connector.py linha 40
import oracledb
conn = oracledb.connect(
    user=self.oracle_cfg.user,
    password=self.oracle_cfg.password,
    dsn=self.oracle_cfg.dsn,
)
# Thin mode: conecta direto via TCP, sem precisar de biblioteca cliente Oracle
```

**Vantagem:** Não precisa instalar Oracle Client pesado (300 MB+)

### SOAP Client (BI Publisher)

```python
# oracle_connector.py linhas 86-100
from zeep import Client
from requests.auth import HTTPBasicAuth
from zeep.transports import Transport

session.auth = HTTPBasicAuth(user, password)
client = Client(wsdl=url, transport=Transport(session=session))

# Executa WSDL operations
response = client.service.runReport(reportRequest=...)
```

**Como funciona:**
1. Zeep baixa WSDL do servidor
2. Autentica com HTTP Basic Auth
3. Chama operações SOAP remotas
4. Retorna resposta estruturada

---

## 🚨 Possíveis Erros e Soluções

| Erro | Causa | Solução |
|------|-------|--------|
| `ORACLE_DB_DSN/USER/PASSWORD não configurados` | Variáveis .env faltando | Preencher em Configuracao → Oracle Fusion |
| `Pacote 'oracledb' não instalado` | Dependência faltando | `pip install dlctl[oracle]` |
| `ORA-12514: TNS:listener does not know of service` | DSN/service_name inválido | Verificar conexão SQL*Plus: `sqlplus user@dsn` |
| `ORA-01017: invalid username/password` | Credenciais erradas | Testar com SQL Developer ou SQL*Plus |
| `Connection refused` | Firewall/rede bloqueada | Verificar conectividade: `telnet host port` |
| `WSDL parsing failed` | BI Publisher indisponível | Verificar URL ORACLE_BIP_BASE_URL |
| `HTTPBasicAuth failed (401)` | Credenciais BIP erradas | Verificar ORACLE_BIP_USER/PASSWORD |

---

## 📈 Potencial de Expansão

### Hoje (Status Quo)

```
✅ Test Connection (CLI e GUI)
✅ Simple SELECT queries
✅ BI Publisher WSDL discovery
```

### Futuro (Possibilidades)

```
🔄 Inventário automático de tabelas Fusion
🔄 Descoberta automática de relatórios BI Publisher
🔄 Mapping automático: Fusion tables → Bronze naming
🔄 Integração com pipeline de ingestão em massa
🔄 Auditoria de queries executadas
🔄 Cache de resultados de queries
🔄 Suporte para PL/SQL procedures
🔄 Exportação automática de metadados
```

---

## 🔐 Segurança

### Princípios Implementados

1. **Senhas não aparecem em logs**
   ```python
   # Nunca:
   console.print(f"Password: {password}")  # ❌ NUNCA
   
   # Sempre usar placeholders
   console.print(f"DSN: {self.oracle_cfg.dsn}")  # ✅ OK
   ```

2. **Senhas armazenadas com cuidado**
   - `.env` está no `.gitignore`
   - Nunca commitar credenciais
   - Usar variáveis de ambiente em CI/CD

3. **Timeout em conexões**
   ```python
   conn = oracledb.connect(..., timeout=15)  # Evita hang infinito
   ```

4. **Validação de entrada**
   - Queries usam placeholders (previne SQL injection)
   - WSDL URL validada antes de conectar

---

## 📞 Próximas Ações Recomendadas

### Se quer testar agora:
1. Instale: `pip install dlctl[oracle]`
2. Preencha `.env` com credenciais Fusion
3. No GUI: **Configuracao** → **Testar Conexões** → "Testar Oracle DB"
4. No CLI: `dlctl auth oracle-doctor`

### Se quer expandir:
1. Criar command `dlctl oracle list-tables` (inventário)
2. Criar command `dlctl oracle run-report` (BI Publisher)
3. Integrar com `nb_bipublisher_fusion` (já mencionado em validators.py)

### Se quer diagnosticar problemas:
1. Testar conectividade: `telnet fusion.company.com 1521`
2. Testar credenciais: `sqlplus user/pass@dsn`
3. Testar BI Publisher: `curl -u user:pass https://fusion.../xmlpserver/`
4. Ver logs: `dlctl auth oracle-doctor` (verbose)

---

**Última atualização**: 2026-08-18
**Status**: ✅ Funcional, Testável via GUI e CLI
