# HELPER.md — Guia completo do `dlctl` (CLI + Dashboard)

Este guia explica, em linguagem simples, **tudo** que você pode fazer com o
projeto: cada comando do CLI, cada botão/página do dashboard, e como
configurar as credenciais para que tudo funcione de verdade. Se você nunca
mexeu neste projeto, comece pela seção **1. Primeiros passos**.

---

## 1. Primeiros passos (para quem nunca usou)

### 1.1. Instalar

**Windows (PowerShell):**
```powershell
cd "CLI Datalake"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[oracle,dashboard,dev]"
```

**Linux/macOS:**
```bash
cd cli-datalake
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[oracle,dashboard,dev]"
```

### 1.2. Configurar credenciais

Copie o arquivo de exemplo e preencha:
```bash
cp .env.example .env      # Linux/macOS
Copy-Item .env.example .env   # Windows
```

Você pode editar o `.env` na mão **ou** pela tela "Configuração" do
dashboard (veja seção 4.2) — os dois caminhos escrevem no mesmo arquivo.

Campos principais do `.env`:

| Campo | Para que serve |
|---|---|
| `FABRIC_AUTH_MODE` | `azure_cli` (**padrão/recomendado**: reaproveita `az login`, sem App Registration) \| `client_credentials` (sem interação, precisa de App Registration) \| `device_code` (você loga no navegador) |
| `FABRIC_TENANT_ID` | ID do tenant no Microsoft Entra ID (só necessário para `client_credentials`/`device_code`) |
| `FABRIC_CLIENT_ID` | ID do App Registration (aplicação) cadastrado no Entra ID (idem) |
| `FABRIC_CLIENT_SECRET` | Segredo do App Registration (só necessário se `FABRIC_AUTH_MODE=client_credentials`) |
| `FABRIC_WORKSPACE_NAME` / `FABRIC_WORKSPACE_ID` | Workspace Fabric alvo |
| `ORACLE_DB_DSN` / `ORACLE_DB_USER` / `ORACLE_DB_PASSWORD` | Conexão com o banco Oracle |
| `ORACLE_BIP_BASE_URL` / `ORACLE_BIP_USER` / `ORACLE_BIP_PASSWORD` | Conexão com o Oracle BI Publisher |
| `DLCTL_ALLOW_WRITE` | `true`/`false` — permite (ou não) que comandos de escrita funcionem |
| `DLCTL_ALLOW_PRODUCTION` | `true`/`false` — libera o gate extra exigido em PRD (`--confirm-production`) |
| `FABRIC_SYNC_MAX_WORKERS` | Paralelismo (1 a 8) de `dlctl lineage sync-notebooks`; comece com 4, reduza se a API retornar 429 |

> ✅ **Modo padrão `azure_cli`**: instale o Azure CLI, rode `az login` (e
> `az account set --subscription "..."` se tiver mais de uma assinatura) e
> pronto — não precisa preencher `FABRIC_TENANT_ID`/`FABRIC_CLIENT_ID`. É a
> mesma forma de conexão usada pela sincronização de notebooks da feature de
> Linhagem (`dlctl lineage sync-notebooks`).
>
> ⚠️ Preencher o `.env` sozinho não é suficiente para autenticar de verdade
> no Fabric com `client_credentials`: o **administrador do tenant** também
> precisa (1) habilitar "Service principals can use Fabric APIs" no admin
> portal do Fabric e (2) adicionar o App Registration como membro do
> workspace. Isso é configuração do lado Microsoft, fora do `dlctl`.

### 1.3. Testar se as credenciais funcionam
```bash
dlctl auth doctor          # testa Fabric
dlctl auth oracle-doctor   # testa Oracle
```
Ou pelo dashboard: página **Configuração → aba "Testar Conexões"**.

### 1.4. Abrir o dashboard
```bash
dlctl dashboard
```
Abre `http://localhost:8501` no navegador. Veja a seção 4 para o que cada
página faz.

### 1.5. Regra de ouro de segurança

Nenhum comando de escrita/execução funciona só porque a credencial está
configurada. Você **também** precisa:
1. Ter `DLCTL_ALLOW_WRITE=true` no `.env` (ou marcado na página Configuração), **e**
2. Passar a flag de confirmação explícita naquele comando (`--confirm-write`,
   `--confirm-execute`, etc.) — ou marcar o checkbox equivalente no dashboard.

