"""dlctl.core.mapping

Registry de mapeamento Bronze->Silver e Silver->Gold. Lê um CSV local
(mappings/*.csv) e produz relatórios de inventário (json/markdown),
aplicando os "Status Gates" definidos em etl-oracle-fabric/SKILL.md e os
"Gold Gates" de etl-oracle-fabric-gold/SKILL.md.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

from dlctl.config import Profile
from dlctl.core.state import upsert_mapping

# Status permitidos para gerar notebooks Silver (etl-oracle-fabric)
SILVER_GO_STATUSES = {"spark_ready", "needs_rewrite"}
SILVER_STOP_STATUSES = {
    "manual_review", "missing_sql", "missing_tab", "missing_silver_table", "no_go_for_productive_batch",
}

GOLD_GO_STATUSES = {"spark_ready", "needs_rewrite"}
GOLD_STOP_STATUSES = {"manual_review", "missing_sql", "missing_view", "no_go"}


@dataclass
class MappingEntry:
    domain: str
    layer: str  # bronze_to_silver | silver_to_gold
    source_table: str
    target_table: str
    sql_file: str = ""
    schema_file: str = ""
    status: str = "manual_review"
    notes: str = ""

    @property
    def is_go(self) -> bool:
        gates = SILVER_GO_STATUSES if self.layer == "bronze_to_silver" else GOLD_GO_STATUSES
        return self.status in gates

    @property
    def stop_reason(self) -> str | None:
        stop_set = SILVER_STOP_STATUSES if self.layer == "bronze_to_silver" else GOLD_STOP_STATUSES
        return self.status if self.status in stop_set else None


def _csv_path(profile: Profile, layer: str) -> Path:
    name = "bronze_to_silver.csv" if layer == "bronze_to_silver" else "silver_to_gold.csv"
    return profile.paths.mappings_root / name


def load_mapping(profile: Profile, layer: str, domain: str | None = None) -> list[MappingEntry]:
    path = _csv_path(profile, layer)
    if not path.exists():
        return []
    entries: list[MappingEntry] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if domain and row.get("domain", "").strip() != domain:
                continue
            entries.append(MappingEntry(
                domain=row.get("domain", "").strip(),
                layer=layer,
                source_table=row.get("source_table", "").strip(),
                target_table=row.get("target_table", "").strip(),
                sql_file=row.get("sql_file", "").strip(),
                schema_file=row.get("schema_file", "").strip(),
                status=row.get("status", "manual_review").strip() or "manual_review",
                notes=row.get("notes", "").strip(),
            ))
    return entries


def sync_mapping_to_state(profile: Profile, entries: list[MappingEntry]) -> None:
    for e in entries:
        upsert_mapping(
            profile, domain=e.domain, layer=e.layer, source_table=e.source_table,
            target_table=e.target_table, sql_file=e.sql_file, schema_file=e.schema_file,
            status=e.status, notes=e.notes,
        )


def build_inventory(profile: Profile, layer: str, domain: str | None = None) -> dict:
    entries = load_mapping(profile, layer, domain=domain)
    sync_mapping_to_state(profile, entries)
    by_status: dict[str, int] = {}
    for e in entries:
        by_status[e.status] = by_status.get(e.status, 0) + 1
    go_count = sum(1 for e in entries if e.is_go)
    return {
        "layer": layer,
        "domain": domain or "ALL",
        "total": len(entries),
        "go_count": go_count,
        "blocked_count": len(entries) - go_count,
        "by_status": by_status,
        "entries": [e.__dict__ for e in entries],
    }


def write_inventory_report(profile: Profile, layer: str, domain: str | None, json_path: Path | None = None,
                            markdown_path: Path | None = None) -> dict:
    inv = build_inventory(profile, layer, domain=domain)
    reports_dir = profile.paths.state_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = json_path or reports_dir / f"inventory_{layer}_{domain or 'all'}.json"
    markdown_path = markdown_path or reports_dir / f"inventory_{layer}_{domain or 'all'}.md"

    json_path.write_text(json.dumps(inv, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        f"# Inventário {layer} — domínio {domain or 'ALL'}",
        "",
        f"Total: {inv['total']} | GO: {inv['go_count']} | Bloqueados: {inv['blocked_count']}",
        "",
        "| status | quantidade |",
        "|---|---|",
    ]
    for status, count in sorted(inv["by_status"].items()):
        lines.append(f"| {status} | {count} |")
    lines.append("")
    lines.append("| source_table | target_table | status | sql_file |")
    lines.append("|---|---|---|---|")
    for e in inv["entries"]:
        lines.append(f"| {e['source_table']} | {e['target_table']} | {e['status']} | {e['sql_file']} |")
    markdown_path.write_text("\n".join(lines), encoding="utf-8")

    inv["json_path"] = str(json_path)
    inv["markdown_path"] = str(markdown_path)
    return inv


def reconcile_scope(profile: Profile, layer: str, domain: str | None, allowed_source_tables: set[str] | None = None) -> dict:
    """Verifica se os targets dependem apenas das tabelas fonte permitidas
    (ex.: as 24 Bronze extraídas do Order Tracking). Marca 'blocked' quando não."""
    entries = load_mapping(profile, layer, domain=domain)
    blocked = []
    ok = []
    for e in entries:
        if allowed_source_tables is not None and e.source_table not in allowed_source_tables:
            blocked.append({"target": e.target_table, "source": e.source_table, "reason": "fora do escopo permitido"})
        elif e.stop_reason:
            blocked.append({"target": e.target_table, "source": e.source_table, "reason": e.stop_reason})
        else:
            ok.append(e.target_table)
    verdict = "go" if not blocked else ("partial_go" if ok else "no_go")
    return {"verdict": verdict, "go_targets": ok, "blocked": blocked}
