# dlctl — CLI Unificado de Migração Constellation (Bronze → Silver → Gold → Fabric)

CLI Python autocontido + dashboard Streamlit que implementa, de forma real e
localmente executável, o workflow descrito no conjunto de skills
`constellation-order-tracking-etl` / `etl-oracle-fabric` /
`etl-oracle-fabric-gold` / `fabric-full-agent`:

```
inventário → reconciliação de escopo → geração de notebook → validação local
    → manifest validate/plan/dry-run/apply --confirm-write → execute --confirm-execute
```

Tudo em um único CLI (`dlctl`), com conectores reais para **Oracle** (banco +
BI Publisher) e **Microsoft Fabric REST API** (auth padrão via **Azure CLI**
— `az login`, sem precisar de App Registration própria; MSAL device_code/
client_credentials continuam disponíveis como alternativa), gates de
segurança centralizados, e um painel de controle Streamlit que mostra
passos, sucessos, mapeamentos e evidências — incluindo a feature de
**Linhagem do Lakehouse** (grafo isolado por tabela/fonte, artefatos
Linhagem Tabelas/Tabelas e trilha de dependências até o SharePoint).

> **Importante sobre este projeto**: ele foi construído sem acesso ao tenant
> Fabric real do cliente nem às ferramentas internas (`fabric-fullctl`,
> `accountctl`) citadas nas skills originais. Os conectores Oracle/Fabric
> aqui são **implementações reais** (chamadas HTTP/SQL de verdade), mas
> precisam das suas credenciais em `.env` para funcionar contra o tenant real.
> Sem credenciais configuradas, os comandos de escrita retornam
> `manual_required` de forma explícita — nunca simulam sucesso.

## 1. Arquitetura

```
config/profiles.yaml        -> perfis (tenant, workspace, allow_write) por ambiente
src/dlctl/
  config.py                 -> carregamento de profile + .env
  auth/fabric_auth.py       -> azure_cli (padrão) | MSAL device_code | client_credentials
  connectors/
    fabric_api.py           -> cliente REST Fabric (workspaces/items/lakehouses/
                                notebooks/pipelines/copyjobs/environments/git/
                                variable-libraries/sqlEndpoints), com retry
                                transiente, driver-log wait, diagnose-run e
                                nenhuma escrita sem gate
    fabric_notebook_sync.py -> sincroniza notebooks de um workspace (via auth
                                azure_cli) para input/lakehouse-dev, alimentando
                                a feature de Linhagem
    oracle_connector.py     -> Oracle DB (python-oracledb) + BI Publisher SOAP (zeep)
  core/
    gates.py                -> Central Write Gate + integração com leases
    secrets.py              -> redação de segredos em evidências/logs
    manifest.py             -> validate/plan/dry-run/apply/status (Canonical Write Workflow)
    mapping.py               -> registry Bronze/Silver/Gold + inventário + reconcile-scope
    state.py                -> SQLite (runs, steps, mappings, manifests, atividades,
                                ownership, leases, backlog, campanhas)
    pipeline.py             -> lógica pura do router (compartilhada CLI+dashboard)
    execution.py            -> lógica pura do Canonical Execution Workflow
    env_editor.py           -> leitura/escrita segura de .env e profiles.yaml
    copyjob_audit.py        -> auditoria semântica de mappings Copy Job (Oracle NUMBER)
    definitions_inspect.py  -> hash triad de definições (aggregate/encoded/decoded)
    log_classifier.py       -> classificador phase-aware de logs (NEVER_PASS por padrão)
    campaign.py             -> orquestrador multi-alvo `execute campaign` (DAG gated)
    retro.py                -> motor de "Improvement Proposals": analisa a telemetria
                                própria (ActivityLog/PipelineStep/CampaignStep/
                                CommandInvocation) e gera propostas categorizadas
    lineage_graph.py        -> grafo de linhagem (networkx) + "Mapa Isolado"
                                (upstream/downstream) reutilizado por CLI e dashboard
    project_scan.py         -> Supervisor: varre input/lakehouse-dev + input/Workspaces,
                                cruza com mappings/*.csv + config/project_targets.yaml e
                                calcula % Bronze/Silver/Gold/Dashboards/Views do projeto
  generators/
    silver_generator.py     -> gera notebooks Bronze->Silver (Notebook Contract)
    gold_generator.py       -> gera notebooks Silver->Gold (Gold Gates)
    validators.py           -> valida os gates acima (bloqueia geração inválida)
    lineage_generator.py    -> feature de Linhagem: parseia notebooks de
                                lakehouse-dev + JSONs do Fabric Scanner API,
                                gera Linhagem Tabelas/Tabelas (com expansão
                                transitiva) e a trilha de dependências SharePoint
  commands/                 -> um módulo Typer por área (skills + backlog + retro + lineage)
  dashboard/
    app.py                  -> painel principal (somente leitura do state)
    pages/1_Configuracao.py -> editar credenciais/conexões pelo front-end
    pages/2_Acoes.py        -> acionar todos os fluxos pelo front-end (gated)
    pages/3_Diagnosticos_Avancados.py -> backlog tracker + auditoria/leases/campaign/logs
    pages/4_Retro_Melhoria_Continua.py -> motor de retro + aprovação manual (Stage B)
    pages/5_Linhagem_Grafo.py -> Mapa Isolado (upstream/downstream) por tabela/fonte
    pages/6_Linhagem_Artefatos.py -> visualizador dos artefatos (Tabelas/Linhagem Tabelas)
    pages/7_Linhagem_SharePoint.py -> trilha dashboard->dataset->tabela->SharePoint,
                                       com validação de existência de cada elo
    pages/9_Supervisor.py    -> diagnóstico geral do projeto (Bronze/Silver/Gold/
                                Dashboards/Views) + botão "Salvar esta visão"
mappings/                   -> CSVs de mapeamento Bronze->Silver / Silver->Gold (exemplo)
manifests/                  -> manifests YAML (DataPipeline/Notebook/Environment/Campaign/...);
                                manifests/dashboard/ guarda os relatórios do Supervisor
fabric_definitions/         -> definitions JSON referenciadas pelos manifests
copyjob_definitions/        -> exemplos de copyjob-content.json + schema export Oracle
sql/, schema/               -> SQL legado adaptado e contratos de schema (.tab)
notebooks/silver, notebooks/gold -> notebooks .ipynb gerados
tests/                      -> pytest cobrindo gates, manifest engine, generators, mapping,
                                leases, copyjob audit, definitions inspect, log classifier, campaign
```

