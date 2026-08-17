"""dlctl.generators.validators

Valida notebooks gerados contra os gates definidos nas skills:
- Notebook Contract (etl-oracle-fabric/SKILL.md)
- Gold Gates (etl-oracle-fabric-gold/SKILL.md)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import nbformat


@dataclass
class ValidationOutcome:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


FORBIDDEN_IMPORTS = ["import pandas", "import numpy", "from pandas", "from numpy", "openpyxl", "xlrd"]
FORBIDDEN_FILE_READS = [".sql'", '.sql"', ".tab'", '.tab"', ".dsx", "open('", 'open("']

GOLD_PLACEHOLDERS = [
    "LakehouseOracle.Lakehouse",
    "abfss://Silver@",
    "abfss://Gold@",
]


def _all_source(nb) -> str:
    return "\n".join(
        "".join(cell.source) if isinstance(cell.source, list) else cell.source
        for cell in nb.cells
    )


def _check_raw_cell_shape(path: str | Path) -> list[str]:
    """Verifica 'id' e 'source' como lista de linhas direto no JSON em disco,
    já que nbformat.read normaliza 'source' (lista -> string única) ao carregar
    e não deve ser usado para essa checagem específica."""
    errors: list[str] = []
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    for i, cell in enumerate(raw.get("cells", [])):
        if not cell.get("id"):
            errors.append(f"Célula {i} sem 'id' (obrigatório para import no Fabric).")
        if not isinstance(cell.get("source"), list):
            errors.append(f"Célula {i}: 'source' deve ser lista de linhas, não string única.")
    return errors


def validate_silver_notebook(path: str | Path) -> ValidationOutcome:
    """Replica o Notebook Contract de etl-oracle-fabric/SKILL.md."""
    errors: list[str] = _check_raw_cell_shape(path)
    warnings: list[str] = []
    nb = nbformat.read(str(path), as_version=4)

    full_source = _all_source(nb)

    for forbidden in FORBIDDEN_IMPORTS:
        if forbidden in full_source:
            errors.append(f"Import proibido encontrado: '{forbidden}' (Pandas/NumPy/Excel não permitidos).")
    for pattern in FORBIDDEN_FILE_READS:
        if pattern in full_source:
            errors.append(f"Leitura de arquivo local proibida em runtime: padrão '{pattern}'.")

    if "createOrReplaceTempView" not in full_source and "createTempView" not in full_source:
        errors.append("Nenhum TempView criado antes do spark.sql (obrigatório).")
    if "spark.sql(" not in full_source:
        errors.append("Nenhuma chamada spark.sql() encontrada (transformação deve rodar via Spark SQL).")
    if ".parquet(" not in full_source and "format(\"parquet\")" not in full_source:
        warnings.append("Não foi encontrada leitura explícita de Parquet para o Bronze.")
    if "format(\"delta\")" not in full_source and ".delta(" not in full_source and "delta" not in full_source.lower():
        errors.append("Nenhuma escrita Delta detectada para o output Silver.")

    return ValidationOutcome(ok=not errors, errors=errors, warnings=warnings)


def validate_gold_notebook(path: str | Path) -> ValidationOutcome:
    """Replica os Gold Gates de etl-oracle-fabric-gold/SKILL.md."""
    errors: list[str] = _check_raw_cell_shape(path)
    warnings: list[str] = []
    nb = nbformat.read(str(path), as_version=4)

    full_source = _all_source(nb)

    for forbidden in FORBIDDEN_IMPORTS:
        if forbidden in full_source:
            errors.append(f"Import proibido encontrado: '{forbidden}'.")
    for placeholder in GOLD_PLACEHOLDERS:
        if placeholder in full_source:
            errors.append(f"Caminho placeholder detectado: '{placeholder}'.")

    silver_path_match = re.search(r"SILVER_PATH\s*=\s*(['\"])(.*?)\1", full_source)
    if silver_path_match and not silver_path_match.group(2).strip():
        errors.append("SILVER_PATH está vazio.")

    if "CREATE OR REPLACE VIEW" in full_source.upper():
        errors.append("'CREATE OR REPLACE VIEW' não é permitido dentro de spark.sql no Gold.")

    tempviews = set(re.findall(r"createOrReplaceTempView\(\s*['\"](\w+)['\"]", full_source))
    sql_blocks = re.findall(r"spark\.sql\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)", full_source)
    inline_sql = re.findall(r"spark\.sql\(\s*(f?['\"])", full_source)
    referenced_names = set(re.findall(r"\bFROM\s+(\w+)", full_source, re.IGNORECASE)) | \
        set(re.findall(r"\bJOIN\s+(\w+)", full_source, re.IGNORECASE))
    missing_refs = referenced_names - tempviews
    # tolerante: apenas alerta, já que a tabela referenciada pode ser Gold/permanente
    if missing_refs and tempviews:
        warnings.append(f"Referências não casadas com TempViews criados: {sorted(missing_refs)}")

    if "PLACEHOLDER" in full_source.upper() or "TODO SQL" in full_source.upper():
        errors.append("SQL placeholder detectado.")

    return ValidationOutcome(ok=not errors, errors=errors, warnings=warnings)
