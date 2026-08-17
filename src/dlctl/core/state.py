"""dlctl.core.state

Estado persistente compartilhado entre o CLI e o dashboard Streamlit.
Usa SQLite (via SQLModel) para registrar: execuções de pipeline, passos,
mapeamentos Bronze/Silver/Gold, manifests aplicados, ownership/rollback e
atividades — tudo que o dashboard de controle precisa exibir.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlmodel import Field, Session, SQLModel, create_engine, select

from dlctl.config import Profile


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{datetime.now(timezone.utc):%Y%m%d%H%M%S}_{uuid.uuid4().hex[:6]}"


class PipelineRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(index=True, unique=True)
    domain: str
    profile: str
    environment: str
    status: str = "running"  # running | success | failed | blocked
    started_at: str = Field(default_factory=now_iso)
    finished_at: Optional[str] = None
    summary: str = ""


class PipelineStep(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(index=True)
    step_index: int
    step_name: str
    skill: str = ""  # etl-oracle-fabric | etl-oracle-fabric-gold | fabric-full-agent
    status: str = "pending"  # pending | running | success | failed | blocked | skipped
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    detail: str = ""


class MappingRow(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    domain: str = Field(index=True)
    layer: str  # bronze_to_silver | silver_to_gold
    source_table: str
    target_table: str
    sql_file: str = ""
    schema_file: str = ""
    status: str = "manual_review"
    notes: str = ""
    updated_at: str = Field(default_factory=now_iso)


class ManifestRecord(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    manifest_id: str = Field(index=True)
    resource_type: str
    display_name: str
    environment: str
    operation: str
    stage: str = "validated"  # validated | planned | dry_run | applied | failed
    allow_write: bool = False
    confirm_write: bool = False
    run_id: str = ""
    updated_at: str = Field(default_factory=now_iso)
    payload_path: str = ""


class ActivityLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(default="", index=True)
    timestamp: str = Field(default_factory=now_iso)
    level: str = "INFO"  # INFO | WARN | ERROR | BLOCKED
    source: str = ""  # command that generated this entry
    message: str = ""


class OwnershipRecord(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    resource_type: str
    resource_id: str
    display_name: str
    owner: str
    delete_allowed: bool = True
    created_at: str = Field(default_factory=now_iso)
    lifecycle_status: str = "active"  # active | rolled_back_deleted


class BacklogItem(SQLModel, table=True):
    """Rastreio das lacunas de CLI levantadas em incidentes reais
    (fabric-fullctl-backlog.zip): origem, prioridade, lacuna, proposta, status."""
    id: Optional[int] = Field(default=None, primary_key=True)
    item_key: str = Field(index=True, unique=True)
    origin: str  # Incid. 1 | Incid. 2 | Nota 3
    priority: str  # P0 | P1 | P2
    gap: str
    proposal: str
    status: str = "aberta"  # aberta | corrigida | parcial | nao_aplicavel
    implemented_in_dlctl: str = ""  # módulo/comando dlctl que cobre esta lacuna, se houver


class Lease(SQLModel, table=True):
    """Lock leve entre agentes/execuções sobre um workspace/itens/tabelas,
    para evitar exclusão/edição concorrente (Incid. 1, P0 'sem lock entre agentes')."""
    id: Optional[int] = Field(default=None, primary_key=True)
    lease_id: str = Field(index=True, unique=True)
    workspace: str = ""
    item_ids: str = ""  # CSV
    tables: str = ""  # CSV
    owner: str
    acquired_at: str = Field(default_factory=now_iso)
    ttl_seconds: int = 3600
    released_at: Optional[str] = None
    status: str = "active"  # active | released | expired


class CampaignRun(SQLModel, table=True):
    """Execução de 'execute campaign': orquestração multi-alvo serial e gated
    (Incid. 2, P0 'sem orquestrador multi-alvo')."""
    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: str = Field(index=True, unique=True)
    manifest_path: str = ""
    status: str = "running"  # running | success | failed | blocked
    started_at: str = Field(default_factory=now_iso)
    finished_at: Optional[str] = None
    summary: str = ""


class CampaignStep(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: str = Field(index=True)
    target: str
    phase: str  # preflight|publish|execute|wait|logs|classify|delta|sql_endpoint|seal
    status: str = "pending"  # pending|running|success|failed|blocked|skipped
    detail: str = ""
    timestamp: str = Field(default_factory=now_iso)


class CommandInvocation(SQLModel, table=True):
    """Cada chamada ao dlctl (comando + subcomando), logada automaticamente
    pelo callback raiz do Typer — alimenta o detector 'skill-featured-unused'
    do motor de retro (core/retro.py) sem precisar instrumentar cada comando."""
    id: Optional[int] = Field(default=None, primary_key=True)
    command: str = Field(index=True)  # ex.: "inventory silver", "manifest apply"
    argv: str = ""
    timestamp: str = Field(default_factory=now_iso)


class RetroProposal(SQLModel, table=True):
    """Proposta de melhoria gerada pelo motor de retro (dlctl retro analyze),
    no mesmo formato do relatório 'Improvement Proposals (retro)'. Persistida
    para permitir o fluxo de aprovação manual (Stage B: manual_required)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    proposal_key: str = Field(index=True, unique=True)
    category: str  # repeated-failure | throttling | gate-friction | prefer-resolver | skill-featured-unused | permission-gap
    risk: str  # doc-only | cli-behavior | gate-change
    title: str
    signal: str = ""
    evidence_json: str = "{}"
    affected: str = ""
    proposal_text: str = ""
    count: int = 0
    first_ts: str = ""
    last_ts: str = ""
    gate_change: bool = False
    status: str = "pending"  # pending | approved | rejected | applied
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class ItemCache(SQLModel, table=True):
    """Cache local de resolução de itens Fabric (prefer-resolver, Incid. retro):
    evita repetir list_items() ao vivo quando o mesmo item já foi resolvido
    recentemente. TTL curto por padrão; `--refresh`/cache_first=False força
    uma nova consulta ao vivo."""
    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: str = Field(index=True)
    item_type: str
    display_name: str
    item_id: str
    cached_at: str = Field(default_factory=now_iso)