### Mapeamento skill → funcionalidade

| Skill original | Onde está implementado aqui |
|---|---|
| `constellation-order-tracking-etl` (router) | `dlctl pipeline run-order-tracking` |
| `etl-oracle-fabric` | `dlctl inventory silver`, `dlctl etl-silver generate\|generate-all\|validate` |
| `etl-oracle-fabric-gold` | `dlctl inventory gold`, `dlctl etl-gold generate\|validate\|reconcile-gold-scope` |
| `fabric-full-agent` (canonical write/execute) | `dlctl manifest validate\|plan\|dry-run\|apply\|status`, `dlctl execute plan\|dry-run\|apply` |
| `cli_command_surface.md` | `dlctl auth`, `dlctl environments`, `dlctl git`, `dlctl variable-libraries`, `dlctl copyjobs` |
| `datapipeline_manifest_patterns.md` | Schema de manifest em `core/manifest.py` + exemplos em `manifests/datapipeline/` |
| `constellation_fusion_pattern.md` | `connectors/oracle_connector.py::OracleBipConnector` (ingestão BIP genérica) |
| `environment_workflow.md` | `dlctl environments inspect\|export\|publish` |
| `git_workflow.md` | `dlctl git status\|diff-summary\|plan-commit\|commit\|update-from-git` |
| `variable_libraries_workflow.md` | `dlctl variable-libraries list\|definition\|create` |
| `copyjob_surface.md` | `dlctl copyjobs list\|run\|mappings-inspect\|oracle-number-audit` |

### Backlog incorporado (`fabric-fullctl-backlog.zip` — 3 incidentes reais)

Lacunas de CLI levantadas em diagnósticos/execuções ao vivo (não são skills
novas, são features que faltavam). Todas incorporadas como **funcionalidades
locais/offline**; onde a proposta original exige um Fabric client autenticado
ao vivo, o dlctl reporta `manual_required`/`skipped` de forma explícita — por
instrução do usuário, **nenhuma chamada real a Fabric/Oracle foi feita ou
testada durante o desenvolvimento desta feature**.

| Prioridade | Lacuna (origem) | Onde está no dlctl |
|---|---|---|
| P0 | Sem comando tipado p/ atividades de pipeline (Incid. 1) | `dlctl pipelines diagnose-run --run-export <json>` |
| P0 | `queryactivityruns` tratado como mutação (Incid. 1) | `fabric_api.py::query_activity_runs` (leitura tipada, não passa por authorize_write) |
| P0 | Sem auditor semântico de Copy Job / Oracle NUMBER (Incid. 1) | `dlctl copyjobs mappings-inspect` / `oracle-number-audit` |
| P0 | Sem lock entre agentes (Incid. 1) | `dlctl leases acquire\|list\|release` + integrado ao `GateContext.authorize_write` |
| P0 | Rota obsoleta de refresh do SQL endpoint (Incid. 2) | `fabric_api.py::refresh_sql_endpoint_metadata` (rota corrigida + `require_visible`) |
| P0 | Sem orquestrador multi-alvo (Incid. 2) | `dlctl execute campaign` + `core/campaign.py` (DAG serial, gated, isolamento de falha) |
| P0 | `driver-log` sem retry seguro (Incid. 2) | `dlctl jobs driver-log --wait` (retry só em 404 exato) |
| P0 | Classificador de logs não integrado (Incid. 2) | `dlctl jobs classify-log` + `core/log_classifier.py` (NEVER_PASS por padrão) |
| P1 | `git plan-commit` sem `--item-ids` (Incid. 1) | `dlctl git plan-commit --item-ids` |
| P1 | Git LRO `OperationHasNoResult` tratado como erro (Incid. 1) | `fabric_api.py::git_lro_result` |
| P2 | Hash de definição ambíguo (Incid. 1) | `dlctl definitions part-inspect` + `core/definitions_inspect.py` |
| Nota 3 | Sem `createdBy`/`modifiedBy` via API | `core/state.py::OwnershipRecord` (trilha auditável local) já cobre o caminho recomendado |

