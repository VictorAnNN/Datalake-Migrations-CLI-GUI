"""dlctl.core.project_scan

"Supervisor": diagnóstico geral do andamento do projeto de migração
(Bronze -> Silver -> Gold -> Dashboards/BI -> Views/processos intermediários).

"Esperado" (quanto DEVERIA existir no projeto como um todo): a fonte
principal é `input/sharedpoint/Projeto Lakehouse - Tabelas e Pipelines.xlsx`
(aba "Tabelas") + tabelas descobertas via SQL (`dlctl.core.global_scope`) --
é o escopo TOTAL definido pelo cliente, independente do que já foi feito em
`input/lakehouse-dev`. Sem esse Excel disponível, cai para uma estimativa
calculada a partir de tudo disponível em `input/` (menos precisa):
- `mappings/*.csv` (registro oficial de Bronze->Silver->Gold do projeto);
- a linhagem extraída de **todos** os notebooks em `input/lakehouse-dev`
  (inclusive os que ainda estão em pastas `_not_mapped`/`_control`, que já
  referenciam tabelas Bronze/Silver/Gold mesmo sem estar "oficialmente"
  classificados);
- tabelas Oracle referenciadas nos datasets legados de
  `input/Workspaces/*.json` (candidatas a Bronze).

"Existente" (quanto REALMENTE já foi criado) é sempre a contagem real de
notebooks físicos presentes nas pastas `_bronze`/`_silver`/`_gold` dentro de
`input/lakehouse-dev` — nunca uma estimativa.

Dashboards/BI: "esperado" = total de relatórios encontrados em
`input/Workspaces/*.json` (universo completo); "existente" = quantos desses
relatórios já têm pelo menos uma tabela do dataset batendo com uma tabela
Gold realmente criada em `input/lakehouse-dev` (ou seja, os dados que
alimentariam aquele dashboard já existem no ambiente novo).

Views/processos intermediários continuam usando uma meta configurável em
`config/project_targets.yaml`, por não terem uma fonte de verdade própria
no projeto. Sem meta configurada, a categoria fica de fora do percentual
geral em vez de fingir 100%.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from dlctl.config import PROJECT_ROOT, Profile
from dlctl.core.global_scope import compute_global_scope
from dlctl.core.mapping import load_mapping
from dlctl.generators.lineage_generator import (
    _resolve_input_path,
    build_workspace_inventory,
    detect_domain,
    find_notebooks,
    parse_gold_notebook,
    process_lakehouse_dev,
)

TARGETS_PATH = PROJECT_ROOT / "config" / "project_targets.yaml"

HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(bold=True, color="FFFFFF", name="Calibri", size=10)
EVEN_FILL = PatternFill("solid", fgColor="DCE6F1")
ODD_FILL = PatternFill("solid", fgColor="FFFFFF")

# Pastas de notebooks seguem a convenção `<dominio>_notebooks_<camada>` em
# input/lakehouse-dev (ex.: financeiro_notebooks_bronze, ..._silver, ..._gold,
# ..._control, ..._not_mapped, ..._files) ou `data_quality/`.
_CATEGORY_PATTERNS = [
    ("nao_mapeado", ("not_mapped", "not_tracked")),
    ("qualidade_dados", ("data_quality",)),
    ("controle", ("_control", "controle")),
    ("arquivos", ("_files",)),
    ("bronze", ("_bronze",)),
    ("silver", ("_silver",)),
    ("gold", ("_gold",)),
]

CATEGORY_LABELS = {
    "bronze": "Bronze", "silver": "Silver", "gold": "Gold",
    "controle": "Controle/Config", "qualidade_dados": "Qualidade de Dados",
    "arquivos": "Arquivos (shortcuts)", "nao_mapeado": "Não mapeado", "outro": "Outro",
}


def _categorize_notebook_path(path: Path) -> str:
    lower = str(path).replace("\\", "/").lower()
    for category, needles in _CATEGORY_PATTERNS:
        if any(needle in lower for needle in needles):
            return category
    return "outro"


def read_project_targets() -> dict:
    """Meta configurável para Views/processos intermediários (única categoria
    sem fonte de verdade própria no projeto). `null`/ausente significa "meta
    não configurada ainda". Bronze/Silver/Gold/Dashboards são sempre
    calculados a partir de `input/` (não precisam de meta manual)."""
    if not TARGETS_PATH.exists():
        return {"intermediate": None}
    data = yaml.safe_load(TARGETS_PATH.read_text(encoding="utf-8")) or {}
    targets = data.get("targets", {})
    return {"intermediate": targets.get("intermediate")}


def write_project_targets(intermediate: Optional[int]) -> None:
    data = yaml.safe_load(TARGETS_PATH.read_text(encoding="utf-8")) if TARGETS_PATH.exists() else {}
    data = data or {}
    data["targets"] = {"intermediate": intermediate}
    TARGETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    TARGETS_PATH.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


# Prefixos padrão de nome de workspace que identificam os domínios hoje
# migrados em input/lakehouse-dev (CONTROLADORIA/FINANCEIRO -> FINAN-,
# OPERACAO/QSMS/SUPRIMENTOS -> OPER- (inclui OPER-QSMS-*/OPER-SUPPLY-*),
# MASTER_DATA -> MASTER-DATA, Suprimentos/Order Tracking -> ORDER-TRACKING).
# Descoberto comparando a contagem de Reports desses workspaces (421) com o
# número informado pela gestão do projeto (428) — bem mais preciso do que
# contar TODOS os workspaces do tenant (569 Reports).
DEFAULT_WORKSPACE_DOMAIN_PREFIXES = ["OPER-", "FINAN-", "MASTER-DATA", "ORDER-TRACKING"]


def read_workspace_domain_prefixes() -> list[str]:
    """Prefixos de nome de workspace usados pelo filtro 'por domínio' do
    Supervisor. Editável em config/project_targets.yaml (chave
    `workspace_domain_prefixes`); sem configuração, usa o padrão acima."""
    if not TARGETS_PATH.exists():
        return list(DEFAULT_WORKSPACE_DOMAIN_PREFIXES)
    data = yaml.safe_load(TARGETS_PATH.read_text(encoding="utf-8")) or {}
    prefixes = data.get("workspace_domain_prefixes")
    return list(prefixes) if prefixes else list(DEFAULT_WORKSPACE_DOMAIN_PREFIXES)


def write_workspace_domain_prefixes(prefixes: list[str]) -> None:
    data = yaml.safe_load(TARGETS_PATH.read_text(encoding="utf-8")) if TARGETS_PATH.exists() else {}
    data = data or {}
    data["workspace_domain_prefixes"] = prefixes
    TARGETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    TARGETS_PATH.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")



def _pct(existente: int, esperado: Optional[int]) -> Optional[float]:
    if not esperado:
        return None
    return round(min(existente, esperado) / esperado * 100, 1)


def _norm(name: str) -> str:
    return str(name or "").strip().upper()


def _oracle_tables_from_workspaces(workspaces_input: str) -> set[str]:
    """Nomes de tabelas Oracle referenciadas nas expressões Power Query dos
    datasets legados em input/Workspaces — candidatas a Bronze (mesma
    lógica de dlctl.generators.fabric_lineage_export, reaproveitada aqui
    só para a contagem, sem gerar nenhum arquivo)."""
    from dlctl.generators.fabric_lineage_export import process_workspaces_raw
    data = process_workspaces_raw(workspaces_input)
    oracle_df = data["oracle_tables"]
    if oracle_df.empty or "oracle_table" not in oracle_df.columns:
        return set()
    return {_norm(t) for t in oracle_df["oracle_table"] if t}


def _gold_table_names_realmente_criadas(lakehouse_input: str) -> set[str]:
    """Nomes das tabelas Gold que têm, de verdade, um notebook criado na
    pasta `_gold` de um lakehouse (`input/lakehouse-dev` ou `input/lakehouse-hml`)
    (parseia cada notebook Gold real para extrair o nome da tabela de destino)."""
    names: set[str] = set()
    for nb_path in find_notebooks(lakehouse_input):
        if _categorize_notebook_path(nb_path) != "gold":
            continue
        try:
            content = nb_path.read_text(encoding="utf-8", errors="replace")
            parsed = parse_gold_notebook(content, detect_domain(nb_path))
        except Exception:
            continue
        if parsed.get("gold_table"):
            names.add(_norm(parsed["gold_table"]))
    return names


def _category_identity_map(lakehouse_input: str) -> dict[str, set[str]]:
    """Mapeia cada categoria (bronze/silver/gold/controle/...) para o conjunto
    de notebooks encontrados em um lakehouse, identificados pela pasta (sem a
    extensão .py/.sql) — usado para casar o MESMO notebook entre
    `input/lakehouse-dev` e `input/lakehouse-hml` (promovido ou não)."""
    identities: dict[str, set[str]] = {c: set() for c, _ in _CATEGORY_PATTERNS}
    identities["outro"] = set()
    root = Path(lakehouse_input) if lakehouse_input else None
    if not root or not root.exists():
        return identities
    for nb_path in find_notebooks(lakehouse_input):
        category = _categorize_notebook_path(nb_path)
        try:
            identity = str(nb_path.parent.relative_to(root)).replace("\\", "/")
        except ValueError:
            identity = str(nb_path.parent)
        identities[category].add(identity)
    return identities



def _dashboard_table_names(workspace_rows: list[dict]) -> dict[str, set[str]]:
    """Mapeia cada Report (por item_id/nome) para o conjunto de nomes de
    tabela do seu dataset — ou seja, as tabelas que precisam existir
    (idealmente como Gold) para aquele dashboard funcionar."""
    dataset_name_by_id = {r["item_id"]: r["item_name"] for r in workspace_rows if r["item_type"] == "Dataset"}
    table_names_by_dataset_name: dict[str, set[str]] = {}
    for r in workspace_rows:
        if r["item_type"] == "Dataset Table":
            table_names_by_dataset_name.setdefault(r["parent_name"], set()).add(_norm(r["item_name"]))

    result: dict[str, set[str]] = {}
    for r in workspace_rows:
        if r["item_type"] != "Report":
            continue
        dataset_name = dataset_name_by_id.get(r["parent_name"], "")
        result[r["item_id"] or r["item_name"]] = table_names_by_dataset_name.get(dataset_name, set())
    return result


def _workspaces_referenciados(workspace_rows: list[dict], table_universe: set[str]) -> set[str]:
    """Nomes dos workspaces que têm pelo menos uma Dataset Table cujo nome
    bate com alguma tabela conhecida em input/lakehouse-dev (Bronze/Silver/
    Gold, esperado ou existente) — ou seja, workspaces que de fato fazem
    parte deste projeto de migração, e não só workspaces do tenant que não
    têm nenhuma relação com o que está sendo migrado."""
    referenced: set[str] = set()
    for r in workspace_rows:
        if r["item_type"] == "Dataset Table" and _norm(r["item_name"]) in table_universe:
            referenced.add(r["workspace"])
    return referenced


def _filter_workspace_rows(workspace_rows: list[dict], workspaces_to_keep: set[str]) -> list[dict]:
    return [r for r in workspace_rows if r["workspace"] in workspaces_to_keep]


def _workspaces_by_domain_prefix(workspace_rows: list[dict], prefixes: list[str]) -> set[str]:
    """Nomes dos workspaces cujo nome começa com algum dos prefixos
    configurados (ex.: OPER-, FINAN-, MASTER-DATA, ORDER-TRACKING) — os
    domínios de negócio hoje migrados em input/lakehouse-dev. Mais
    determinístico do que casar por nome de tabela: não depende do dataset
    já ter alguma tabela conhecida, só do nome do workspace."""
    prefixes_upper = tuple(p.strip().upper() for p in prefixes if p and p.strip())
    if not prefixes_upper:
        return set()
    return {
        r["workspace"] for r in workspace_rows
        if r["item_type"] == "Workspace" and _norm(r["workspace"]).startswith(prefixes_upper)
    }


def _gold_needed_for_dashboards(dashboard_tables: dict[str, set[str]]) -> set[str]:
    """União de todas as tabelas necessárias (por qualquer dashboard) — o
    universo de tabelas Gold que o cliente precisa para os dashboards dele."""
    needed: set[str] = set()
    for names in dashboard_tables.values():
        needed |= names
    return needed


def _dashboards_prontos(dashboard_tables: dict[str, set[str]], gold_existente_names: set[str]) -> tuple[int, int]:
    """Retorna (total_dashboards, dashboards_prontos): um dashboard está
    "pronto" quando pelo menos uma tabela do seu dataset já bate (por nome)
    com uma tabela Gold realmente criada em input/lakehouse-dev — ou seja,
    os dados que o alimentariam já existem no ambiente novo."""
    total = len(dashboard_tables)
    prontos = sum(1 for names in dashboard_tables.values() if names & gold_existente_names)
    return total, prontos


def scan_project(
    profile: Profile,
    lakehouse_dev_input: str = "input/lakehouse-dev",
    workspaces_input: Optional[str] = "input/Workspaces",
    only_referenced_workspaces: bool = False,
    filter_by_domain_prefix: bool = False,
    lakehouse_hml_input: Optional[str] = None,
    sharedpoint_input: Optional[str] = "input/sharedpoint",
) -> dict:
    """Varre os artefatos reais do projeto e monta o diagnóstico geral
    (Bronze/Silver/Gold/Dashboards/Views). "Esperado" é a união de tudo que
    foi encontrado em `input/` (mappings + linhagem de notebooks + Oracle
    refs de Workspaces); "existente" é a contagem real de notebooks já
    criados — em `input/lakehouse-dev` e, se `lakehouse_hml_input` for
    informado, também em `input/lakehouse-hml` (união das duas, sem contar
    duas vezes o mesmo notebook já promovido para HML).

    Dois filtros opcionais e mutuamente exclusivos descartam, do cálculo de
    Dashboards/BI e Gold, os workspaces de `input/Workspaces` que não fazem
    parte deste projeto (`filter_by_domain_prefix` tem prioridade se ambos
    forem passados):
    - `filter_by_domain_prefix=True`: mantém só workspaces cujo nome começa
      com um dos prefixos de `read_workspace_domain_prefixes()` (ex.: OPER-,
      FINAN-, MASTER-DATA, ORDER-TRACKING) — determinístico, baseado nos
      domínios de negócio já migrados em `input/lakehouse-dev`;
    - `only_referenced_workspaces=True`: mantém só workspaces que têm alguma
      Dataset Table batendo com uma tabela conhecida em `input/lakehouse-dev`
      (Bronze/Silver/Gold) — mais permissivo, útil quando os prefixos de
      nome não são conhecidos/configurados."""
    lakehouse_dev_input = _resolve_input_path(lakehouse_dev_input)
    lakehouse_hml_input = _resolve_input_path(lakehouse_hml_input) if lakehouse_hml_input else None
    hml_found = bool(lakehouse_hml_input) and Path(lakehouse_hml_input).exists()
    workspaces_input = _resolve_input_path(workspaces_input) if workspaces_input else None
    workspaces_found = bool(workspaces_input) and Path(workspaces_input).exists()

    # ---- Escopo TOTAL do projeto (o que DEVERIA existir), fonte principal: input/sharedpoint ----
    sharedpoint_input = _resolve_input_path(sharedpoint_input) if sharedpoint_input else None
    global_scope = compute_global_scope(sharedpoint_input) if sharedpoint_input else {"excel_found": False}

    def _camada_total(nome: str) -> Optional[int]:
        if not global_scope.get("excel_found"):
            return None
        for c in global_scope["camadas"]:
            if c["camada"].strip().lower() == nome.lower():
                return c["total"]
        return None

    # ---- Notebooks reais em input/lakehouse-dev, categorizados por pasta (o que já foi CRIADO) ----
    notebook_rows: list[dict] = []
    category_counts: dict[str, int] = {c: 0 for c, _ in _CATEGORY_PATTERNS}
    category_counts["outro"] = 0
    dev_identities: dict[str, set[str]] = {c: set() for c, _ in _CATEGORY_PATTERNS}
    dev_identities["outro"] = set()
    dev_root = Path(lakehouse_dev_input)
    for nb_path in find_notebooks(lakehouse_dev_input):
        category = _categorize_notebook_path(nb_path)
        category_counts[category] += 1
        try:
            identity = str(nb_path.parent.relative_to(dev_root)).replace("\\", "/")
        except ValueError:
            identity = str(nb_path.parent)
        dev_identities[category].add(identity)
        try:
            rel = str(nb_path.relative_to(PROJECT_ROOT))
        except ValueError:
            rel = str(nb_path)
        notebook_rows.append({"categoria": CATEGORY_LABELS.get(category, category), "caminho": rel})

    # ---- Notebooks reais em input/lakehouse-hml (mesma árvore de pastas, para casar por identidade) ----
    hml_identities = _category_identity_map(lakehouse_hml_input) if hml_found else {c: set() for c in category_counts}

    # "Geral" = união dev+hml por categoria (mesmo notebook promovido não conta 2x); sem HML, é igual ao dev.
    category_counts_geral: dict[str, int] = {
        cat: len(dev_identities.get(cat, set()) | hml_identities.get(cat, set())) for cat in category_counts
    }

    env_categories = [
        {
            "categoria": CATEGORY_LABELS.get(cat, cat),
            "existente_dev": len(dev_identities.get(cat, set())),
            "existente_hml": len(hml_identities.get(cat, set())),
            "existente_geral": category_counts_geral[cat],
            "promovidos_hml": len(dev_identities.get(cat, set()) & hml_identities.get(cat, set())),
            "somente_dev": len(dev_identities.get(cat, set()) - hml_identities.get(cat, set())),
            "pct_hml": (
                round(len(hml_identities.get(cat, set())) / category_counts_geral[cat] * 100, 1)
                if category_counts_geral[cat] else None
            ),
        }
        for cat in category_counts if cat != "outro"
    ]
    total_dev = sum(len(s) for s in dev_identities.values())
    total_hml = sum(len(s) for s in hml_identities.values())
    total_geral = sum(category_counts_geral.values())
    env_totals = {
        "existente_dev": total_dev, "existente_hml": total_hml, "existente_geral": total_geral,
        "promovidos_hml": sum(e["promovidos_hml"] for e in env_categories),
        "pct_hml": round(total_hml / total_geral * 100, 1) if total_geral else None,
    }

    # ---- "Esperado": união de mappings/*.csv + linhagem de TODOS os notebooks + Oracle refs ----
    bronze_to_silver = load_mapping(profile, layer="bronze_to_silver")
    silver_to_gold = load_mapping(profile, layer="silver_to_gold")
    linhagem_rows = process_lakehouse_dev(lakehouse_dev_input)["linhagem"]

    bronze_universe = {_norm(e.source_table) for e in bronze_to_silver if e.source_table}
    bronze_universe |= {_norm(r["TABELA_ORIGEM"]) for r in linhagem_rows if r.get("CAMADA_ORIGEM") == "bronze" and r.get("TABELA_ORIGEM")}

    silver_universe = {_norm(e.target_table) for e in bronze_to_silver if e.target_table}
    silver_universe |= {_norm(r["TABELA_DESTINO"]) for r in linhagem_rows if r.get("CAMADA_DESTINO") == "silver" and r.get("TABELA_DESTINO")}
    silver_universe |= {_norm(r["TABELA_ORIGEM"]) for r in linhagem_rows if r.get("CAMADA_ORIGEM") == "silver" and r.get("TABELA_ORIGEM")}

    gold_universe = {_norm(e.target_table) for e in silver_to_gold if e.target_table}
    gold_universe |= {_norm(r["TABELA_DESTINO"]) for r in linhagem_rows if r.get("CAMADA_DESTINO") == "gold" and r.get("TABELA_DESTINO")}

    workspace_rows: list[dict] = []
    dashboards_esperado = 0
    dashboards_existente = 0
    gold_needed: set[str] = set()
    gold_existente_names: set[str] = set()
    workspaces_total = 0
    workspaces_referenciados: set[str] = set()
    workspace_filter_mode: Optional[str] = None
    if workspaces_found:
        workspace_rows = build_workspace_inventory(workspaces_input)
        workspaces_total = len({r["workspace"] for r in workspace_rows if r["item_type"] == "Workspace"})
        bronze_universe |= _oracle_tables_from_workspaces(workspaces_input)
        gold_existente_names = _gold_table_names_realmente_criadas(lakehouse_dev_input)
        if hml_found:
            gold_existente_names |= _gold_table_names_realmente_criadas(lakehouse_hml_input)
        if filter_by_domain_prefix:
            workspace_filter_mode = "domain_prefix"
            workspaces_referenciados = _workspaces_by_domain_prefix(workspace_rows, read_workspace_domain_prefixes())
            workspace_rows = _filter_workspace_rows(workspace_rows, workspaces_referenciados)
        elif only_referenced_workspaces:
            workspace_filter_mode = "referenced_table"
            table_universe = bronze_universe | silver_universe | gold_universe | gold_existente_names
            workspaces_referenciados = _workspaces_referenciados(workspace_rows, table_universe)
            workspace_rows = _filter_workspace_rows(workspace_rows, workspaces_referenciados)
        dashboard_tables = _dashboard_table_names(workspace_rows)
        dashboards_esperado, dashboards_existente = _dashboards_prontos(dashboard_tables, gold_existente_names)
        gold_needed = _gold_needed_for_dashboards(dashboard_tables)


    # Gold "esperado": prioridade é input/sharedpoint (escopo total real do
    # cliente); sem isso, cai para os dashboards de input/Workspaces (Dataset
    # Tables dos relatórios); sem nenhum dos dois, cai para mapping+linhagem.
    sharedpoint_gold = _camada_total("Gold")
    if sharedpoint_gold is not None:
        gold_esperado = sharedpoint_gold
        gold_existente_count = category_counts_geral["gold"]
        gold_fonte = f"input/sharedpoint (Excel 'Tabelas' + tabelas descobertas via SQL) — {global_scope['excel_path']}"
    elif gold_needed:
        gold_esperado = len(gold_needed)
        gold_existente_count = len(gold_needed & gold_existente_names)
        gold_fonte = (
            "Tabelas Gold que os dashboards de input/Workspaces precisam (Dataset Tables dos relatórios) "
            "vs. tabelas Gold realmente criadas em input/lakehouse-dev" + (" + input/lakehouse-hml" if hml_found else "")
        )
    else:
        gold_esperado = len(gold_universe)
        gold_existente_count = category_counts_geral["gold"]
        gold_fonte = (
            "União: mappings/silver_to_gold.csv + linhagem de todos os notebooks (input/lakehouse-dev"
            + (" + input/lakehouse-hml)" if hml_found else ")")
            + " — input/sharedpoint e input/Workspaces não encontrados/sem dados"
        )

    sharedpoint_bronze = _camada_total("Bronze")
    bronze_esperado = sharedpoint_bronze if sharedpoint_bronze is not None else len(bronze_universe)
    bronze_fonte = (
        f"input/sharedpoint (Excel 'Tabelas' + tabelas descobertas via SQL)"
        if sharedpoint_bronze is not None else
        "União: mappings/bronze_to_silver.csv + linhagem de todos os notebooks + Oracle refs (input/Workspaces) "
        "— input/sharedpoint não encontrado"
    ) + (" | existente = união DEV+HML" if hml_found else "")

    sharedpoint_silver = _camada_total("Silver")
    silver_esperado = sharedpoint_silver if sharedpoint_silver is not None else len(silver_universe)
    silver_fonte = (
        "input/sharedpoint (Excel 'Tabelas' + tabelas descobertas via SQL)"
        if sharedpoint_silver is not None else
        "União: mappings/bronze_to_silver.csv + linhagem de todos os notebooks (input/lakehouse-dev) "
        "— input/sharedpoint não encontrado"
    ) + (" | existente = união DEV+HML" if hml_found else "")

    # Dashboards/BI "esperado": prioridade é o total declarado pelo próprio
    # cliente em input/sharedpoint (aba de entregáveis, ex.: "428 dashboards
    # conectados à nova origem") — não é uma contagem, é a meta oficial do
    # projeto. Sem isso, cai para a contagem de relatórios em input/Workspaces.
    dashboard_target = global_scope.get("dashboard_target")
    if dashboard_target:
        dashboards_esperado_final = dashboard_target["total"]
        dashboards_fonte = (
            f"input/sharedpoint, aba '{dashboard_target['fonte_sheet']}': \"{dashboard_target['fonte_texto']}\"; "
            "\"pronto\" = dataset já bate com uma tabela Gold criada" if workspaces_found else
            f"input/sharedpoint, aba '{dashboard_target['fonte_sheet']}': \"{dashboard_target['fonte_texto']}\" "
            "(input/Workspaces não encontrado, existente fica em 0)"
        )
    else:
        dashboards_esperado_final = dashboards_esperado
        dashboards_fonte = (
            ("Total de relatórios em input/Workspaces" + {
                "domain_prefix": " (só workspaces com prefixo de domínio conhecido)",
                "referenced_table": " (só workspaces referenciados em lakehouse-dev)",
            }.get(workspace_filter_mode, ""))
            + "; \"pronto\" = dataset já bate com uma tabela Gold criada"
        ) if workspaces_found else "input/Workspaces e input/sharedpoint não encontrados"

    targets = read_project_targets()

    categories = [
        {"categoria": "Bronze", "existente": category_counts_geral["bronze"], "esperado": bronze_esperado,
         "percentual": _pct(category_counts_geral["bronze"], bronze_esperado),
         "fonte_meta": bronze_fonte},
        {"categoria": "Silver", "existente": category_counts_geral["silver"], "esperado": silver_esperado,
         "percentual": _pct(category_counts_geral["silver"], silver_esperado),
         "fonte_meta": silver_fonte},
        {"categoria": "Gold", "existente": gold_existente_count, "esperado": gold_esperado,
         "percentual": _pct(gold_existente_count, gold_esperado),
         "fonte_meta": gold_fonte},
        {"categoria": "Dashboards/BI", "existente": dashboards_existente, "esperado": dashboards_esperado_final,
         "percentual": _pct(dashboards_existente, dashboards_esperado_final),
         "fonte_meta": dashboards_fonte},
        {"categoria": "Views/Processos intermediários",
         "existente": category_counts_geral["controle"] + category_counts_geral["qualidade_dados"],
         "esperado": targets["intermediate"],
         "percentual": _pct(category_counts_geral["controle"] + category_counts_geral["qualidade_dados"], targets["intermediate"]),
         "fonte_meta": "config/project_targets.yaml (meta manual)" if targets["intermediate"] else "meta não configurada"},
    ]

    # Qualquer camada extra que o cliente tenha criado em input/sharedpoint
    # além de Bronze/Silver/Gold (descoberta dinamicamente pelo cabeçalho do
    # Excel) entra como categoria própria — sem contagem "existente" própria
    # em input/lakehouse-dev (ainda não rastreada), só o total esperado.
    if global_scope.get("excel_found"):
        _known_camadas = {"bronze", "silver", "gold"}
        for c in global_scope["camadas"]:
            if c["camada"].strip().lower() in _known_camadas:
                continue
            categories.append({
                "categoria": f"Outros processos ({c['camada']})", "existente": 0, "esperado": c["total"],
                "percentual": _pct(0, c["total"]),
                "fonte_meta": f"input/sharedpoint (Excel 'Tabelas', coluna Camada {c['camada']}) "
                              "— sem contagem de existente própria ainda em input/lakehouse-dev",
            })

    measured = [c for c in categories if c["esperado"]]
    overall_percent = (
        round(sum(min(c["existente"], c["esperado"]) for c in measured) / sum(c["esperado"] for c in measured) * 100, 1)
        if measured else 0.0
    )

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "categories": categories,
        "overall_percent": overall_percent,
        "excluded_from_overall": [c["categoria"] for c in categories if not c["esperado"]],
        "notebook_rows": notebook_rows,
        "notebook_category_counts": {CATEGORY_LABELS.get(k, k): v for k, v in category_counts_geral.items() if v},
        "workspace_rows": workspace_rows,
        "lakehouse_dev_input": lakehouse_dev_input,
        "workspaces_input": workspaces_input if workspaces_found else None,
        "only_referenced_workspaces": only_referenced_workspaces,
        "filter_by_domain_prefix": filter_by_domain_prefix,
        "workspace_filter_mode": workspace_filter_mode,
        "workspaces_total": workspaces_total,
        "workspaces_referenciados": sorted(workspaces_referenciados) if workspace_filter_mode else None,
        "hml_enabled": hml_found,
        "lakehouse_hml_input": lakehouse_hml_input if hml_found else None,
        "env_categories": env_categories,
        "env_totals": env_totals,
        "global_scope": global_scope,
        "sharedpoint_input": sharedpoint_input if global_scope.get("excel_found") else None,
    }


# ===========================================================================
# Export do relatório (Excel + CSV) em manifests/dashboard/
# ===========================================================================

def _autofit_sheet(ws_sheet) -> None:
    for col_idx, col in enumerate(ws_sheet.iter_cols(), start=1):
        col_letter = get_column_letter(col_idx)
        max_len = 0
        for i, cell in enumerate(col):
            if i == 0:
                cell.font = HEADER_FONT
                cell.fill = HEADER_FILL
                cell.alignment = Alignment(horizontal="center", vertical="center")
            else:
                cell.fill = EVEN_FILL if i % 2 == 0 else ODD_FILL
            try:
                max_len = max(max_len, len(str(cell.value)) if cell.value else 0)
            except Exception:
                pass
        ws_sheet.column_dimensions[col_letter].width = min(max(max_len + 4, 12), 80)
    ws_sheet.freeze_panes = "A2"


def export_supervisor_report(scan_result: dict, output_dir: Path, batch_id: str) -> dict[str, str]:
    """Exporta o diagnóstico para `manifests/dashboard/`: um Excel com abas
    Resumo/Notebooks/Dashboards e um CSV simples só do resumo."""
    output_dir.mkdir(parents=True, exist_ok=True)
    excel_path = output_dir / f"supervisor_report_{batch_id}.xlsx"
    csv_path = output_dir / f"supervisor_report_{batch_id}.csv"

    summary_df = pd.DataFrame(scan_result["categories"])
    summary_df.to_csv(csv_path, index=False, encoding="utf-8")

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        overview = pd.DataFrame({
            "Item": ["Gerado em", "% geral do projeto", "Categorias sem meta configurada"],
            "Valor": [
                scan_result["generated_at"], f"{scan_result['overall_percent']}%",
                ", ".join(scan_result["excluded_from_overall"]) or "(nenhuma)",
            ],
        })
        overview.to_excel(writer, sheet_name="Resumo", index=False, startrow=0)
        summary_df.to_excel(writer, sheet_name="Resumo", index=False, startrow=len(overview) + 2)

        notebooks_df = pd.DataFrame(scan_result["notebook_rows"])
        (notebooks_df if not notebooks_df.empty else pd.DataFrame(columns=["categoria", "caminho"])).to_excel(
            writer, sheet_name="Notebooks", index=False,
        )

        workspace_df = pd.DataFrame(scan_result["workspace_rows"])
        (workspace_df if not workspace_df.empty else pd.DataFrame(columns=["workspace", "item_type", "item_name"])).to_excel(
            writer, sheet_name="Dashboards e Workspaces", index=False,
        )

    wb = load_workbook(excel_path)
    for sheet_name in wb.sheetnames:
        _autofit_sheet(wb[sheet_name])
    wb.save(excel_path)

    return {"excel_path": str(excel_path), "csv_path": str(csv_path)}