_engine_cache: dict[str, object] = {}


def get_engine(profile: Profile):
    db_path: Path = profile.paths.state_root / "dlctl.db"
    key = str(db_path)
    if key not in _engine_cache:
        engine = create_engine(f"sqlite:///{db_path}")
        SQLModel.metadata.create_all(engine)
        _engine_cache[key] = engine
    return _engine_cache[key]


def get_session(profile: Profile) -> Session:
    return Session(get_engine(profile))


def log_activity(profile: Profile, message: str, level: str = "INFO", source: str = "", run_id: str = "") -> None:
    with get_session(profile) as session:
        session.add(ActivityLog(run_id=run_id, level=level, source=source, message=message))
        session.commit()


def start_run(profile: Profile, domain: str) -> str:
    run_id = new_id("run")
    with get_session(profile) as session:
        session.add(PipelineRun(run_id=run_id, domain=domain, profile=profile.name, environment=profile.environment))
        session.commit()
    log_activity(profile, f"Run iniciado para domínio {domain}", source="pipeline", run_id=run_id)
    return run_id


def finish_run(profile: Profile, run_id: str, status: str, summary: str = "") -> None:
    with get_session(profile) as session:
        run = session.exec(select(PipelineRun).where(PipelineRun.run_id == run_id)).first()
        if run:
            run.status = status
            run.finished_at = now_iso()
            run.summary = summary
            session.add(run)
            session.commit()
    log_activity(profile, f"Run finalizado com status={status}: {summary}", source="pipeline", run_id=run_id)


def record_step(
    profile: Profile,
    run_id: str,
    step_index: int,
    step_name: str,
    status: str,
    skill: str = "",
    detail: str = "",
) -> None:
    with get_session(profile) as session:
        step = PipelineStep(
            run_id=run_id,
            step_index=step_index,
            step_name=step_name,
            skill=skill,
            status=status,
            started_at=now_iso() if status == "running" else None,
            finished_at=now_iso() if status in {"success", "failed", "blocked", "skipped"} else None,
            detail=detail,
        )
        session.add(step)
        session.commit()
    log_activity(profile, f"[{step_index}] {step_name}: {status} - {detail}", source=skill or "pipeline", run_id=run_id)