O rastreio completo (25 itens, P0/P1/P2, status, e o que já está coberto)
fica visível na aba **"📋 Backlog Tracker"** da página **Diagnósticos
Avançados** do dashboard.

### Motor de retro (`dlctl retro` — Improvement Proposals)

Além de incorporar o backlog de um relatório de retro específico, o dlctl
agora tem seu **próprio motor de retro**: ele analisa a telemetria que ele
mesmo gera (`ActivityLog`, `PipelineStep`, `CampaignStep`, `CommandInvocation`)
e produz um relatório "Improvement Proposals (retro)" no mesmo formato/
categorias usadas para analisar outras CLIs (msauthctl, teamsctl, fabricctl
etc.), mas aplicado ao próprio dlctl:

- **repeated-failure**: o mesmo comando/passo falha repetidamente com a
  mesma "forma" de erro (mensagem normalizada, IDs/números/aspas removidos).
- **throttling**: retries/429 concentrados em `fabric_api` (log automático a
  cada retry em `_request`).
- **gate-friction** (⚠ *nunca* uma proposta para enfraquecer o gate): recusas
  repetidas de um `authorize_*` — o gate está funcionando; a proposta é só
  tornar a precondição mais visível.
- **prefer-resolver**: lookups ao vivo de itens Fabric (`find_item_by_name`)
  repetidos quando existe `resolve_item_cached` (cache local, `dlctl inventory
  cache show|query`) — reforça o uso do cache-first.
- **skill-featured-unused**: comandos registrados no CLI (introspecção da
  árvore Typer/Click) nunca invocados na janela — candidatos a dieta.
- **permission-gap**: profile com `allow_write=false` e tentativas de
  escrita repetidas — decisão humana sobre habilitar ou não.

Toda invocação do `dlctl` é registrada automaticamente (callback raiz do
Typer em `cli.py`, sem precisar instrumentar cada comando manualmente) e toda
recusa de gate é logada com `level=BLOCKED` antes de levantar `SecurityError`
— isso alimenta os detectores acima sem esforço adicional.

```bash
dlctl retro analyze --window-days 90 --min-count 3
dlctl retro list --category gate-friction --status pending
dlctl retro approve --key gate-friction:gates.authorize_write:c55cb4a5b9
dlctl retro reject --key <chave>
dlctl retro report --out improvement_proposals_retro.md
```

O fluxo de aprovação é **sempre manual (Stage B)**: `retro analyze` só
persiste propostas; `approve`/`reject` só marcam status; nada é aplicado
automaticamente. Reanalisar nunca sobrescreve uma decisão humana já
registrada (só atualiza contagem/evidência). Veja a página **"🔁 Retro /
Melhoria Contínua"** do dashboard para o mesmo fluxo com botões.

## 2. Instalação (Windows, Linux e macOS)

Este projeto é 100% Python puro e roda igualmente em Windows, Linux ou macOS —
não depende de nenhuma ferramenta específica do Windows. Requer **Python 3.10+**.

### Windows (PowerShell)

```powershell
git clone <url-do-repositorio> "CLI Datalake"
cd "CLI Datalake"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[oracle,dashboard,dev]"
Copy-Item .env.example .env
notepad .env
```

### Linux / macOS (bash/zsh)

```bash
git clone <url-do-repositorio> cli-datalake
cd cli-datalake
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[oracle,dashboard,dev]"
cp .env.example .env
nano .env   # ou vim/code .env
```

> Em qualquer máquina nova, os passos são sempre os mesmos: **clonar → criar
> venv → ativar → `pip install -e ".[oracle,dashboard,dev]"` → configurar
> `.env`**. Nenhuma dependência externa de **Oracle Client** é necessária —
> `oracledb` roda em modo *thin* (sem Oracle Instant Client). A autenticação
> Fabric padrão (`FABRIC_AUTH_MODE=azure_cli`, já vem assim no
> `.env.example`) reaproveita o **Azure CLI** (`az login`), então instale-o
> (`winget install --exact --id Microsoft.AzureCLI` no Windows, ou o pacote
> `azure-cli` no Linux/macOS) se for usar esse modo — é o modo recomendado e
> usado pela maioria do time. Se preferir não instalar o Azure CLI, troque
> para `FABRIC_AUTH_MODE=device_code` ou `client_credentials` (MSAL puro,
> sem dependência externa).

Se o pacote `oracledb`/`zeep` (extra `oracle`) falhar ao instalar em alguma
máquina sem esses extras necessários, você ainda pode rodar tudo exceto os
comandos que tocam Oracle: `pip install -e ".[dashboard,dev]"`.

Depois de instalar, confirme que o CLI está no PATH do ambiente virtual ativo:

```bash
dlctl version
```

Se o comando `dlctl` não for reconhecido (raro, mas pode acontecer dependendo
do PATH do shell), use sempre a forma equivalente via módulo Python, que
funciona em qualquer SO:

```bash
python -m dlctl.cli version
```