Sem os dois ao mesmo tempo, o comando é recusado (ou, se faltar credencial,
retorna `manual_required`) — nunca finge que deu certo.

---

## 2. Estrutura de pastas que você vai usar no dia a dia

| Pasta | Para que serve |
|---|---|
| `mappings/` | Planilhas (CSV) de mapeamento Bronze→Silver e Silver→Gold |
| `manifests/` | Arquivos YAML descrevendo o que publicar no Fabric (pipelines, notebooks, campanhas); `manifests/lineage/` guarda os Excels de conferência gerados por `dlctl lineage generate` |
| `sql/`, `schema/` | SQL adaptado e contratos de schema usados na geração de notebooks |
| `notebooks/silver/`, `notebooks/gold/` | Notebooks `.ipynb` gerados |
| `copyjob_definitions/` | Definições de Copy Job (individuais e em lote/bulk) |
| `state/` | Banco de dados local (`dlctl.db`), evidências e cache de login — **não apague sem necessidade**, é o histórico do dashboard |

---

## 3. Todos os comandos do CLI (`dlctl ...`)

Uso geral: `dlctl <grupo> <comando> [opções]`. Toda opção com valor pode ser
vista com `dlctl <grupo> <comando> --help`. Comandos marcados com 🔒 exigem
uma flag de confirmação explícita (gate de segurança); comandos marcados com
🌐 precisam de credenciais reais configuradas para funcionar por completo
(sem elas, respondem `manual_required`, sem quebrar).

### 3.0. Comandos soltos
| Comando | O que faz |
|---|---|
| `dlctl version` | Mostra a versão instalada |
| `dlctl dashboard [--port 8501]` | Abre o painel de controle no navegador |

### 3.1. `dlctl auth` — testar credenciais
| Comando | O que faz |
|---|---|
| `auth profile-show [--profile NOME]` | Mostra o profile ativo (ambiente, permissões, workspace) sem revelar segredos |
| `auth doctor [--profile NOME]` 🌐 | Tenta autenticar de verdade no Fabric e listar workspaces visíveis |
| `auth oracle-doctor [--profile NOME]` 🌐 | Tenta conectar de verdade no banco Oracle configurado |

### 3.2. `dlctl inventory` — inventário e escopo Bronze/Silver/Gold
| Comando | O que faz |
|---|---|
| `inventory silver [--domain X] [--profile NOME]` | Lista o status de cada tabela Silver (pronta, precisa reescrita, bloqueada etc.) e gera relatório em `state/reports/` |
| `inventory gold [--domain X] [--profile NOME]` | Mesma coisa, para as tabelas Gold |
| `inventory reconcile-scope [--layer bronze_to_silver\|silver_to_gold] [--domain X] [--restrict-order-tracking-24]` | Verifica se os alvos dependem só das fontes permitidas |
| `inventory cache show [--profile NOME]` | Mostra os itens Fabric já resolvidos e guardados em cache local (evita repetir chamadas) |
| `inventory cache query [--type TIPO] [--profile NOME]` | Filtra o cache por tipo de item (ex.: Notebook, Lakehouse) |

### 3.3. `dlctl manifest` — publicar itens no Fabric (fluxo seguro em 5 passos)
| Comando | O que faz |
|---|---|
| `manifest validate --manifest ARQUIVO.yaml` | Verifica se o arquivo de manifesto está bem formado (sem tocar rede) |
| `manifest plan --manifest ARQUIVO.yaml [--out-plan ARQUIVO.plan.json]` | Compara com o que já existe no Fabric (se houver credencial) e decide create/update/noop |
| `manifest dry-run --manifest ARQUIVO.yaml [--plan ARQUIVO.plan.json]` | Confirma que nada mudou desde o plano (100% offline) |
| `manifest apply --manifest ARQUIVO.yaml [--plan ...] --confirm-write [--confirm-production] [--confirm-move]` 🔒🌐 | Aplica de fato (cria/atualiza o item no Fabric) |
| `manifest status --manifest-id ID` | Mostra o histórico de um manifesto já processado |
| `manifest init --resource-type TIPO --manifest-id ID --display-name NOME --out ARQUIVO.yaml [--folder-path PASTA]` | Gera um esqueleto de manifesto novo para você editar |