def upsert_mapping(profile: Profile, domain: str, layer: str, source_table: str, target_table: str,
                    sql_file: str = "", schema_file: str = "", status: str = "manual_review", notes: str = "") -> None:
    with get_session(profile) as session:
        existing = session.exec(
            select(MappingRow).where(
                MappingRow.domain == domain,
                MappingRow.layer == layer,
                MappingRow.source_table == source_table,
                MappingRow.target_table == target_table,
            )
        ).first()
        if existing:
            existing.sql_file = sql_file
            existing.schema_file = schema_file
            existing.status = status
            existing.notes = notes
            existing.updated_at = now_iso()
            session.add(existing)
        else:
            session.add(MappingRow(
                domain=domain, layer=layer, source_table=source_table, target_table=target_table,
                sql_file=sql_file, schema_file=schema_file, status=status, notes=notes,
            ))
        session.commit()


def record_manifest(profile: Profile, manifest_id: str, resource_type: str, display_name: str,
                     environment: str, operation: str, stage: str, allow_write: bool,
                     confirm_write: bool, run_id: str = "", payload_path: str = "") -> None:
    with get_session(profile) as session:
        existing = session.exec(select(ManifestRecord).where(ManifestRecord.manifest_id == manifest_id)).first()
        if existing:
            existing.stage = stage
            existing.allow_write = allow_write
            existing.confirm_write = confirm_write
            existing.run_id = run_id or existing.run_id
            existing.updated_at = now_iso()
            existing.payload_path = payload_path or existing.payload_path
            session.add(existing)
        else:
            session.add(ManifestRecord(
                manifest_id=manifest_id, resource_type=resource_type, display_name=display_name,
                environment=environment, operation=operation, stage=stage, allow_write=allow_write,
                confirm_write=confirm_write, run_id=run_id, payload_path=payload_path,
            ))
        session.commit()


def register_ownership(profile: Profile, resource_type: str, resource_id: str, display_name: str,
                        owner: str = "dlctl-agent", delete_allowed: bool = True) -> None:
    with get_session(profile) as session:
        session.add(OwnershipRecord(
            resource_type=resource_type, resource_id=resource_id, display_name=display_name,
            owner=owner, delete_allowed=delete_allowed,
        ))
        session.commit()


def dump_evidence(profile: Profile, run_id: str, command: str, payload: dict) -> Path:
    """Grava um payload de evidência (JSON redigido) em state/evidence/<run_id>/<command>_<ts>.json."""
    run_dir = profile.paths.evidence_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    out_path = run_dir / f"{command}_{ts}.json"
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return out_path


# ==================== Backlog tracker (fabric-fullctl-backlog.zip) ====================

