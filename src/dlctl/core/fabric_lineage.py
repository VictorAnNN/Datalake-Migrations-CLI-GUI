"""Read-only enrichment of static lineage with bounded Fabric evidence."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote


_RUN_TIMESTAMP = re.compile(r"fabric_full_(\d{8}T\d{6}Z)_")
_ONELAKE_URL = re.compile(
    r"/([^/]+)/([^/]+)\.lakehouse/Tables/([^?]+)\?", re.IGNORECASE,
)
_CANONICAL_STATUSES = {
    "ORFAO_SEM_ARESTA", "PARCIAL_SEM_DASHBOARD", "COMPLETO",
    "COMPLETO_DIRETO", "CANDIDATO_BAIXA_CONFIANCA",
}
_DOMAIN_LAKEHOUSE = {
    "CONTROLADORIA": "LH_CONTROLADORIA",
    "FINANCEIRO": "LH_FINANCEIRO",
    "MASTER DATA": "LH_MASTER_DATA",
    "OPERACAO": "LH_OPERACAO",
    "QSMS": "LH_QSMS",
    "RH": "LH_RH",
    "SUPRIMENTOS": "LH_SUPRIMENTOS",
    "TI": "LH_TI",
}


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _name_key(value: str) -> str:
    plain = "".join(
        char for char in unicodedata.normalize("NFKD", str(value or ""))
        if not unicodedata.combining(char)
    ).casefold()
    return re.sub(r"[^a-z0-9]+", " ", plain).strip()


def _table_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").casefold()).strip("_")


def _domain_key(value: str) -> str:
    plain = "".join(
        char for char in unicodedata.normalize("NFKD", str(value or ""))
        if not unicodedata.combining(char)
    )
    return " ".join(plain.upper().split())


def _snapshot_payload(snapshot_path: Path) -> dict:
    payload = _read_json(snapshot_path)
    snapshot = payload.get("snapshot", payload)
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("items"), list):
        raise ValueError("Snapshot Fabric inválido: coleção 'items' ausente.")
    if not snapshot.get("collectedAt"):
        raise ValueError("Snapshot Fabric inválido: 'collectedAt' ausente.")
    return snapshot


def _run_timestamp(path: Path) -> datetime | None:
    match = _RUN_TIMESTAMP.search(path.parent.name)
    if not match:
        return None
    return datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def _discover_onelake_tables(
    evidence_root: Path,
    *,
    workspace_name: str,
    collected_at: datetime,
    window_minutes: int,
) -> tuple[dict[str, list[dict]], list[Path]]:
    """Load only schema listings captured shortly after the selected snapshot."""
    latest_by_url: dict[str, tuple[datetime, Path, dict]] = {}
    upper_bound = collected_at + timedelta(minutes=window_minutes)
    for path in evidence_root.glob("fabric_full_*_onelake-list_*/onelake_list.json"):
        run_at = _run_timestamp(path)
        if run_at is None or not (collected_at <= run_at <= upper_bound):
            continue
        payload = _read_json(path)
        url = unquote(str(payload.get("url", "")))
        match = _ONELAKE_URL.search(url)
        if not match or match.group(1).casefold() != workspace_name.casefold():
            continue
        # A URL sem schema lista apenas os diretórios bronze/silver/gold;
        # ela não constitui evidência da existência de uma tabela.
        schema = match.group(3).strip("/")
        if not schema or "/" in schema:
            continue
        current = latest_by_url.get(url)
        if current is None or run_at > current[0]:
            latest_by_url[url] = (run_at, path, payload)

    locations: dict[str, list[dict]] = defaultdict(list)
    selected_files: list[Path] = []
    for url, (run_at, path, payload) in sorted(latest_by_url.items()):
        match = _ONELAKE_URL.search(url)
        if not match:
            continue
        lakehouse, schema = match.group(2), match.group(3).strip("/")
        selected_files.append(path)
        for entry in payload.get("response", {}).get("paths", []):
            full_name = str(entry.get("name", "")).rstrip("/")
            table = full_name.rsplit("/", 1)[-1]
            if not table or table.casefold() == schema.casefold():
                continue
            locations[_table_key(table)].append({
                "workspace": workspace_name,
                "lakehouse": lakehouse,
                "schema": schema,
                "table": table,
                "path": f"{lakehouse}.{schema}.{table}",
                "last_modified": entry.get("lastModified", ""),
                "evidence_run": path.parent.name,
                "evidence_collected_at": run_at.isoformat(),
            })
    return dict(locations), selected_files


def _item_index(items: list[dict], item_type: str) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        if str(item.get("type", "")).casefold() != item_type.casefold():
            continue
        index[_name_key(item.get("displayName", ""))].append(item)
    return dict(index)


def _notebook_candidates(table: str, notebooks: list[dict]) -> list[dict]:
    """Nominal candidates only; short labels are intentionally not guessed."""
    table_key = _table_key(table)
    if len(table_key) < 5:
        return []
    token = re.compile(rf"(?:^|_){re.escape(table_key)}(?:_|$)")
    candidates = [item for item in notebooks if token.search(_table_key(item.get("displayName", "")))]
    return sorted(candidates, key=lambda item: str(item.get("displayName", "")).casefold())


def enrich_dashboard_lineage_with_fabric(
    result: dict,
    *,
    snapshot_path: str | Path,
    onelake_evidence_root: str | Path,
    workspace_name: str = "LAKEHOUSE-DEV",
    evidence_window_minutes: int = 10,
) -> dict:
    """Cross static rows with one immutable inventory and its OneLake listings.

    This proves observed publication/presence only. It never claims execution,
    freshness, column contract, semantic relationships or visual correctness.
    """
    snapshot_path = Path(snapshot_path)
    evidence_root = Path(onelake_evidence_root)
    if evidence_window_minutes <= 0:
        raise ValueError("evidence_window_minutes deve ser positivo.")
    snapshot = _snapshot_payload(snapshot_path)
    collected_at = datetime.fromisoformat(str(snapshot["collectedAt"]).replace("Z", "+00:00"))
    if collected_at.tzinfo is None:
        collected_at = collected_at.replace(tzinfo=timezone.utc)

    physical_by_table, evidence_files = _discover_onelake_tables(
        evidence_root,
        workspace_name=workspace_name,
        collected_at=collected_at,
        window_minutes=evidence_window_minutes,
    )
    if not evidence_files:
        raise ValueError("Nenhuma listagem OneLake compatível com o snapshot foi localizada.")

    enriched = copy.deepcopy(result)
    items = list(snapshot.get("items", []))
    folders = {folder.get("id"): folder for folder in snapshot.get("folders", [])}
    lakehouses = {
        str(item.get("displayName", "")).casefold(): item
        for item in items if str(item.get("type", "")).casefold() == "lakehouse"
    }
    reports_by_name = _item_index(items, "Report")
    models_by_name = _item_index(items, "SemanticModel")
    notebooks = [item for item in items if str(item.get("type", "")).casefold() == "notebook"]

    associations: dict[str, list[dict]] = defaultdict(list)
    for association in enriched.get("mapping_dashboard_rows", []):
        associations[_table_key(association.get("tabela_mapeada", ""))].append(association)

    static_fabric: dict[str, Counter] = defaultdict(Counter)
    divergences: list[dict] = []
    absent_by_domain: Counter = Counter()
    canonical_total = found_total = expected_total = cross_total = notebook_total = 0
    e2e_total = e2e_found = 0

    for row in enriched.get("end_to_end_mapping_rows", []):
        table = str(row.get("tabela_mapeada", ""))
        table_key = _table_key(table)
        canonical = row.get("status_fim_a_fim") in _CANONICAL_STATUSES
        expected_lakehouse = _DOMAIN_LAKEHOUSE.get(_domain_key(row.get("dominio", "")), "")
        expected_layers = {
            layer.strip().casefold() for layer in str(row.get("camada_mapeada", "")).split(",")
            if layer.strip()
        }
        locations = list(physical_by_table.get(table_key, [])) if canonical else []
        for location in locations:
            lakehouse_item = lakehouses.get(location["lakehouse"].casefold(), {})
            location["lakehouse_id"] = lakehouse_item.get("id", "")
        expected_locations = [
            location for location in locations
            if (not expected_lakehouse or location["lakehouse"].casefold() == expected_lakehouse.casefold())
            and (not expected_layers or location["schema"].casefold() in expected_layers)
        ]

        if not canonical:
            fabric_status = "NÃO APLICÁVEL"
            fabric_reason = "Entrada não canônica; não foi comparada como tabela física."
        elif expected_locations:
            fabric_status = "NO LOCAL ESPERADO"
            fabric_reason = "Tabela nominal observada na camada e no Lakehouse esperados."
            found_total += 1
            expected_total += 1
        elif locations:
            fabric_status = "OUTRO DOMÍNIO/CAMADA"
            actual = ", ".join(location["path"] for location in locations)
            expected = ".".join(part for part in (expected_lakehouse, "/".join(sorted(expected_layers)), table) if part)
            fabric_reason = f"Esperado {expected or 'local não definido'}; observado {actual}."
            found_total += 1
            cross_total += 1
            divergences.append({
                "table": table,
                "domain": row.get("dominio", ""),
                "expected": expected,
                "observed": actual,
            })
        else:
            fabric_status = "NÃO ENCONTRADO"
            expected = ".".join(part for part in (expected_lakehouse, "/".join(sorted(expected_layers)), table) if part)
            fabric_reason = (
                f"Nenhuma ocorrência nominal nas listagens OneLake selecionadas; esperado {expected}."
                if expected else
                "Nenhuma ocorrência nominal e mapping sem Lakehouse/camada esperados suficientes."
            )
            absent_by_domain[row.get("dominio") or "Sem domínio"] += 1

        candidates = _notebook_candidates(table, notebooks) if canonical else []
        if candidates:
            notebook_total += 1
        candidate_names = [str(item.get("displayName", "")) for item in candidates]
        candidate_ids = [str(item.get("id", "")) for item in candidates]
        candidate_paths = [
            str(folders.get(item.get("folderId"), {}).get("path", "")) for item in candidates
        ]

        linked = associations.get(table_key, [])
        report_names = {entry.get("dashboard", "") for entry in linked if entry.get("dashboard")}
        model_names = {entry.get("dataset", "") for entry in linked if entry.get("dataset")}
        live_reports = [item for name in report_names for item in reports_by_name.get(_name_key(name), [])]
        live_models = [item for name in model_names for item in models_by_name.get(_name_key(name), [])]
        legacy_ids = {
            str(entry.get(field, "")) for entry in linked for field in ("report_id", "dataset_id")
            if entry.get(field)
        }
        current_ids = {
            str(item.get("id", "")) for item in (*live_reports, *live_models) if item.get("id")
        }

        row.update({
            "fabric_status": fabric_status,
            "fabric_lakehouse_esperado": expected_lakehouse or "Não definido",
            "fabric_camada_esperada": ", ".join(sorted(expected_layers)) or "Não definida",
            "fabric_localizacoes": " | ".join(location["path"] for location in locations),
            "fabric_lakehouse_ids": " | ".join(sorted({location["lakehouse_id"] for location in locations if location["lakehouse_id"]})),
            "fabric_ultima_modificacao": " | ".join(sorted({location["last_modified"] for location in locations if location["last_modified"]})),
            "fabric_divergencia_dominio": fabric_reason if fabric_status == "OUTRO DOMÍNIO/CAMADA" else "",
            "fabric_motivo_ausencia": fabric_reason if fabric_status == "NÃO ENCONTRADO" else "",
            "fabric_evidencia": fabric_reason,
            "fabric_notebook_candidato": " | ".join(candidate_names),
            "fabric_notebook_ids": " | ".join(candidate_ids),
            "fabric_notebook_pastas": " | ".join(path for path in candidate_paths if path),
            "fabric_report_dev": " | ".join(sorted({str(item.get("displayName", "")) for item in live_reports})),
            "fabric_report_dev_ids": " | ".join(sorted({str(item.get("id", "")) for item in live_reports})),
            "fabric_modelo_dev": " | ".join(sorted({str(item.get("displayName", "")) for item in live_models})),
            "fabric_modelo_dev_ids": " | ".join(sorted({str(item.get("id", "")) for item in live_models})),
            "fabric_id_legado_coincide": "Sim" if legacy_ids & current_ids else "Não",
        })

        static_fabric[str(row.get("status_fim_a_fim", ""))][fabric_status] += 1
        if canonical:
            canonical_total += 1
        if row.get("status_fim_a_fim") in {"COMPLETO", "COMPLETO_DIRETO"}:
            e2e_total += 1
            if locations:
                e2e_found += 1

    report_matches = {
        _name_key(row.get("dashboard", ""))
        for row in enriched.get("dashboard_quality_rows", [])
        if _name_key(row.get("dashboard", "")) in reports_by_name
    }
    model_matches = {
        _name_key(row.get("dataset", ""))
        for row in enriched.get("dashboard_quality_rows", [])
        if _name_key(row.get("dataset", "")) in models_by_name
    }
    legacy_item_ids = {
        str(row.get(field, ""))
        for row in enriched.get("dashboard_quality_rows", [])
        for field in ("report_id", "dataset_id")
        if row.get(field)
    }
    current_item_ids = {
        str(item.get("id", ""))
        for item in items
        if str(item.get("type", "")).casefold() in {"report", "semanticmodel"}
        and item.get("id")
    }
    matrix = []
    for status, counts in sorted(static_fabric.items()):
        matrix.append({
            "status": status,
            "total": sum(counts.values()),
            "no_local_esperado": counts["NO LOCAL ESPERADO"],
            "outro_dominio": counts["OUTRO DOMÍNIO/CAMADA"],
            "nao_encontrado": counts["NÃO ENCONTRADO"],
            "nao_aplicavel": counts["NÃO APLICÁVEL"],
        })

    enriched["fabric"] = {
        "workspace": workspace_name,
        "workspace_id": snapshot.get("workspaceId", ""),
        "snapshot_collected_at": snapshot["collectedAt"],
        "snapshot_run": snapshot_path.parent.name,
        "snapshot_sha256": _sha256(snapshot_path),
        "onelake_evidence_files": len(evidence_files),
        "onelake_window_minutes": evidence_window_minutes,
        "canonical_tables": canonical_total,
        "physical_found": found_total,
        "expected_location": expected_total,
        "cross_domain_or_layer": cross_total,
        "not_found": canonical_total - found_total,
        "e2e_origins_total": e2e_total,
        "e2e_origins_materialized": e2e_found,
        "report_names_matched": len(report_matches),
        "semantic_model_names_matched": len(model_matches),
        "tables_with_notebook_candidate": notebook_total,
        "legacy_id_matches": len(legacy_item_ids & current_item_ids),
        "static_fabric_matrix": matrix,
        "divergences": divergences,
        "absent_by_domain": dict(absent_by_domain.most_common()),
        "evidence_limit": (
            "Comprova presença/publicação observada por nome no snapshot e no OneLake; "
            "não comprova execução, atualização, conteúdo da definição, contrato de colunas, "
            "relacionamentos semânticos ou resultado funcional dos visuais."
        ),
    }
    return enriched