Campos principais do `.env`:
- `FABRIC_AUTH_MODE=azure_cli` (**padrão/recomendado**, já vem assim no `.env.example`) — reaproveita a sessão aberta com `az login` (+ `az account set --subscription "..."`), sem precisar de App Registration/tenant/client secret. É a forma de conexão usada pela maioria do time e a mesma usada por `dlctl lineage sync-notebooks`.
- `FABRIC_TENANT_ID`, `FABRIC_CLIENT_ID` — só necessários se trocar para `FABRIC_AUTH_MODE=device_code` (login interativo no navegador) ou `client_credentials` + `FABRIC_CLIENT_SECRET` (automação sem interação, requer App Registration cadastrado no Entra ID).
- `FABRIC_WORKSPACE_NAME` / `FABRIC_WORKSPACE_ID`.
- `ORACLE_DB_DSN/USER/PASSWORD` e/ou `ORACLE_BIP_BASE_URL/USER/PASSWORD`.
- `FABRIC_SYNC_MAX_WORKERS` — paralelismo (1 a 8) da sincronização de notebooks (`dlctl lineage sync-notebooks`); comece com 4, reduza se a API retornar 429.
- `DLCTL_ALLOW_WRITE=true` **somente** quando você realmente quiser permitir escritas (ainda assim cada comando exige `--confirm-write`/`--confirm-execute` explícito).

> ✅ Com `FABRIC_AUTH_MODE=azure_cli`, basta instalar o Azure CLI e rodar `az
> login` uma vez — não precisa preencher `FABRIC_TENANT_ID`/`FABRIC_CLIENT_ID`.
> Os modos `device_code`/`client_credentials` continuam totalmente
> suportados como alternativa (ex.: automação sem usuário interativo).

> **Importante em multi-máquina**: `.env`, `config/profiles.yaml` e a pasta
> `state/` (que contém o banco SQLite `dlctl.db`, o cache de token MSAL e as
> evidências) são **locais a cada máquina/clone** — não são versionados
> (veja `.gitignore`). Cada pessoa/máquina que rodar o projeto precisa do seu
> próprio `.env` com suas credenciais. Se vários usuários precisarem ver o
> **mesmo** histórico de execuções/mapeamentos, rode o dashboard em uma única
> máquina compartilhada (servidor) e acesse-o remotamente — veja a seção 4.

## 2.1. Instalação via Docker (Windows ou Linux)

Alternativa ao passo a passo acima: o projeto inclui um `Dockerfile` e um
`docker-compose.yml` que rodam de forma idêntica em host Windows ou Linux —
o Docker sempre executa o container em Linux por baixo dos panos, então não
há diferença de comportamento entre hosts. Útil para não precisar instalar
Python/dependências localmente, ou para rodar o dashboard em um servidor
compartilhado pelo time.

```bash
cp .env.example .env            # Linux/macOS
Copy-Item .env.example .env     # Windows (PowerShell)
# edite o .env com suas credenciais/config (FABRIC_AUTH_MODE=azure_cli já é o padrão)

docker compose build
docker compose up -d
```

O dashboard fica disponível em `http://localhost:8501`.

Para autenticar com `FABRIC_AUTH_MODE=azure_cli` **dentro do container** (o
modo mais usado pelo time):

```bash
docker compose exec dlctl az login
```

A sessão fica persistida no volume nomeado `azure-cli-config`, então não
precisa logar de novo a cada `docker compose up`.

Rodar qualquer comando do CLI sem abrir o dashboard:

```bash
docker compose run --rm dlctl auth doctor
docker compose run --rm dlctl inventory silver
docker compose run --rm dlctl manifest validate --manifest manifests/lineage/algum_arquivo.yaml
```

As pastas `state/`, `input/`, `mappings/`, `manifests/`, `notebooks/`,
`config/`, `copyjob_definitions/`, `fabric_definitions/`, `schema/` e `sql/`
são montadas como volumes — o que o container gera/lê nessas pastas aparece
direto no diretório do projeto no host (e vice-versa).

```bash
docker compose down          # para os containers
docker compose down -v       # também apaga a sessão do az login salva
```

Veja a seção **4.5** do [HELPER.md](HELPER.md) para mais detalhes de uso.

## 3. Uso do CLI