BACKLOG_SEED: list[dict] = [
    {"item_key": "pipelines-diagnose-run", "origin": "Incid. 1", "priority": "P0",
     "gap": "Sem comando tipado para atividades internas de pipeline; api request em queryactivityruns gerava payload enorme.",
     "proposal": "pipelines diagnose-run --item ID --run-id ID --failed-only (agrega erros, activityRunId, iterationHash, notebook run ID, Copy output, logs de controle).",
     "status": "aberta", "implemented_in_dlctl": "dlctl pipelines diagnose-run (offline, a partir de export JSON)"},
    {"item_key": "queryactivityruns-typed-read", "origin": "Incid. 1", "priority": "P0",
     "gap": "queryactivityruns é POST semanticamente read-only, mas o escape hatch tende a tratá-lo como mutação.",
     "proposal": "Registrar como leitura tipada, com redaction e resumo padrão.",
     "status": "aberta", "implemented_in_dlctl": "connectors/fabric_api.py::query_activity_runs (marcado como leitura, não passa por authorize_write)"},
    {"item_key": "pipelines-run-parameters", "origin": "Incid. 1", "priority": "P0",
     "gap": "pipelines run só aceita --execution-data bruto, sem validação.",
     "proposal": "--parameters, --plan, --dry-run, validação contra parâmetros da definição.",
     "status": "aberta", "implemented_in_dlctl": "dlctl execute plan/dry-run já valida parâmetros tipados (extensível)"},
    {"item_key": "copyjobs-oracle-number-audit", "origin": "Incid. 1", "priority": "P0",
     "gap": "Sem auditor semântico de mappings do Copy Job; 970 colunas Oracle NUMBER identificadas via script ad hoc.",
     "proposal": "copyjobs mappings-inspect e copyjobs oracle-number-audit, com manifest de casts e falha em coluna/tabela não mapeada.",
     "status": "aberta", "implemented_in_dlctl": "dlctl copyjobs mappings-inspect / oracle-number-audit"},
    {"item_key": "leases-lock-entre-agentes", "origin": "Incid. 1", "priority": "P0",
     "gap": "Sem lock entre agentes; exclusões de artefatos/tabelas controladas manualmente.",
     "proposal": "leases acquire/list/release --workspace --item-ids --tables --owner --ttl, integrado ao write gate.",
     "status": "aberta", "implemented_in_dlctl": "dlctl leases acquire/list/release + GateContext.authorize_write"},
    {"item_key": "sql-endpoint-refresh-route-fix", "origin": "Incid. 2", "priority": "P0",
     "gap": "Refresh do SQL endpoint usava rota obsoleta (jobType=RefreshSqlEndpointMetadata), 400 InvalidJobType.",
     "proposal": "Rota corrigida: POST /sqlEndpoints/{id}/refreshMetadata com {recreateTables: false}.",
     "status": "corrigida", "implemented_in_dlctl": "connectors/fabric_api.py::refresh_sql_endpoint_metadata (rota corrigida no código; NÃO testada ao vivo nesta sessão)"},
    {"item_key": "execute-campaign", "origin": "Incid. 2", "priority": "P0",
     "gap": "Sem orquestrador multi-alvo: publicar->executar->coletar logs->Delta->SQL endpoint->selar.",
     "proposal": "execute campaign consumindo manifesto multi-alvo, serial, zero replay de mutação, isolamento de falha por DAG.",
     "status": "aberta", "implemented_in_dlctl": "dlctl execute campaign + core/campaign.py"},
    {"item_key": "driver-log-wait", "origin": "Incid. 2", "priority": "P0",
     "gap": "driver-log é leitura única; pode retornar 404 unknown app antes da agregação existir.",
     "proposal": "jobs driver-log --wait --streams both, polling configurável, só repete o 404 exato, persiste tentativa+hash.",
     "status": "aberta", "implemented_in_dlctl": "dlctl jobs driver-log --wait (estrutura de polling; sem chamada real nesta sessão)"},
    {"item_key": "sql-endpoint-require-visible", "origin": "Incid. 2", "priority": "P0",
     "gap": "Refresh do endpoint trata HTTP 200 como sucesso mesmo com todas as tabelas em NotRun.",
     "proposal": "--require-visible --poll-seconds --timeout-seconds; 200 com NotRun/tabela omitida/pós-condição ausente não é ok.",
     "status": "aberta", "implemented_in_dlctl": "connectors/fabric_api.py::refresh_sql_endpoint_metadata(require_visible=True)"},
    {"item_key": "log-classifier-integration", "origin": "Incid. 2", "priority": "P0",
     "gap": "Classificador phase-aware de logs não está integrado à CLI.",
     "proposal": "Integrar; assinatura desconhecida sempre NEVER_PASS (bloqueia, não passa por default).",
     "status": "aberta", "implemented_in_dlctl": "core/log_classifier.py + dlctl jobs classify-log"},
    {"item_key": "lakehouses-where-filter", "origin": "Incid. 1", "priority": "P1",
     "gap": "lakehouses table-query/delta-read sem --where; exigiu ler 126 arquivos e filtrar depois.",
     "proposal": "Filtros de igualdade, --expect-row-count, comando dedicado ctrl-run-read --pipeline-run-id.",
     "status": "aberta", "implemented_in_dlctl": ""},
    {"item_key": "sql-endpoint-stale", "origin": "Incid. 1", "priority": "P1",
     "gap": "SQL endpoint retornou zero para logs recém-gravados enquanto o Delta já tinha os registros.",
     "proposal": "--wait-sql-sync, --fallback-delta, resultado explícito SQL_ENDPOINT_STALE.",
     "status": "aberta", "implemented_in_dlctl": ""},
    {"item_key": "pipelines-wait-resumable", "origin": "Incid. 1", "priority": "P1",
     "gap": "pipelines run --wait com timeout fixo de 1800s, sem retomada por run-id.",
     "proposal": "pipelines wait --run-id --timeout --poll-interval, retomável em processo separado.",
     "status": "aberta", "implemented_in_dlctl": "dlctl pipelines wait (estrutura; sem chamada real nesta sessão)"},
    {"item_key": "git-lro-no-result", "origin": "Incid. 1", "priority": "P1",
     "gap": "Git LRO concluído sem conteúdo: consulta a /result retorna OperationHasNoResult e é registrada como erro.",
     "proposal": "Não consultar /result quando a operação não tem conteúdo; tratar esse código como sucesso sem resultado.",
     "status": "aberta", "implemented_in_dlctl": "connectors/fabric_api.py (tratamento de OperationHasNoResult como sucesso)"},
    {"item_key": "git-plan-commit-item-ids", "origin": "Incid. 1", "priority": "P1",
     "gap": "git commit aceita --item-ids; git plan-commit não.",
     "proposal": "Adicionar seleção de itens ao planejamento, mostrando só o delta selecionado.",
     "status": "aberta", "implemented_in_dlctl": "dlctl git plan-commit --item-ids"},
    {"item_key": "lakehouses-reconcile-manifest", "origin": "Incid. 2", "priority": "P1",
     "gap": "Reconciliação não deriva o lakehouse automaticamente do manifesto.",
     "proposal": "lakehouses reconcile-manifest: resolve lakehouse/tabela/chaves/contagens, roda table-stats+aggregate, faz polling de sync.",
     "status": "aberta", "implemented_in_dlctl": ""},
    {"item_key": "expected-column-count-separation", "origin": "Incid. 2", "priority": "P1",
     "gap": "--expected-columns 7 é interpretado como nome de coluna, não quantidade.",
     "proposal": "Separar --expected-column-count 75 de --expected-columns col1,col2,...",
     "status": "aberta", "implemented_in_dlctl": ""},
    {"item_key": "onelake-schema-fallback", "origin": "Incid. 2", "priority": "P1",
     "gap": "Inventário REST de lakehouse com schemas habilitados retorna UnsupportedOperationForSchemasEnabledLakehouse.",
     "proposal": "Fallback OneLake recursivo.",
     "status": "parcial", "implemented_in_dlctl": ""},
    {"item_key": "parameter-canary", "origin": "Incid. 2", "priority": "P1",
     "gap": "Parâmetros enviados ao background job podem ser ignorados sem prova de round-trip.",
     "proposal": "Canary de parâmetros: provar antes da escrita que o notebook recebeu exatamente os parâmetros tipados.",
     "status": "aberta", "implemented_in_dlctl": ""},
    {"item_key": "gold-generators-contract-defects", "origin": "Incid. 2", "priority": "P1",
     "gap": "Geradores Gold não detectam alguns defeitos contratuais antes da publicação.",
     "proposal": "Parse Spark SQL, CTE duplicada, unicidade de chave natural, filtros view/JPAR, lakehouse destino.",
     "status": "aberta", "implemented_in_dlctl": "generators/validators.py (checagens adicionais de CTE duplicada e chave natural)"},
    {"item_key": "definitions-part-inspect", "origin": "Incid. 1", "priority": "P2",
     "gap": "Hash de definição ambíguo (agregado vs. payload Base64 vs. conteúdo decodificado).",
     "proposal": "definitions part inspect com aggregateDefinitionSha256, encodedPayloadSha256, decodedContentSha256 + resumo semântico.",
     "status": "aberta", "implemented_in_dlctl": "dlctl definitions part-inspect + core/definitions_inspect.py"},
    {"item_key": "notebooks-run-validation", "origin": "Incid. 1", "priority": "P2",
     "gap": "notebooks run --parameters não valida o envelope (NotebookBadWebRequest).",
     "proposal": "Validação local de tipos/estrutura + notebooks run --plan/--dry-run.",
     "status": "aberta", "implemented_in_dlctl": ""},
    {"item_key": "driver-log-extract-exit", "origin": "Incid. 1", "priority": "P2",
     "gap": "jobs driver-log mistura log Spark bruto com ruído de shutdown (InterruptedException pós-Completed).",
     "proposal": "--extract-notebook-exit, separando resultado funcional do ruído.",
     "status": "aberta", "implemented_in_dlctl": "core/log_classifier.py (separa ruído de shutdown conhecido)"},
    {"item_key": "pipeline-diagnostic-recipe", "origin": "Incid. 1", "priority": "P2",
     "gap": "Skill sem recipe de diagnóstico de pipeline completo.",
     "proposal": "Recipe: status -> atividades -> definição -> config -> logs -> watermark -> classificação -> relatório (sem rerun automático).",
     "status": "aberta", "implemented_in_dlctl": "dlctl pipelines diagnose-run agrega boa parte desta recipe offline"},
    {"item_key": "ownership-authorship-limitation", "origin": "Nota 3", "priority": "P2",
     "gap": "Endpoint comum de itens não expõe createdBy/modifiedBy; endpoint admin dá 403 InsufficientScopes.",
     "proposal": "Usar apenas trilhas auditáveis: Git (Added/Modified) + registro de ownership do fabric-fullctl + inventário atual.",
     "status": "nao_aplicavel", "implemented_in_dlctl": "core/state.py::OwnershipRecord já cobre isso; dashboard exibe a trilha combinada"},
]


