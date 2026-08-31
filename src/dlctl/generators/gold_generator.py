"""Gera notebooks Silver -> Gold no contrato canônico Constellation."""
from __future__ import annotations

import json
from pathlib import Path

import nbformat as nbf

from dlctl.core.mapping import MappingEntry


CELL_TITLES = [
    "G1_HEADER_METADATA", "G2_PARAMETERS", "G3_SPARK_SESSION",
    "G4_SILVER_TEMPVIEWS", "G5_SPARK_SQL", "G6_SCHEMA_CONTRACT",
    "G7_PK_QUARANTINE", "G8_DELTA_WRITE", "G9_OPTIMIZE", "G10_METRICS",
]


def _code_cell(source: str, cell_id: str):
    cell = nbf.v4.new_code_cell(source=source)
    cell["id"] = cell_id
    cell["source"] = source.rstrip().splitlines(keepends=True) + ["\n"]
    return cell


def generate_gold_notebook(
    entry: MappingEntry,
    silver_base_path: str,
    gold_base_path: str,
    project_root: Path,
    write_mode: str = "overwrite",
    fail_on_errors: bool = True,
    ancient_date_cutoff: str = "1900-01-01",
) -> nbf.NotebookNode:
    if not silver_base_path.strip() or not gold_base_path.strip():
        raise ValueError("silver_base_path e gold_base_path são obrigatórios.")
    if write_mode != "overwrite":
        raise ValueError("O piloto suporta somente write_mode='overwrite'.")
    sql_path = (project_root / entry.sql_file) if entry.sql_file else None
    if not sql_path or not sql_path.is_file():
        raise ValueError(f"SQL obrigatório não encontrado para {entry.target_table}: {sql_path}")

    sql_literal = sql_path.read_text(encoding="utf-8")
    source_table = entry.source_table
    target_table = entry.target_table
    source_view = source_table.lower()
    sql_string = json.dumps(sql_literal, ensure_ascii=False)

    cells = [
        _code_cell(
            f"""# {CELL_TITLES[0]}
# ETL: SILVER -> GOLD
# Dominio: {entry.domain}
# Fonte: {source_table}
# Destino: {target_table}
# Status de geração: {entry.status}
# Gerado por: dlctl""",
            "g1-header-metadata",
        ),
        _code_cell(
            f"""# {CELL_TITLES[1]}
SILVER_TABLE = {source_table!r}
GOLD_TABLE = {target_table!r}
SILVER_PATH = f{(silver_base_path.rstrip('/') + '/{SILVER_TABLE}')!r}
GOLD_PATH = f{(gold_base_path.rstrip('/') + '/{GOLD_TABLE}')!r}
QUARANTINE_PATH = f{(gold_base_path.rstrip('/') + '/_quarantine/{GOLD_TABLE}')!r}
PRIMARY_KEYS = []
WRITE_MODE = {write_mode!r}
FAIL_ON_ERRORS = {fail_on_errors!r}
ANCIENT_DATE_CUTOFF = {ancient_date_cutoff!r}""",
            "g2-parameters",
        ),
        _code_cell(
            f"""# {CELL_TITLES[2]}
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
import time

spark = SparkSession.builder.appName(f"ETL_GOLD_{{GOLD_TABLE}}").getOrCreate()
spark.sparkContext.setLogLevel("WARN")
spark.conf.set("spark.sql.parquet.datetimeRebaseModeInWrite", "CORRECTED")
spark.conf.set("spark.sql.parquet.int96RebaseModeInWrite", "CORRECTED")
inicio_pipeline = time.time()""",
            "g3-spark-session",
        ),
        _code_cell(
            f"""# {CELL_TITLES[3]}
df_silver = spark.read.format("delta").load(SILVER_PATH)
df_silver.createOrReplaceTempView({source_view!r})
source_count = df_silver.count()""",
            "g4-silver-tempviews",
        ),
        _code_cell(
            f"""# {CELL_TITLES[4]}
SQL_GOLD = {sql_string}
df_gold_raw = spark.sql(SQL_GOLD)""",
            "g5-spark-sql",
        ),
        _code_cell(
            f"""# {CELL_TITLES[5]}
# O mapeamento simplificado ainda não fornece contrato Gold tipado.
SCHEMA_CONTRACT = {{}}
df_gold_conformado = df_gold_raw""",
            "g6-schema-contract",
        ),
        _code_cell(
            f"""# {CELL_TITLES[6]}
if PRIMARY_KEYS:
    null_condition = None
    for key in PRIMARY_KEYS:
        condition = F.col(key).isNull()
        null_condition = condition if null_condition is None else null_condition | condition
    df_quarentena = df_gold_conformado.filter(null_condition)
    df_gold_final = df_gold_conformado.filter(~null_condition)
    quarantine_count = df_quarentena.count()
    if quarantine_count:
        df_quarentena.write.format("delta").mode("append").save(QUARANTINE_PATH)
else:
    df_gold_final = df_gold_conformado
    quarantine_count = 0""",
            "g7-pk-quarantine",
        ),
        _code_cell(
            f"""# {CELL_TITLES[7]}
(
    df_gold_final.write
    .format("delta")
    .mode(WRITE_MODE)
    .option("overwriteSchema", "true")
    .save(GOLD_PATH)
)""",
            "g8-delta-write",
        ),
        _code_cell(
            f"""# {CELL_TITLES[8]}
try:
    spark.sql(f"OPTIMIZE delta.`{{GOLD_PATH}}`")
except Exception as exc:
    print(f"[WARN] OPTIMIZE não executado: {{type(exc).__name__}}")""",
            "g9-optimize",
        ),
        _code_cell(
            f"""# {CELL_TITLES[9]}
target_count = df_gold_final.count()
elapsed_seconds = round(time.time() - inicio_pipeline, 2)
print(
    "[METRICS] "
    f"table={{GOLD_TABLE}} source_count={{source_count}} target_count={{target_count}} "
    f"quarantine_count={{quarantine_count}} elapsed_seconds={{elapsed_seconds}}"
)""",
            "g10-metrics",
        ),
    ]

    nb = nbf.v4.new_notebook(cells=cells)
    nb["nbformat"] = 4
    nb["nbformat_minor"] = 5
    nb["metadata"] = {
        "kernelspec": {"display_name": "PySpark", "language": "python", "name": "synapse_pyspark"},
        "language_info": {"name": "python"},
        "generated_by": "dlctl.generators.gold_generator",
        "source_table": source_table,
        "target_table": target_table,
        "status_at_generation": entry.status,
    }
    return nb


def write_notebook(nb: nbf.NotebookNode, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    nbf.write(nb, str(output_path))
    return output_path