```powershell
# Diagnóstico
dlctl auth profile-show
dlctl auth doctor
dlctl auth oracle-doctor

# Inventário Bronze->Silver / Silver->Gold
dlctl inventory silver --domain ORDER_TRACKING
dlctl inventory gold --domain ORDER_TRACKING
dlctl inventory reconcile-scope --layer bronze_to_silver --domain ORDER_TRACKING

# Geração e validação de notebooks
dlctl etl-silver generate --table SLV_PO_HEADERS --write
dlctl etl-silver validate notebooks/silver/SLV_PO_HEADERS.ipynb
dlctl etl-gold generate --table GLD_PR_REQUISITION --silver-base-path Tables/silver --gold-base-path Tables/gold --write
dlctl etl-gold validate notebooks/gold/GLD_PR_REQUISITION.ipynb

# Manifests (Canonical Write Workflow)
dlctl manifest validate --manifest manifests/datapipeline/pp_silver_order_tracking_2h.manifest.yaml
dlctl manifest plan --manifest manifests/datapipeline/pp_silver_order_tracking_2h.manifest.yaml
dlctl manifest dry-run --manifest manifests/datapipeline/pp_silver_order_tracking_2h.manifest.yaml
dlctl manifest apply --manifest manifests/datapipeline/pp_silver_order_tracking_2h.manifest.yaml --confirm-write

# Execução gated
dlctl execute plan --manifest execution_manifest.yaml
dlctl execute apply --manifest execution_manifest.yaml --confirm-execute

# Router de ponta a ponta (grava progresso no state para o dashboard)
dlctl pipeline run-order-tracking --domain ORDER_TRACKING --write

# ---- Novos comandos (backlog fabric-fullctl-backlog.zip) ----

# Leases: lock leve entre agentes/execuções
dlctl leases acquire --owner meu-agente --tables "AP_INVOICES_ALL" --ttl 3600
dlctl leases list
dlctl leases release --lease-id LEASE_ID --owner meu-agente

# Auditoria semântica de Copy Job (Oracle NUMBER sem precisão -> Decimal(256,130))
dlctl copyjobs mappings-inspect --definition copyjob_definitions/example_copyjob-content.json
dlctl copyjobs oracle-number-audit --definition copyjob_definitions/example_copyjob-content.json --schema-export copyjob_definitions/example_oracle_schema_export.json

# Diagnóstico de pipeline (offline, a partir de um export de queryactivityruns)
dlctl pipelines diagnose-run --run-export caminho/para/activity_runs_export.json --failed-only

# Inspeção de definição (hash triad: aggregate/encoded/decoded)
dlctl definitions part-inspect --file caminho/para/definition_payload.json

# Classificador de logs (assinatura desconhecida = NEVER_PASS por padrão)
dlctl jobs classify-log --file caminho/para/driver.log

# Execute campaign — orquestrador multi-alvo (DAG), 100% gated
dlctl execute campaign --manifest manifests/campaign/gold_order_tracking_completion.campaign.yaml --confirm-write --confirm-execute

# Status polling de uma execução real (leitura pura, sem gate)
dlctl execute status --item-id ITEM_ID --job-instance-id JOB_INSTANCE_ID --wait --poll-seconds 5 --timeout-seconds 300

# Bulk Copy Jobs (Plan 39): plan -> dry-run -> apply, nunca roda os jobs
dlctl copyjobs bulk plan --definitions-dir copyjob_definitions/bulk
dlctl copyjobs bulk diff --definitions-dir copyjob_definitions/bulk
dlctl copyjobs bulk dry-run --plan copyjob_definitions/bulk/bulk.plan.json
dlctl copyjobs bulk apply --plan copyjob_definitions/bulk/bulk.plan.json --confirm-write
dlctl copyjobs bulk reconcile --definitions-dir copyjob_definitions/bulk

# Git plan-commit com seleção de itens
dlctl git plan-commit --workspace LAKEHOUSE-DEV --item-ids "id1,id2"

# ---- Linhagem do Lakehouse (integração Skill-LineageFabric) ----

# Sincroniza notebooks do workspace via Azure CLI (forma padrão de conexão desta feature)
dlctl lineage sync-notebooks
# Com paralelismo customizado (1-8 downloads simultâneos; padrão vem de FABRIC_SYNC_MAX_WORKERS no .env)
dlctl lineage sync-notebooks --max-workers 8

# Gera Linhagem Tabelas + Tabelas (+ trilha SharePoint, se --workspaces-input for informado)
dlctl lineage generate --lakehouse-dev-input input/lakehouse-dev --workspaces-input input/Workspaces

# Consulta os artefatos persistidos
dlctl lineage show dependencies --domain ORDER_TRACKING
dlctl lineage show catalog
dlctl lineage show sharepoint

# Mapa Isolado (upstream/downstream) de uma tabela/fonte, direto no terminal
dlctl lineage isolate PR_RECEIPT_ORDER --direction "Linhagem completa"

# Painel de controle
dlctl dashboard
```

Todos os comandos aceitam `--profile NOME` (default vem de `DLCTL_PROFILE`
no `.env`, ou `ms_client_constellation`).

> **Nota de segurança**: os comandos que precisam de um Fabric client
> autenticado ao vivo (`pipelines diagnose-run` sem `--run-export`,
> `pipelines wait`, `jobs driver-log` sem export local, e as fases
> `wait`/`logs`/`sql_endpoint` de `execute campaign`) **não foram executados
> nem testados contra nenhum endpoint real durante o desenvolvimento desta
> sessão** — por instrução explícita, para não comprometer o ambiente DEV.
> Sem credenciais no `.env`, eles sempre retornam `manual_required` de forma
> explícita.

## 4. Dashboard de controle (leitura + ações)

### Rodando localmente (mesma máquina que abre o navegador)

```bash
dlctl dashboard
# ou diretamente (funciona igual em Windows/Linux/macOS):
streamlit run src/dlctl/dashboard/app.py
# ou:
python -m streamlit run src/dlctl/dashboard/app.py
```

Abre em `http://localhost:8501`.

Ou via Docker (sem precisar instalar Python localmente): `docker compose up
-d` — veja a seção **2.1** acima.

### Rodando em um servidor e acessando de outra máquina na rede

Se o `dlctl` rodar em uma máquina (servidor Linux, VM, notebook do time) e
você quiser acessar o dashboard do navegador de **outro** computador na
mesma rede:

```bash
# na máquina onde o dlctl está instalado:
streamlit run src/dlctl/dashboard/app.py --server.address 0.0.0.0 --server.port 8501
# (ou: dlctl dashboard --port 8501, mas para expor em 0.0.0.0 use o comando streamlit direto)
```