> Sequência recomendada: **validate → plan → dry-run → apply**.

### 3.4. `dlctl environments` — Ambientes Fabric (Spark/bibliotecas)
| Comando | O que faz |
|---|---|
| `environments inspect --workspace WS --environment ENV` 🌐 | Mostra o estado atual de um Environment |
| `environments export --workspace WS --environment ENV --out PASTA` 🌐 | Exporta o estado para uma pasta local (com hash de verificação) |
| `environments publish --workspace WS --environment-id ID --confirm-publish` 🔒🌐 | Publica o Environment (só a publicação, não escrita de bibliotecas/compute) |

### 3.5. `dlctl git` — integração com o Git do Fabric
| Comando | O que faz |
|---|---|
| `git status --workspace WS` 🌐 | Mostra o status de sincronização (conflitos, head atual) |
| `git diff-summary --workspace WS` 🌐 | Resumo rápido do status |
| `git plan-commit --workspace WS [--item-ids "id1,id2"]` 🌐 | Mostra o que seria commitado, sem commitar |
| `git commit --workspace WS --message "..." --expect-head HEAD [--item-ids "..."] --confirm-git-commit` 🔒🌐 | Faz o commit de verdade |
| `git update-from-git --workspace WS --expect-head HEAD --confirm-git-update` 🔒🌐 | Atualiza o workspace a partir do Git |

### 3.6. `dlctl variable-libraries` — bibliotecas de variáveis
| Comando | O que faz |
|---|---|
| `variable-libraries list --workspace WS` 🌐 | Lista as bibliotecas existentes |
| `variable-libraries definition --workspace WS --library NOME` 🌐 | Mostra a definição (valores sensíveis sempre ocultos) |
| `variable-libraries create --workspace WS --name NOME [--description D] --confirm-create` 🔒🌐 | Cria uma nova biblioteca |

### 3.7. `dlctl copyjobs` — Copy Jobs (individuais e em lote)
| Comando | O que faz |
|---|---|
| `copyjobs list --workspace WS` 🌐 | Lista os Copy Jobs existentes |
| `copyjobs run --workspace WS --name NOME --confirm-execute` 🔒🌐 | Executa **um** Copy Job específico |
| `copyjobs mappings-inspect --definition ARQUIVO.json` | Lista tabelas/colunas mapeadas em um `copyjob-content.json` local (offline) |
| `copyjobs oracle-number-audit --definition ARQUIVO.json [--schema-export EXPORT.json]` | Audita colunas Oracle `NUMBER` sem precisão (evita virarem "Decimal gigante" sem querer) |
| `copyjobs bulk plan --definitions-dir PASTA [--out-plan ARQUIVO.json]` | Compara **vários** Copy Jobs locais (`*.copyjob.yaml`) contra o que existe no Fabric |
| `copyjobs bulk diff --definitions-dir PASTA` | Mostra só as diferenças (sem salvar plano) |
| `copyjobs bulk dry-run --plan ARQUIVO.json` | Confere que nada mudou desde o plano (offline) |
| `copyjobs bulk apply --plan ARQUIVO.json --confirm-write [--confirm-production]` 🔒🌐 | Cria/atualiza **vários** Copy Jobs de uma vez (nunca executa os jobs, só cria/atualiza a definição) |
| `copyjobs bulk reconcile --definitions-dir PASTA` 🌐 | Mostra o que existe só localmente, só no Fabric, e duplicatas |

### 3.8. `dlctl execute` — rodar notebooks/pipelines/dataflows/Copy Jobs
| Comando | O que faz |
|---|---|
| `execute plan --manifest ARQUIVO.yaml` | Mostra o que seria executado, sem executar |
| `execute dry-run --manifest ARQUIVO.yaml` | Valida a estrutura do manifesto de execução |
| `execute apply --manifest ARQUIVO.yaml --confirm-execute` 🔒🌐 | Dispara a execução de verdade |
| `execute campaign --manifest ARQUIVO.yaml --confirm-write --confirm-execute` 🔒🌐 | Roda uma "campanha" com **vários alvos dependentes entre si** (publica → executa → espera → confere logs → sela), pulando os que dependem de um alvo que falhou |
| `execute status --item-id ID --job-instance-id ID [--wait] [--poll-seconds N] [--timeout-seconds N]` 🌐 | Consulta se uma execução terminou com sucesso, falha ou ainda está rodando |