def seed_backlog(profile: Profile) -> int:
    """Insere/atualiza o rastreio de lacunas do fabric-fullctl-backlog.zip.
    Idempotente: pode ser chamado a cada boot do dashboard sem duplicar linhas."""
    inserted = 0
    with get_session(profile) as session:
        for item in BACKLOG_SEED:
            existing = session.exec(select(BacklogItem).where(BacklogItem.item_key == item["item_key"])).first()
            if existing:
                existing.status = item["status"]
                existing.implemented_in_dlctl = item["implemented_in_dlctl"]
                session.add(existing)
            else:
                session.add(BacklogItem(**item))
                inserted += 1
        session.commit()
    return inserted


# ==================== Leases (lock leve entre agentes/execuções) ====================

def acquire_lease(profile: Profile, workspace: str, item_ids: list[str], tables: list[str],
                   owner: str, ttl_seconds: int = 3600) -> dict:
    """Adquire uma lease se não houver conflito ativo (mesmos item_ids/tables já
    detidos por outro owner). Retorna {ok, lease_id, conflict}."""
    from datetime import timedelta

    requested_items = set(item_ids)
    requested_tables = set(tables)
    with get_session(profile) as session:
        active = session.exec(select(Lease).where(Lease.status == "active")).all()
        now = datetime.now(timezone.utc)
        for lease in active:
            expires_at = datetime.fromisoformat(lease.acquired_at) + timedelta(seconds=lease.ttl_seconds)
            if now > expires_at:
                lease.status = "expired"
                session.add(lease)
                continue
            if lease.owner == owner:
                continue
            existing_items = set(lease.item_ids.split(",")) if lease.item_ids else set()
            existing_tables = set(lease.tables.split(",")) if lease.tables else set()
            if (requested_items & existing_items) or (requested_tables & existing_tables):
                session.commit()
                return {"ok": False, "conflict": lease.lease_id, "owner": lease.owner,
                        "message": f"Conflito com lease ativa '{lease.lease_id}' de '{lease.owner}'."}
        session.commit()

        lease_id = new_id("lease")
        with get_session(profile) as session2:
            session2.add(Lease(
                lease_id=lease_id, workspace=workspace, item_ids=",".join(item_ids),
                tables=",".join(tables), owner=owner, ttl_seconds=ttl_seconds,
            ))
            session2.commit()
    log_activity(profile, f"Lease adquirida: {lease_id} por {owner}", source="leases")
    return {"ok": True, "lease_id": lease_id}