Depois, no navegador de qualquer outra máquina da mesma rede, acesse:

```
http://<IP-ou-hostname-do-servidor>:8501
```

Descubra o IP do servidor com `ipconfig` (Windows) ou `ip addr` / `hostname -I` (Linux/macOS).

> ⚠️ **Segurança**: por padrão o Streamlit não tem autenticação própria.
> Se for expor `0.0.0.0` em uma rede não confiável, coloque atrás de um
> proxy reverso com autenticação (ex.: Nginx + Basic Auth, ou Azure App
> Service/Container Apps com autenticação do Entra ID) e libere a porta
> apenas no firewall interno. Nunca exponha a porta do dashboard direto na
> internet sem essa camada, pois a página de Configuração grava segredos no
> `.env` do servidor.

### Considerações para múltiplas máquinas / múltiplos usuários

- Cada máquina que instala o projeto (seção 2) tem seu **próprio** `.env`,
  `config/profiles.yaml` e `state/dlctl.db` — são arquivos locais, não
  sincronizados automaticamente entre máquinas.
- Se cada pessoa do time roda sua própria instância localmente, cada uma verá
  apenas o histórico de execuções que ela mesma gerou. Para um histórico
  **compartilhado** (mesmas execuções/mapeamentos visíveis para todo o time),
  centralize a instalação em uma única máquina/servidor e todos acessam o
  mesmo dashboard remotamente (seção acima), em vez de rodar uma cópia local
  cada um.
- Para replicar a mesma configuração (perfis/domínios) em várias máquinas sem
  segredos, você pode versionar `config/profiles.yaml` (não contém segredos,
  só nomes de variáveis de ambiente) e distribuir um `.env` por fora (cofre de
  segredos da empresa, gestor de senhas, etc.) — nunca commitar o `.env`.

Abre em `http://localhost:8501` com 3 páginas (navegação na barra lateral):

### Página principal — Visão Geral (somente leitura)
- **Visão Geral**: KPIs de execuções (sucesso/bloqueadas/falhas) e distribuição de status por passo.
- **Mapeamentos**: tabelas Bronze→Silver / Silver→Gold com status (`spark_ready`, `needs_rewrite`, `manual_review`, etc.) e gráfico de pizza.
- **Execuções & Passos**: linha do tempo detalhada de cada rodada do pipeline.
- **Manifests**: estado de cada manifest processado (validado/planejado/aplicado).
- **Atividades**: log de auditoria (equivalente à trilha de evidência das skills).
- **Ownership/Rollback**: recursos criados e registrados para rollback controlado.

### Página "Configuração" — editar conexões/credenciais pelo front-end
- Formulários para **FABRIC_TENANT_ID/CLIENT_ID/CLIENT_SECRET/AUTH_MODE/WORKSPACE**,
  **ORACLE_DB_DSN/USER/PASSWORD** e **ORACLE_BIP_BASE_URL/USER/PASSWORD**, gravados
  diretamente em `.env`. Segredos já salvos **nunca são reexibidos** — o campo fica em
  branco e só é sobrescrito se você digitar um novo valor.
- Toggle de **ambiente (DEV/HML/PRD)** e **allow_write/allow_production**, gravado em
  `config/profiles.yaml`.
- CRUD de **domínios de negócio** (ORDER_TRACKING, FINANCEIRO, etc.) com `folder_path`,
  `silver_lakehouse`, `gold_lakehouse`.
- Botões **"Testar Microsoft Fabric"** e **"Testar Oracle DB"** que tentam autenticar/conectar
  de verdade e mostram o resultado (ou o erro/`manual_required`) na tela.

### Página "Ações" — acionar todos os fluxos pelo front-end
Reaproveita exatamente a mesma lógica core do CLI (nenhuma duplicação de regra de negócio):
1. **Inventário**: botões para rodar inventário Silver/Gold e reconcile-scope.
2. **Gerar Silver**: seleciona uma tabela GO do mapeamento, gera e valida o notebook.
3. **Gerar Gold**: idem para Silver→Gold.
4. **Manifest (Fabric)**: seleciona um manifest existente ou cria um novo YAML pela UI,
   roda Validate → Plan → Dry-run, e só permite **Apply** com os checkboxes
   "Confirmo a escrita" (e "Confirmo produção"/"Confirmo mover" quando aplicável) marcados —
   mesmo gate do `--confirm-write` do CLI.
5. **Execute (gated)**: monta um manifesto de execução (item Fabric + parâmetros JSON),
   roda Plan → Dry-run, e só dispara com o checkbox "Confirmo a execução"
   (`--confirm-execute`) marcado.
6. **Pipeline Router**: formulário com os paths Bronze/Silver/Gold e os checkboxes de
   escrita/publicação/execução; um clique roda o workflow de 10 passos do router
   (`constellation-order-tracking-etl`) e mostra a linha do tempo em tempo real.
7. **Linhagem (Azure CLI)**: botão que baixa (ou atualiza) os notebooks do workspace
   configurado via Azure CLI (`az login`, sem App Registration) para `input/lakehouse-dev/`
   em paralelo — equivalente a `dlctl lineage sync-notebooks`, com um campo para
   ajustar o número de downloads simultâneos (1-8, padrão vem de `FABRIC_SYNC_MAX_WORKERS`
   no `.env`) — seguido de um botão para gerar os artefatos de Linhagem
   (`dlctl lineage generate`), populando as páginas Linhagem Grafo/Artefatos/SharePoint/Workspaces.