### 3.9. `dlctl etl-silver` / `dlctl etl-gold` — gerar notebooks
| Comando | O que faz |
|---|---|
| `etl-silver generate --table NOME [--domain X] [--write]` | Gera (e valida) um notebook Silver para uma tabela |
| `etl-silver generate-all [--domain X] [--write] --approved` | Gera notebooks para **todas** as tabelas prontas do domínio (exige `--approved`) |
| `etl-silver validate CAMINHO_DO_NOTEBOOK` | Valida um notebook Silver já existente |
| `etl-gold generate --table NOME --silver-base-path X --gold-base-path Y [--write]` | Gera (e valida) um notebook Gold |
| `etl-gold validate CAMINHO_DO_NOTEBOOK` | Valida um notebook Gold já existente |
| `etl-gold reconcile-gold-scope [--domain X]` | Verifica se os Golds só dependem de Silvers já validados |

### 3.10. `dlctl pipeline run-order-tracking` — rodar o fluxo completo de uma vez
```
dlctl pipeline run-order-tracking [--domain ORDER_TRACKING] [--write] [--publish]
    [--confirm-write] [--confirm-execute] [--profile NOME]
```
Roda os 10 passos do fluxo (identificar tabelas → gerar Silver → validar →
publicar → executar → validação de negócio → gerar Gold → publicar/executar
→ conectar relatório), registrando cada passo no dashboard.

### 3.11. `dlctl leases` — evitar que dois processos mexam na mesma coisa ao mesmo tempo
| Comando | O que faz |
|---|---|
| `leases acquire --owner NOME [--workspace WS] [--item-ids "..."] [--tables "..."] [--ttl 3600]` | Reserva um "cadeado" temporário sobre itens/tabelas |
| `leases list [--active-only/--all]` | Lista os cadeados ativos (ou todos) |
| `leases release --lease-id ID --owner NOME` | Libera o cadeado |

### 3.12. `dlctl pipelines` — diagnóstico de execuções de pipeline
| Comando | O que faz |
|---|---|
| `pipelines diagnose-run [--run-export ARQUIVO.json] [--item ID --run-id ID] [--failed-only/--all]` | Resume os erros de uma execução de pipeline (offline se você já tiver o export salvo) |
| `pipelines wait --run-id ID [--timeout 1800] [--poll-interval 10]` 🌐 | Espera uma execução de pipeline terminar |

### 3.13. `dlctl definitions part-inspect --file ARQUIVO.json`
Calcula 3 "impressões digitais" (hash) diferentes de uma definição do
Fabric, para você saber com certeza se algo mudou ou não.

### 3.14. `dlctl jobs` — logs de execução
| Comando | O que faz |
|---|---|
| `jobs driver-log [--item ID --job-instance-id ID] [--wait] [--max-attempts 10] [--poll-seconds 3]` 🌐 | Busca o log de uma execução, tentando de novo só quando o log ainda não existe |
| `jobs classify-log --file ARQUIVO.log [--extract-notebook-exit/--no-extract-notebook-exit]` | Lê um log e diz se passou, falhou, ou tem algo desconhecido (nunca deixa passar silenciosamente o que não reconhece) |

### 3.15. `dlctl retro` — motor de melhoria contínua
| Comando | O que faz |
|---|---|
| `retro analyze [--window-days 90] [--min-count 3]` | Analisa o histórico do próprio dlctl e sugere melhorias |
| `retro list [--category X] [--risk X] [--status X]` | Lista as sugestões geradas |
| `retro approve --key CHAVE` | Marca uma sugestão como aprovada (não aplica nada sozinho) |
| `retro reject --key CHAVE` | Marca como rejeitada |
| `retro report [--out ARQUIVO.md] [--window-days 90]` | Gera um relatório markdown com todas as sugestões |