def list_leases(profile: Profile, active_only: bool = True) -> list[dict]:
    with get_session(profile) as session:
        query = select(Lease)
        if active_only:
            query = query.where(Lease.status == "active")
        return [l.model_dump() for l in session.exec(query).all()]


def release_lease(profile: Profile, lease_id: str, owner: str) -> dict:
    with get_session(profile) as session:
        lease = session.exec(select(Lease).where(Lease.lease_id == lease_id)).first()
        if not lease:
            return {"ok": False, "message": "Lease não encontrada."}
        if lease.owner != owner:
            return {"ok": False, "message": f"Lease pertence a '{lease.owner}', não a '{owner}'."}
        lease.status = "released"
        lease.released_at = now_iso()
        session.add(lease)
        session.commit()
    log_activity(profile, f"Lease liberada: {lease_id} por {owner}", source="leases")
    return {"ok": True}


def has_conflicting_lease(profile: Profile, item_ids: list[str], tables: list[str], owner: str) -> Optional[str]:
    """Usado pelo GateContext.authorize_write: retorna o lease_id conflitante, se houver."""
    from datetime import timedelta

    requested_items = set(item_ids)
    requested_tables = set(tables)
    with get_session(profile) as session:
        active = session.exec(select(Lease).where(Lease.status == "active")).all()
        now = datetime.now(timezone.utc)
        for lease in active:
            expires_at = datetime.fromisoformat(lease.acquired_at) + timedelta(seconds=lease.ttl_seconds)
            if now > expires_at or lease.owner == owner:
                continue
            existing_items = set(lease.item_ids.split(",")) if lease.item_ids else set()
            existing_tables = set(lease.tables.split(",")) if lease.tables else set()
            if (requested_items & existing_items) or (requested_tables & existing_tables):
                return lease.lease_id
    return None