O dashboard **nunca** aplica uma escrita/execução sem o gate equivalente marcado —
os mesmos `authorize_write`/`authorize_execute` do CLI (`dlctl.core.gates.GateContext`)
são chamados por trás dos botões.

### Página "Diagnósticos Avançados" — backlog incorporado (3 incidentes reais)

Todas as funcionalidades levantadas em `fabric-fullctl-backlog.zip`, 100% locais/offline:

1. **📋 Backlog Tracker**: tabela filtrável (P0/P1/P2, status, o que já está
   coberto no dlctl) com as 24 lacunas + 1 nota dos 3 incidentes.
2. **🔎 Auditoria Copy Job**: `mappings-inspect` e `oracle-number-audit` sobre
   um `copyjob-content.json` local (+ export opcional de schema Oracle),
   destacando colunas `NUMBER` sem precisão/escala e tabelas/colunas sem mapping.
3. **🔒 Leases**: adquirir/listar/liberar locks leves sobre workspace/itens/
   tabelas — integrado ao `authorize_write`, bloqueia escrita se outro owner
   tiver uma lease ativa conflitante.
4. **🚀 Execute Campaign**: roda um manifesto multi-alvo (DAG com
   `depends_on`) fase a fase (preflight→publish→execute→wait→logs→classify→
   delta→sql_endpoint→seal), serial, com isolamento de falha por dependência.
5. **🧬 Definitions Inspect**: calcula os 3 hashes nomeados de uma definição
   Fabric local (`aggregateDefinitionSha256`/`encodedPayloadSha256`/`decodedContentSha256`).
6. **📜 Log Classifier**: cola um log e recebe um veredito `PASS`/`FAIL`/
   `NEVER_PASS` — assinatura desconhecida nunca passa silenciosamente.

### Página "Retro / Melhoria Contínua" — motor de retro próprio

1. Botão **"Rodar análise"** (janela em dias + contagem mínima) — chama
   `dlctl.core.retro.analyze` e persiste as propostas encontradas.
2. Tabela filtrável por categoria/risco/status.
3. Seletor de proposta com detalhe completo (título, evidência bruta,
   afetado, texto da proposta) e aviso **⚠ GATE-CHANGE** destacado quando a
   categoria é `gate-friction`.
4. Botões **✅ Aprovar** / **❌ Rejeitar** — Stage B: só marca status, nunca
   aplica nada sozinho.
5. **Gerar relatório completo** + botão de download do markdown.

### Páginas "Linhagem" — integração do Skill-LineageFabric

Todas leem o que `dlctl lineage generate` persistiu em `state.py`
(nenhuma dessas páginas chama a Fabric API diretamente):

1. **🔗 Linhagem — Grafo Isolado** (`5_Linhagem_Grafo.py`): escolha uma
   geração (batch), busque uma tabela/schema/lakehouse e isole o "Mapa
   Isolado" — upstream, downstream ou linhagem completa — com o mesmo
   critério do `docs/lineage-report.md` original. Exporta as relações em CSV.
2. **📋 Linhagem — Artefatos** (`6_Linhagem_Artefatos.py`): visualizador
   genérico e filtrável dos demais artefatos gerados (aba **Tabelas** —
   catálogo por domínio/status — e a própria **Linhagem Tabelas**, com
   destaque para as linhas transitivas), além do histórico de gerações.
3. **🧷 Linhagem — Dependências SharePoint** (`7_Linhagem_SharePoint.py`):
   trilha dashboard/relatório → dataset → tabela → fonte SharePoint extraída
   dos JSONs do Fabric Scanner API, com validação de existência de cada elo
   (🟢 existe / 🔴 não encontrado) e um grafo que destaca visualmente o que
   está ausente (ex.: relatório apontando para um dataset fora do scan).

## 5. Gates de segurança (Central Write Gate)

Toda escrita/execução passa por `dlctl.core.gates.GateContext`, que replica
fielmente as regras das skills:

- `authorize_write`: exige `profile.microsoft.allow_write=true` **e**
  `--confirm-write` explícito no comando atual; PRD exige adicionalmente
  `--confirm-production`; e (novo) verifica se não há **lease conflitante**
  de outro owner sobre os mesmos itens/tabelas (`dlctl leases`).
- `authorize_execute`: exige `--confirm-execute` explícito (nunca reaproveita
  autorização de um turno anterior).
- `authorize_delete`, `authorize_move`, `authorize_publish`,
  `authorize_rollback`, `authorize_security_change`,
  `authorize_git_commit/update`, `authorize_data_access`: um gate dedicado
  por categoria de mutação, cada um com sua própria flag.
- Toda recusa de qualquer `authorize_*` é logada em `ActivityLog`
  (`level=BLOCKED`, `source=gates.<método>`) **antes** de levantar
  `SecurityError` — essa trilha alimenta o motor de retro (`dlctl retro
  analyze`), que trata recusas repetidas como sinal de "gate-friction"
  (documentação/mensagem precisa melhorar), nunca como motivo para
  enfraquecer o gate.