### 3.16. `dlctl lineage` — Linhagem do Lakehouse (integração Skill-LineageFabric)
| Comando | O que faz |
|---|---|
| `lineage sync-notebooks [--output-dir input/lakehouse-dev] [--max-workers N]` 🌐 | Baixa os notebooks do workspace via Azure CLI (`az login`), em paralelo (1-8 downloads simultâneos; padrão: `FABRIC_SYNC_MAX_WORKERS` do `.env`) |
| `lineage generate --lakehouse-dev-input DIR [--workspaces-input DIR_OU_ZIP] [--no-excel]` | Parseia notebooks (+ JSONs do Fabric Scanner, se informado) e gera Linhagem Tabelas/Tabelas/trilha SharePoint. Se `--workspaces-input` for informado, também gera os 3 artefatos extras do projeto original Skill-LineageFabric: extrato bruto completo (`fabric_lineage_*.xlsx`, 7 abas), Simplified Migration (`fabric_lineage_simplified_migration_*.xlsx`, 4 abas) e PowerQuery Detailed (`fabric_lineage_powerquery_detailed_*.xlsx`, 5 abas) |
| `lineage show dependencies\|catalog\|sharepoint [--batch-id ID] [--domain X]` | Lista as linhas persistidas de um artefato (padrão: última geração) |
| `lineage isolate TERMO [--direction "Downstream"\|"Upstream"\|"Linhagem completa"]` | Mostra o Mapa Isolado (upstream/downstream) de uma tabela/fonte em texto |

### 3.17. `dlctl supervisor` — diagnóstico geral do projeto (Bronze/Silver/Gold/Dashboards/Views)
| Comando | O que faz |
|---|---|
| `supervisor scan [--lakehouse-dev-input DIR] [--workspaces-input DIR_OU_ZIP] [--save]` | Calcula, para Bronze/Silver/Dashboards, quanto **deveria existir no total** (união de `mappings/*.csv` + linhagem extraída de *todos* os notebooks de `input/lakehouse-dev` + tabelas Oracle referenciadas em `input/Workspaces` + total de relatórios do Power BI); para **Gold**, olha para todos os dashboards que o cliente precisa e calcula quais tabelas Gold eles realmente exigem (Dataset Tables dos relatórios em `input/Workspaces`) contra quantas dessas tabelas já existem de verdade em `input/lakehouse-dev`. Views/Processos intermediários usa uma meta manual. Com `--save`, exporta o relatório para `manifests/dashboard/` e grava no histórico |
| `supervisor history` | Lista as visões já salvas (`scan --save`), com percentual geral e caminho do Excel de cada uma |
| `supervisor set-targets [--intermediate N]` | Define a meta de Views/processos intermediários em `config/project_targets.yaml` (Bronze/Silver/Gold/Dashboards já são calculados automaticamente a partir de `input/`, sem precisar de meta manual) |

---

## 4. Tudo que existe no Dashboard (`dlctl dashboard`)

O dashboard tem 9 páginas, acessíveis pela barra lateral esquerda.

### 4.1. Página principal (Visão Geral) — só leitura
- **KPIs**: quantas execuções tiveram sucesso, foram bloqueadas ou falharam.
- **Aba Visão Geral**: gráfico de execuções ao longo do tempo + distribuição de status por passo.
- **Aba Mapeamentos**: tabela de status Bronze→Silver e Silver→Gold, com gráfico de pizza.
- **Aba Execuções & Passos**: escolha uma execução e veja o passo a passo detalhado (linha do tempo).
- **Aba Manifests**: status de cada manifesto já processado (validado/aplicado/falhou).
- **Aba Atividades**: log cronológico de tudo que o dlctl fez.
- **Aba Ownership/Rollback**: quais recursos foram criados e registrados para possível rollback.