# ==================== Campaign (execute campaign multi-alvo) ====================

def start_campaign(profile: Profile, manifest_path: str) -> str:
    campaign_id = new_id("campaign")
    with get_session(profile) as session:
        session.add(CampaignRun(campaign_id=campaign_id, manifest_path=manifest_path))
        session.commit()
    log_activity(profile, f"Campaign iniciada: {campaign_id}", source="execute-campaign", run_id=campaign_id)
    return campaign_id


def finish_campaign(profile: Profile, campaign_id: str, status: str, summary: str = "") -> None:
    with get_session(profile) as session:
        c = session.exec(select(CampaignRun).where(CampaignRun.campaign_id == campaign_id)).first()
        if c:
            c.status = status
            c.finished_at = now_iso()
            c.summary = summary
            session.add(c)
            session.commit()
    log_activity(profile, f"Campaign finalizada: {campaign_id} status={status} {summary}", source="execute-campaign", run_id=campaign_id)


def record_campaign_step(profile: Profile, campaign_id: str, target: str, phase: str, status: str, detail: str = "") -> None:
    with get_session(profile) as session:
        session.add(CampaignStep(campaign_id=campaign_id, target=target, phase=phase, status=status, detail=detail))
        session.commit()
    log_activity(profile, f"[{target}/{phase}] {status}: {detail}", source="execute-campaign", run_id=campaign_id)


# ==================== Command invocation tracking (retro: skill-featured-unused) ====================

def log_command_invocation(profile: Profile, command: str, argv: str = "") -> None:
    with get_session(profile) as session:
        session.add(CommandInvocation(command=command, argv=argv))
        session.commit()


