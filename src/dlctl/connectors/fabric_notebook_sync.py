"""dlctl.connectors.fabric_notebook_sync

Sincroniza notebooks de um workspace Fabric para a pasta local de entrada da
feature de Linhagem (`input/lakehouse-dev` por padrão), reaproveitando o
`FabricClient`/`FabricAuth` do dlctl — ou seja, a MESMA conexão padrão
(Azure CLI, `FABRIC_AUTH_MODE=azure_cli`) usada pelas demais ações do CLI-GUI.

Portado de `fabric_sync.py` (Skill-LineageFabric), adaptado para:
- usar `dlctl.connectors.fabric_api.FabricClient` (com retries/gates já
  existentes) em vez de chamadas `requests` soltas;
- registrar atividade em `dlctl.core.state.log_activity` (mesmo rastro usado
  pelo restante do dlctl);
- expor uma API reutilizável tanto pelo CLI (`dlctl lineage sync-notebooks`)
  quanto pelo dashboard.
"""
from __future__ import annotations

import base64
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Optional

from dlctl.config import Profile
from dlctl.connectors.fabric_api import FabricApiError, FabricClient
from dlctl.core.state import log_activity

ProgressCallback = Callable[[int, int, str], None]


class NotebookSyncError(RuntimeError):
    """Erro acionável durante a sincronização de notebooks."""


def safe_segment(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]+', "_", value).strip(". ")
    return cleaned or "sem_nome"


def _folder_path(folder_id: Optional[str], folders_by_id: dict[str, dict]) -> list[str]:
    parts: list[str] = []
    visited: set[str] = set()
    while folder_id and folder_id not in visited:
        visited.add(folder_id)
        folder = folders_by_id.get(folder_id)
        if not folder:
            break
        parts.append(safe_segment(folder.get("displayName", folder.get("name", folder_id))))
        folder_id = folder.get("parentFolderId")
    return list(reversed(parts))


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name, str(default)).strip().lower()
    return value in {"1", "true", "yes", "sim"}


def _folder_suffixes() -> tuple[str, ...]:
    value = os.getenv("FABRIC_SYNC_FOLDER_SUFFIXES", "_notebooks")
    return tuple(suffix.strip().lower() for suffix in value.split(",") if suffix.strip())


def _max_workers(override: Optional[int] = None) -> int:
    if override is not None:
        return max(1, min(int(override), 8))
    value = os.getenv("FABRIC_SYNC_MAX_WORKERS", "4")
    try:
        return max(1, min(int(value), 8))
    except ValueError:
        return 4


def _should_sync_notebook(relative_folder: list[str]) -> bool:
    if _env_flag("FABRIC_SYNC_ALL", True):
        return True
    if not _env_flag("FABRIC_SYNC_BY_SUFFIX", False):
        return False
    suffixes = _folder_suffixes()
    return bool(suffixes) and any(
        folder.lower().endswith(suffix) for folder in relative_folder for suffix in suffixes
    )


def _decode_part(part: dict) -> str:
    payload = part.get("payload", "")
    if part.get("payloadType") == "InlineBase64":
        return base64.b64decode(payload).decode("utf-8", errors="replace")
    return payload


def _notebook_source(definition: dict) -> str:
    parts = definition.get("parts", [])
    python_parts = [part for part in parts if part.get("path", "").endswith(".py")]
    if python_parts:
        return _decode_part(python_parts[0])

    ipynb_parts = [part for part in parts if part.get("path", "").endswith(".ipynb")]
    if ipynb_parts:
        notebook = json.loads(_decode_part(ipynb_parts[0]))
        return "\n\n".join("".join(cell.get("source", [])) for cell in notebook.get("cells", []))
    raise NotebookSyncError("A definição retornada não contém uma parte Python ou .ipynb.")


def _download_notebook(
    client: FabricClient,
    item: dict,
    relative_folder: list[str],
    output_root: Path,
) -> str:
    definition = client.get_definition_lro(item["id"], item_type="notebooks")
    source = _notebook_source(definition)
    destination = output_root.joinpath(*relative_folder, safe_segment(item.get("displayName", item["id"])))
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "notebook-content.py").write_text(source, encoding="utf-8")
    return item.get("displayName", item.get("id", "sem nome"))


def sync_workspace_notebooks(
    profile: Profile,
    output_dir: Optional[str] = None,
    on_progress: Optional[ProgressCallback] = None,
    max_workers: Optional[int] = None,
    workspace_id: Optional[str] = None,
) -> dict[str, object]:
    """Baixa os notebooks do workspace configurado no profile para
    `input/lakehouse-dev` (ou `output_dir`), no formato consumido pelo
    `dlctl.generators.lineage_generator` (um `notebook-content.py` por pasta).

    `workspace_id` sobrepõe o workspace padrão do profile (`FABRIC_WORKSPACE_ID`)
    — usado para sincronizar outros ambientes do mesmo tenant, como HML
    (`FABRIC_WORKSPACE_ID_HML`), sem precisar trocar o profile inteiro.

    `max_workers` (1 a 8) controla o paralelismo dos downloads via
    ThreadPoolExecutor. Se omitido, usa `FABRIC_SYNC_MAX_WORKERS` do `.env`
    (padrão 4)."""
    workspace_id = workspace_id or profile.microsoft.default_workspace_id
    if not workspace_id:
        raise NotebookSyncError(
            "FABRIC_WORKSPACE_ID não configurado no profile/.env. "
            "Copie o GUID da URL do workspace no portal Fabric."
        )

    output_root = Path(output_dir or os.getenv("FABRIC_SYNC_OUTPUT_DIR", "input/lakehouse-dev"))
    client = FabricClient(profile, workspace_id=workspace_id)

    try:
        items = client.list_items()
        folders = {f["id"]: f for f in client.list_folders() if f.get("id")}
    except FabricApiError as exc:
        raise NotebookSyncError(str(exc)) from exc

    notebooks = []
    for item in items:
        if item.get("type") != "Notebook":
            continue
        relative_folder = _folder_path(item.get("folderId"), folders) or ["SEM_PASTA"]
        if _should_sync_notebook(relative_folder):
            notebooks.append((item, relative_folder))

    if not notebooks:
        raise NotebookSyncError(
            "Nenhum notebook corresponde ao filtro configurado. Revise FABRIC_SYNC_ALL, "
            "FABRIC_SYNC_BY_SUFFIX e FABRIC_SYNC_FOLDER_SUFFIXES no .env."
        )

    downloaded = 0
    failures: list[str] = []
    total = len(notebooks)
    workers = _max_workers(max_workers)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_download_notebook, client, item, relative_folder, output_root): item
            for item, relative_folder in notebooks
        }
        for index, future in enumerate(as_completed(futures), start=1):
            item = futures[future]
            name = item.get("displayName", item.get("id", "sem nome"))
            try:
                future.result()
                downloaded += 1
                if on_progress:
                    on_progress(index, total, name)
            except Exception as exc:  # noqa: BLE001 - agregamos falhas por notebook
                failures.append(f"{name}: {exc}")
                if on_progress:
                    on_progress(index, total, f"FALHA: {name}")

    log_activity(
        profile,
        f"lineage sync-notebooks: {downloaded}/{total} notebooks baixados para {output_root} "
        f"({len(failures)} falha(s), {workers} worker(s) paralelo(s))",
        level="WARN" if failures else "INFO",
        source="lineage.sync_notebooks",
    )

    return {
        "output_dir": str(output_root),
        "total": total,
        "downloaded": downloaded,
        "failures": failures,
        "max_workers": workers,
    }