### 4.2. Página "Configuração" — editar credenciais e ambiente
- **Aba Microsoft Fabric**: escolha do modo de autenticação (`azure_cli` recomendado, `device_code` ou `client_credentials`) e campos para `TENANT_ID`/`CLIENT_ID`/`CLIENT_SECRET` (nunca reexibido depois de salvo) quando aplicável, + workspace.
- **Aba Oracle Fusion**: campos para conexão do banco e do BI Publisher.
- **Aba Ambiente & Escrita**: escolher DEV/HML/PRD e ligar/desligar `allow_write`/`allow_production` (isso só habilita a *possibilidade*; cada ação ainda pede confirmação).
- **Aba Domínios**: criar/editar/remover domínios de negócio (ex.: ORDER_TRACKING, FINANCEIRO) usados pelo resto do sistema.
- **Aba Testar Conexões**: botões para testar Fabric e Oracle de verdade e ver o resultado na tela.

### 4.3. Página "Ações" — acionar os fluxos pelo navegador (sem digitar comando nenhum)
- **1. Inventário**: botões para rodar inventário Silver/Gold e `reconcile-scope`.
- **2. Gerar Silver**: escolhe uma tabela pronta, gera e valida o notebook.
- **3. Gerar Gold**: mesma coisa, para Gold.
- **4. Manifest (Fabric)**: escolhe ou cria um manifesto, roda Validate→Plan→Dry-run, e só permite Apply com os checkboxes de confirmação marcados.
- **5. Execute (gated)**: monta um "pedido de execução" (item + parâmetros), roda Plan→Dry-run, e só dispara com o checkbox de confirmação marcado.
- **6. Pipeline Router**: formulário único para rodar o fluxo completo de ponta a ponta, com checkboxes para escrita/publicação/execução.
- **7. Linhagem (Azure CLI)**: botão **🔄 Puxar/atualizar notebooks do workspace (az login)** — mesma sincronização de `dlctl lineage sync-notebooks`, baixando os notebooks para `input/lakehouse-dev/` via Azure CLI, com campo para ajustar o paralelismo (1-8 downloads simultâneos, padrão vem de `FABRIC_SYNC_MAX_WORKERS` no `.env`); logo abaixo, botão **⚙️ Gerar artefatos de Linhagem** — mesma lógica de `dlctl lineage generate`.

### 4.4. Página "Diagnósticos Avançados" — ferramentas extras
- **📋 Backlog Tracker**: tabela com lacunas conhecidas de CLIs deste tipo (P0/P1/P2) e o que já foi resolvido aqui.
- **🔎 Auditoria Copy Job**: roda a auditoria de colunas Oracle `NUMBER` direto na tela.
- **🔒 Leases**: adquirir/listar/liberar cadeados pela interface.
- **🚀 Execute Campaign**: escolhe um manifesto de campanha e roda com um clique, vendo o progresso de cada alvo em tempo real.
- **🧬 Definitions Inspect**: cola/aponta um arquivo de definição e vê os 3 hashes.
- **📜 Log Classifier**: cola um log e recebe o veredito na hora.