def list_command_invocations(profile: Profile, since: Optional[str] = None) -> list[dict]:
    with get_session(profile) as session:
        query = select(CommandInvocation)
        if since:
            query = query.where(CommandInvocation.timestamp >= since)
        return [c.model_dump() for c in session.exec(query).all()]


# ==================== Item cache (retro: prefer-resolver) ====================

def cache_item(profile: Profile, workspace_id: str, item_type: str, display_name: str, item_id: str) -> None:
    with get_session(profile) as session:
        existing = session.exec(
            select(ItemCache).where(
                ItemCache.workspace_id == workspace_id, ItemCache.item_type == item_type,
                ItemCache.display_name == display_name,
            )
        ).first()
        if existing:
            existing.item_id = item_id
            existing.cached_at = now_iso()
            session.add(existing)
        else:
            session.add(ItemCache(workspace_id=workspace_id, item_type=item_type,
                                   display_name=display_name, item_id=item_id))
        session.commit()


def get_cached_item(profile: Profile, workspace_id: str, item_type: str, display_name: str,
                     max_age_seconds: int = 300) -> Optional[str]:
    from datetime import timedelta

    with get_session(profile) as session:
        existing = session.exec(
            select(ItemCache).where(
                ItemCache.workspace_id == workspace_id, ItemCache.item_type == item_type,
                ItemCache.display_name == display_name,
            )
        ).first()
        if not existing:
            return None
        cached_at = datetime.fromisoformat(existing.cached_at)
        if datetime.now(timezone.utc) - cached_at > timedelta(seconds=max_age_seconds):
            return None
        return existing.item_id


def list_cached_items(profile: Profile) -> list[dict]:
    with get_session(profile) as session:
        return [i.model_dump() for i in session.exec(select(ItemCache)).all()]


# ==================== Retro proposals (Improvement Proposals engine) ====================

def upsert_retro_proposal(profile: Profile, proposal_key: str, category: str, risk: str, title: str,
                           signal: str, evidence: dict, affected: str, proposal_text: str,
                           count: int, first_ts: str, last_ts: str, gate_change: bool = False) -> None:
    """Idempotente: regenerar a análise atualiza contagem/evidência mas NUNCA
    sobrescreve uma decisão humana já registrada (approved/rejected/applied)."""
    with get_session(profile) as session:
        existing = session.exec(select(RetroProposal).where(RetroProposal.proposal_key == proposal_key)).first()
        if existing:
            existing.count = count
            existing.first_ts = first_ts
            existing.last_ts = last_ts
            existing.evidence_json = json.dumps(evidence, ensure_ascii=False, default=str)
            existing.updated_at = now_iso()
            session.add(existing)
        else:
            session.add(RetroProposal(
                proposal_key=proposal_key, category=category, risk=risk, title=title, signal=signal,
                evidence_json=json.dumps(evidence, ensure_ascii=False, default=str), affected=affected,
                proposal_text=proposal_text, count=count, first_ts=first_ts, last_ts=last_ts,
                gate_change=gate_change,
            ))
        session.commit()


def list_retro_proposals(profile: Profile, category: Optional[str] = None, risk: Optional[str] = None,
                          status: Optional[str] = None) -> list[dict]:
    with get_session(profile) as session:
        query = select(RetroProposal)
        if category:
            query = query.where(RetroProposal.category == category)
        if risk:
            query = query.where(RetroProposal.risk == risk)
        if status:
            query = query.where(RetroProposal.status == status)
        rows = session.exec(query.order_by(RetroProposal.count.desc())).all()
        return [r.model_dump() for r in rows]


def set_retro_status(profile: Profile, proposal_key: str, status: str) -> bool:
    with get_session(profile) as session:
        existing = session.exec(select(RetroProposal).where(RetroProposal.proposal_key == proposal_key)).first()
        if not existing:
            return False
        existing.status = status
        existing.updated_at = now_iso()
        session.add(existing)
        session.commit()
    log_activity(profile, f"Retro proposal '{proposal_key}' marcada como '{status}'", source="retro")
    return True