Sem credenciais Fabric configuradas, `manifest apply`/`execute apply`/
`execute campaign` retornam `status=manual_required`/`skipped` de forma
explícita (nunca fingem sucesso).

## 6. Testes

```powershell
pytest -q
```

49 testes cobrindo: gates de escrita/execução/delete/move (+ leases), motor
de manifests (validate/plan/apply, placeholders, parâmetros tipados),
geradores de notebook (Notebook Contract, Gold Gates, rejeição de
Pandas/placeholders), registry de mapeamento (inventário, reconcile-scope),
auditoria de Copy Job (Oracle NUMBER), inspeção de definições (hash triad),
classificador de logs (NEVER_PASS por padrão), o orquestrador de campanha
(ordenação topológica, isolamento de falha por DAG) e o motor de retro
(normalização de erro, detecção de cada categoria de sinal, workflow
aprovar/rejeitar, e que reanalisar nunca sobrescreve uma decisão humana).

## 7. Auditoria de cobertura (o que está unificado vs. o que ficou de fora)

Este projeto **não** implementa 100% da superfície de ~80 comandos citada em
`cli_command_surface.md` — focou no caminho crítico documentado (router
Order Tracking, ETL Bronze/Silver/Gold, Canonical Write/Execute Workflow,
Copy Job, backlog de incidentes reais, motor de retro). Abaixo, o que está
coberto e o que **não** está, por honestidade:

### ✅ Totalmente coberto
- Router `constellation-order-tracking-etl` (10 passos) → `dlctl pipeline run-order-tracking`
- `etl-oracle-fabric` / `etl-oracle-fabric-gold` (inventário, geração, validação, reconcile-scope)
- Canonical Write/Execute Workflow (`manifest`/`execute`) + Central Write Gate
- `datapipeline_manifest_patterns.md` (schema completo + exemplos)
- `copyjob_surface.md` incluindo o bulk do Plan 39 (`copyjobs bulk plan/dry-run/diff/apply/reconcile`)
- Todos os 5 itens **P0** do backlog de incidentes (leases, oracle-number-audit, sql endpoint route fix, execute campaign, driver-log wait, log classifier)
- Motor de retro próprio (`dlctl retro`) — não fazia parte do pedido original, é uma extensão

### ⚠️ Parcialmente coberto
- `git_workflow.md`: status/diff-summary/plan-commit/commit/update-from-git ✅; `connection`, `credentials`, `changes`, `plan-update` ❌
- `variable_libraries_workflow.md`: list/definition/create ✅; `get`, `write-plan`, `update-definition`, `activate-valueset`, `delete` ❌
- `environment_workflow.md`: inspect/export/publish ✅; `create/delete` (bootstrap descartável), `libraries plan/apply`, `compute plan/apply`, `rollback` ❌
- `constellation_fusion_pattern.md`: conector BI Publisher genérico existe (`OracleBipConnector`), mas não há um gerador de notebook `nb_bipublisher_fusion`/config-notebooks como os geradores Silver/Gold
- Backlog P1/P2: a maioria tem pelo menos anotação no tracker; itens ainda sem código (`lakehouses --where`, `--wait-sql-sync`/`SQL_ENDPOINT_STALE`, `--expected-column-count` separado, canário de parâmetros, detecção adicional de defeitos no gerador Gold) seguem como propostas em aberto no `dlctl retro`/backlog tracker

### ❌ Não coberto (fora do caminho crítico documentado)
- Gateways e Connections (create/update/delete/roles) — RBAC de workspace, OneLake Data Access Security, `sqlsec` (DDM/RLS/CLS)
- `lakehouses` de leitura de dados (`table-query`, `delta-read`, `table-stats`, `aggregate`, `schema-diff`) e `onelake` (download/upload/transfer)
- Criação/resolução direta de Notebooks/Pipelines/Dataflows (`notebooks create`, `pipelines create`, `dataflows create`) — hoje só manifest genérico cobre isso indiretamente
- `jobs run/status/cancel/schedules`, `spark sessions`, `capacities`, `semantic refresh-plan`, `evidence list/pack`, `recipes`, `ownership list/verify` como comandos dedicados, `cleanup plan/apply`, `api request`

Se algum desses itens for necessário para o seu fluxo real, me diga qual e eu
implemento seguindo o mesmo padrão (offline-first, gated, testado).

## 8. Próximos passos para produção

1. Preencher `.env` com credenciais reais (Entra ID App Registration com
   permissões Fabric; usuário/BIP do Oracle Fusion).
2. Completar `mappings/bronze_to_silver.csv` e `mappings/silver_to_gold.csv`
   com o mapeamento real de tabelas do cliente (as 24 Bronze do Order
   Tracking, etc.) e os arquivos `sql/*.sql` / `schema/*.tab` correspondentes.
3. Ajustar `ORDER_TRACKING_BRONZE_24` em
   `src/dlctl/commands/inventory_cmds.py` com a lista real das 24 tabelas.
4. Revisar/expandir `connectors/fabric_api.py` para os endpoints específicos
   ainda não cobertos (onelake-security, sqlsec, gateways) antes de usá-los
   em produção — hoje eles não têm comando dedicado.
5. Rodar `dlctl auth doctor` e `dlctl auth oracle-doctor` para validar as
   conexões antes de qualquer operação de escrita.