### 4.5. Página "Retro / Melhoria Contínua"
- Botão para rodar a análise (mesma coisa que `dlctl retro analyze`).
- Tabela filtrável de sugestões, com aviso especial **⚠ GATE-CHANGE** quando a sugestão é sobre um gate de segurança (nunca é sugestão para enfraquecê-lo).
- Botões **Aprovar**/**Rejeitar** por sugestão.
- Botão para gerar e baixar o relatório completo em markdown.

### 4.6. Páginas "Linhagem" — grafo isolado, artefatos e dependências SharePoint
- **🔗 Linhagem — Grafo Isolado**: escolha uma tabela/fonte e a direção
  (upstream/downstream/completa); o grafo mostra só o que está relacionado
  àquele item — igual ao relatório "Mapa Isolado" do projeto original, mas
  navegável pela tela.
- **📋 Linhagem — Artefatos**: tabelas filtráveis do catálogo **Tabelas** e da
  **Linhagem Tabelas** (com destaque para as relações transitivas), + histórico
  de gerações (`dlctl lineage generate`).
- **🧷 Linhagem — Dependências SharePoint**: lista (e desenha) a trilha
  dashboard/relatório → dataset → tabela → SharePoint, marcando em vermelho o
  que não foi encontrado (ex.: relatório apontando para um dataset fora do
  scan, ou referência SharePoint não resolvida).

### 4.7. Página "Supervisor" — diagnóstico geral do projeto
- Botão **🔎 Rodar diagnóstico**: varre `input/lakehouse-dev` e `input/Workspaces`
  e calcula, por categoria (Bronze, Silver, Gold, Dashboards/BI, Views/Processos
  intermediários), quanto **existe de verdade** (notebooks reais em
  `input/lakehouse-dev`) contra quanto **deveria existir no total** — para
  Bronze/Silver isso é a união de `mappings/*.csv` com a linhagem
  extraída de *todos* os notebooks (mesmo os ainda não classificados) e, para
  Bronze, também as tabelas Oracle referenciadas nos datasets legados de
  `input/Workspaces`. Para **Gold**, a meta é calculada olhando para todos os
  dashboards do cliente em `input/Workspaces`: as tabelas do dataset de cada
  relatório são o que o Gold **precisa** entregar, e o "existente" é quantas
  dessas tabelas necessárias já têm um notebook Gold real em
  `input/lakehouse-dev`. Para Dashboards/BI é o total de relatórios
  encontrados em `input/Workspaces`, marcando como "pronto" quem já tem
  alguma tabela do seu dataset batendo com uma tabela Gold já criada. Views/
  Processos intermediários usa a meta configurada na seção "Meta" da própria
  página — sem meta, a categoria fica de fora do % geral em vez de fingir 100%.
- Barra de progresso + métricas por categoria + tabela detalhada + lista dos
  notebooks encontrados (filtrável por categoria).
- Seção **🎯 Meta**: define/edita a meta de Views/processos intermediários
  (grava em `config/project_targets.yaml`).
- Botão **💾 Salvar esta visão**: exporta o diagnóstico atual para
  `manifests/dashboard/` (Excel com abas Resumo/Notebooks/Dashboards + CSV) e
  registra no histórico exibido no final da página.

---

## 4.5. Rodando via Docker (Windows ou Linux)

O projeto inclui um `Dockerfile` e um `docker-compose.yml` que funcionam
igual em Windows e Linux (o Docker sempre executa o container em Linux por
baixo dos panos, então não há diferença de comportamento entre hosts).

### Primeira vez
```bash
cp .env.example .env      # Linux/macOS
Copy-Item .env.example .env   # Windows (PowerShell)
# edite o .env com suas credenciais/config

docker compose build
docker compose up -d
```
O dashboard fica disponível em `http://localhost:8501`.

### Autenticar com `FABRIC_AUTH_MODE=azure_cli` dentro do container
```bash
docker compose exec dlctl az login
```
A sessão fica persistida no volume `azure-cli-config`, então não precisa
logar de novo a cada `docker compose up`.

### Rodar comandos do CLI (sem abrir o dashboard)
```bash
docker compose run --rm dlctl auth doctor
docker compose run --rm dlctl inventory silver
docker compose run --rm dlctl manifest validate --manifest manifests/lineage/algum_arquivo.yaml
```

### Pastas sincronizadas com o host
`state/`, `input/`, `mappings/`, `manifests/`, `notebooks/`, `config/`,
`copyjob_definitions/`, `fabric_definitions/`, `schema/` e `sql/` são
montadas como volumes — o que o container gera/lê nessas pastas aparece
direto no seu diretório do projeto (e vice-versa).

### Parar / remover
```bash
docker compose down          # para os containers
docker compose down -v       # também apaga a sessão do az login salva
```

---

## 5. Perguntas rápidas

**"Rodei um comando e ele disse `manual_required`, é erro?"**
Não — significa que faltam credenciais reais configuradas no `.env` para
aquela ação específica. Configure e teste com `dlctl auth doctor`.

**"Rodei um comando e ele disse `BLOCKED`, é erro?"**
Não — é o gate de segurança funcionando. Você esqueceu de marcar
`--confirm-write`/`--confirm-execute` (ou o checkbox equivalente no
dashboard), ou `allow_write` está desligado no profile.

**"Como sei se uma migração deu certo de verdade?"**
Veja a página "Visão Geral" (execuções) ou rode `dlctl execute status
--wait` para conferir o status real de um job específico no Fabric.

**"Onde fica salvo o que já rodei?"**
Em `state/dlctl.db` (SQLite) — é lido tanto pelo CLI quanto pelo dashboard,
sempre o mesmo histórico.
