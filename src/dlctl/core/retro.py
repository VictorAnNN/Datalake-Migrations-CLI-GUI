"""dlctl.core.retro

Motor de "Improvement Proposals (retro)": analisa a telemetria do próprio
dlctl (ActivityLog, PipelineStep, ManifestRecord, CampaignStep,
CommandInvocation) e gera propostas de melhoria categorizadas, no mesmo
formato do relatório de retro usado para outras ferramentas (msauthctl,
teamsctl, fabricctl, etc.):

- **repeated-failure**: o mesmo comando/passo falha repetidamente com a
  mesma "forma" de erro -> falta doc de precondição ou a CLI deveria falhar
  mais cedo com mensagem mais clara.
- **throttling**: retries/throttle concentrados em uma superfície -> considerar
  batching/backoff.
- **gate-friction**: recusas repetidas de um gate de segurança -> o gate está
  funcionando corretamente; a proposta é só tornar a precondição/flag mais
  visível. NUNCA é uma proposta para enfraquecer o gate (marcado com
  `gate_change=True` e reforçado no relatório).
- **prefer-resolver**: lookups ao vivo repetidos quando existe um resolver
  cache-first (`resolve_item_cached`) -> reforçar uso do cache.
- **skill-featured-unused**: comandos registrados no CLI mas nunca invocados
  na janela -> candidatos a mover para documentação de referência (dieta).
- **permission-gap**: profile com escrita desabilitada mas tentativas
  repetidas -> decisão humana sobre habilitar ou não.

Todas as propostas são persistidas via `dlctl.core.state.upsert_retro_proposal`
(idempotente — nunca sobrescreve uma decisão humana já registrada) e o
fluxo de aprovação é manual (Stage B): nada aqui aplica mudança sozinho.
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlmodel import select

from dlctl.config import Profile
from dlctl.core.state import (
    ActivityLog,
    CampaignStep,
    CommandInvocation,
    PipelineStep,
    get_session,
    list_retro_proposals,
    set_retro_status,
    upsert_retro_proposal,
)

_UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_NUM_RE = re.compile(r"\b\d+\b")
_QUOTED_RE = re.compile(r"'[^']*'|\"[^\"]*\"")


def normalize_error_shape(message: str) -> str:
    """Reduz uma mensagem de erro à sua 'forma' genérica, removendo IDs,
    números e valores entre aspas — equivalente ao `errorShape` do retro
    original (ex.: 'HTTP <n> retry <n>/<n> after <n>s')."""
    s = _UUID_RE.sub("<uuid>", message)
    s = _QUOTED_RE.sub("<v>", s)
    s = _NUM_RE.sub("<n>", s)
    return s.strip()[:140]


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def analyze(
    profile: Profile,
    window_days: int = 90,
    min_count: int = 3,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> dict:
    """Roda todos os detectores e persiste as propostas encontradas.
    Retorna um resumo {window, event_count, proposals: [...]}."""
    now = datetime.now(timezone.utc)
    window_start = _parse_ts(since) if since else now - timedelta(days=window_days)
    window_end = _parse_ts(until) if until else now

    with get_session(profile) as session:
        activity_rows = session.exec(select(ActivityLog)).all()
        step_rows = session.exec(select(PipelineStep)).all()
        campaign_rows = session.exec(select(CampaignStep)).all()
        invocation_rows = session.exec(select(CommandInvocation)).all()

    def in_window(ts: str) -> bool:
        try:
            t = _parse_ts(ts)
        except ValueError:
            return True
        return window_start <= t <= window_end

    activity_rows = [a for a in activity_rows if in_window(a.timestamp)]
    step_rows = [s for s in step_rows if s.finished_at and in_window(s.finished_at)]
    campaign_rows = [c for c in campaign_rows if in_window(c.timestamp)]
    invocation_rows = [c for c in invocation_rows if in_window(c.timestamp)]

    proposals: list[dict] = []

    # ---------------- gate-friction + repeated-failure (via ActivityLog) ----------------
    groups: dict[tuple[str, str], list[ActivityLog]] = defaultdict(list)
    throttle_events: list[ActivityLog] = []
    cache_hits: list[ActivityLog] = []
    cache_live: list[ActivityLog] = []

    for a in activity_rows:
        if a.source == "fabric_api.retry":
            throttle_events.append(a)
            continue
        if a.source == "fabric_api.cache":
            (cache_hits if a.message.startswith("cache hit") else cache_live).append(a)
            continue
        if a.level in {"ERROR", "BLOCKED"}:
            groups[(a.source, normalize_error_shape(a.message))].append(a)

    for (source, shape), rows in groups.items():
        if len(rows) < min_count:
            continue
        is_gate = source.startswith("gates.")
        category = "gate-friction" if is_gate else "repeated-failure"
        risk = "gate-change" if is_gate else ("doc-only" if "manual_required" in shape or "allow_write" in shape else "cli-behavior")
        method = source.split(".", 1)[1] if is_gate else source
        # chave curta e ASCII-safe (hash da forma do erro) — chaves com acentos/
        # texto longo são impraticáveis de digitar em `dlctl retro approve --key`;
        # o dashboard mostra o título completo e usa botões (sem digitação).
        shape_hash = hashlib.sha256(shape.encode("utf-8")).hexdigest()[:10]
        key = f"{category}:{source}:{shape_hash}"
        title = f"'{method}' {'recusado pelo gate' if is_gate else 'falhou'} {len(rows)}x com a mesma forma"
        if is_gate:
            affected = f"documentação do gate '{method}' (NÃO é proposta para enfraquecer o gate)"
            proposal_text = (
                f"'{method}' foi recusado pelo gate {len(rows)}x — o gate está funcionando; torne as "
                "flags/preconditions exigidas mais visíveis para que os agentes parem de tentar sem elas. "
                "Releia a regra de segurança antes de qualquer mudança."
            )
        else:
            affected = f"tratamento de erro / documentação de precondição de '{source}'"
            proposal_text = (
                f"'{source}' falhou {len(rows)}x com a mesma forma de erro — falta documentar a precondição "
                "ou a CLI deveria falhar mais cedo com uma mensagem mais clara."
            )
        upsert_retro_proposal(
            profile, proposal_key=key, category=category, risk=risk, title=title,
            signal="repeated exit/refusal with the same error shape",
            evidence={"source": source, "errorShape": shape, "count": len(rows),
                      "firstTs": rows[0].timestamp, "lastTs": rows[-1].timestamp},
            affected=affected, proposal_text=proposal_text, count=len(rows),
            first_ts=rows[0].timestamp, last_ts=rows[-1].timestamp, gate_change=is_gate,
        )
        proposals.append({"key": key, "category": category, "risk": risk, "count": len(rows)})

    # ---------------- repeated-failure via PipelineStep/CampaignStep ----------------
    step_groups: dict[tuple[str, str], list] = defaultdict(list)
    for s in step_rows:
        if s.status != "failed":
            continue
        step_groups[(s.skill or "pipeline", normalize_error_shape(s.detail))].append(s)
    for c in campaign_rows:
        if c.status != "failed":
            continue
        step_groups[(f"campaign:{c.phase}", normalize_error_shape(c.detail))].append(c)

    for (source, shape), rows in step_groups.items():
        if len(rows) < min_count:
            continue
        shape_hash = hashlib.sha256(shape.encode("utf-8")).hexdigest()[:10]
        key = f"repeated-failure:{source}:{shape_hash}"
        title = f"'{source}' falhou {len(rows)}x com o mesmo detalhe"
        ts_first = getattr(rows[0], "finished_at", None) or getattr(rows[0], "timestamp", "")
        ts_last = getattr(rows[-1], "finished_at", None) or getattr(rows[-1], "timestamp", "")
        upsert_retro_proposal(
            profile, proposal_key=key, category="repeated-failure", risk="cli-behavior", title=title,
            signal="repeated step failure with the same detail shape",
            evidence={"source": source, "errorShape": shape, "count": len(rows), "firstTs": ts_first, "lastTs": ts_last},
            affected=f"geradores/validações relacionadas a '{source}'",
            proposal_text=f"'{source}' falhou {len(rows)}x com o mesmo detalhe — considere um gate/validação local que capture isso antes da geração/publicação.",
            count=len(rows), first_ts=ts_first, last_ts=ts_last, gate_change=False,
        )
        proposals.append({"key": key, "category": "repeated-failure", "risk": "cli-behavior", "count": len(rows)})

    # ---------------- throttling ----------------
    if len(throttle_events) >= min_count:
        key = "throttling:fabric_api"
        upsert_retro_proposal(
            profile, proposal_key=key, category="throttling", risk="cli-behavior",
            title=f"fabric_api sofreu throttling/retry {len(throttle_events)}x na janela",
            signal="throttle/retry events clustering on one surface",
            evidence={"throttleEvents": len(throttle_events), "tool": "fabric_api"},
            affected="fabric_api throttle policy / batching",
            proposal_text=f"fabric_api sofreu sinais de throttling {len(throttle_events)}x na janela — considere batching ou ajuste de backoff.",
            count=len(throttle_events), first_ts=throttle_events[0].timestamp, last_ts=throttle_events[-1].timestamp,
        )
        proposals.append({"key": key, "category": "throttling", "risk": "cli-behavior", "count": len(throttle_events)})

    # ---------------- prefer-resolver ----------------
    if len(cache_live) >= min_count and len(cache_live) > len(cache_hits):
        key = "prefer-resolver:fabric-items"
        upsert_retro_proposal(
            profile, proposal_key=key, category="prefer-resolver", risk="doc-only",
            title=f"{len(cache_live)} lookups ao vivo vs {len(cache_hits)} cache hits",
            signal="repeated live lookups where a cache-first resolver exists",
            evidence={"liveLookups": len(cache_live), "cacheHits": len(cache_hits), "resolverHint": "resolve_item_cached / dlctl inventory cache"},
            affected="uso de resolve_item_cached em manifest/execute/campaign",
            proposal_text=f"Resolução de itens Fabric rodou {len(cache_live)}x ao vivo vs {len(cache_hits)}x via cache — reforçar cache-first (`resolve_item_cached`) nos fluxos que chamam find_item_by_name diretamente.",
            count=len(cache_live), first_ts=cache_live[0].timestamp, last_ts=cache_live[-1].timestamp,
        )
        proposals.append({"key": key, "category": "prefer-resolver", "risk": "doc-only", "count": len(cache_live)})

    # ---------------- skill-featured-unused ----------------
    registered = _list_registered_commands()
    invoked = {c.command for c in invocation_rows}
    unused = sorted(registered - invoked)
    if unused:
        key = "skill-featured-unused:dlctl"
        upsert_retro_proposal(
            profile, proposal_key=key, category="skill-featured-unused", risk="doc-only",
            title=f"{len(unused)} comando(s) registrados nunca invocados na janela",
            signal="commands featured in the CLI but unused in the window",
            evidence={"sample": unused[:15], "total": len(unused)},
            affected="candidatos a dieta de comandos (mover para referência/depreciar)",
            proposal_text=f"{len(unused)} comando(s) do dlctl nunca foram usados na janela — revisar se ainda merecem destaque ou se devem virar referência.",
            count=len(unused), first_ts=window_start.isoformat(), last_ts=window_end.isoformat(),
        )
        proposals.append({"key": key, "category": "skill-featured-unused", "risk": "doc-only", "count": len(unused)})

    # ---------------- permission-gap ----------------
    allow_write_refusals = [
        a for a in activity_rows
        if a.level == "BLOCKED" and a.source == "gates.authorize_write" and "allow_write=false" in a.message
    ]
    if not profile.microsoft.allow_write and len(allow_write_refusals) >= min_count:
        key = f"permission-gap:{profile.name}"
        upsert_retro_proposal(
            profile, proposal_key=key, category="permission-gap", risk="doc-only",
            title=f"profile '{profile.name}' tem escrita desabilitada e foi tentada {len(allow_write_refusals)}x",
            signal="recurring blocked writes due to profile allow_write=false",
            evidence={"profile": profile.name, "refusals": len(allow_write_refusals)},
            affected="decisão humana: habilitar allow_write para este profile ou não",
            proposal_text=f"Profile '{profile.name}' teve {len(allow_write_refusals)} tentativas de escrita bloqueadas por allow_write=false — decida se vale habilitar (config/profiles.yaml) ou manter assim; os gates já falham fechado corretamente.",
            count=len(allow_write_refusals), first_ts=allow_write_refusals[0].timestamp, last_ts=allow_write_refusals[-1].timestamp,
        )
        proposals.append({"key": key, "category": "permission-gap", "risk": "doc-only", "count": len(allow_write_refusals)})

    return {
        "window_start": window_start.isoformat(), "window_end": window_end.isoformat(),
        "event_count": len(activity_rows), "proposal_count": len(proposals), "proposals": proposals,
    }


def _list_registered_commands() -> set[str]:
    """Introspecta a árvore de comandos Typer/Click do dlctl (import tardio
    para evitar import circular: core.retro é importado por commands.retro_cmds,
    que é registrado em cli.py)."""
    import typer

    from dlctl.cli import app as root_app

    click_group = typer.main.get_command(root_app)
    commands: set[str] = set()

    def walk(group, prefix: str = ""):
        for name, cmd in getattr(group, "commands", {}).items():
            path = f"{prefix} {name}".strip()
            if hasattr(cmd, "commands"):
                walk(cmd, path)
            else:
                commands.add(path)

    walk(click_group)
    return commands


def render_markdown_report(profile: Profile, summary: dict) -> str:
    """Gera o relatório markdown no mesmo formato do retro original."""
    proposals = list_retro_proposals(profile)
    lines = [
        "# Improvement Proposals (retro)",
        "",
        f"Window: {summary['window_start']} .. {summary['window_end']} | "
        f"events: {summary['event_count']} | proposals: {len(proposals)}",
        "",
    ]
    for p in sorted(proposals, key=lambda x: -x["count"]):
        badge = " ⚠ GATE-CHANGE: re-read the affected safety rule before approving" if p["gate_change"] else ""
        lines.append(f"## {p['category']}:{p['proposal_key'].split(':', 1)[1]} (count {p['count']}, risk {p['risk']}){badge}")
        lines.append("")
        lines.append(f"- signal: {p['signal']}")
        lines.append(f"- evidence: `{p['evidence_json']}`")
        lines.append(f"- affected: {p['affected']}")
        lines.append(f"- status: {p['status']}")
        lines.append(f"- proposal: {p['proposal_text']}")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("Stage B: manual_required — apply only user-approved items through the normal edit -> tests -> sync pipeline.")
    return "\n".join(lines)


def approve_proposal(profile: Profile, proposal_key: str) -> bool:
    return set_retro_status(profile, proposal_key, "approved")


def reject_proposal(profile: Profile, proposal_key: str) -> bool:
    return set_retro_status(profile, proposal_key, "rejected")
