"""dlctl.core.table_lineage_graph

Mapeia a linhagem tabela-a-tabela dentro de `input/sharedpoint` (Bronze ->
Silver -> Gold), lendo os scripts `.sql`/`.prc`/`.tab`/`.vw` de TODAS as
subpastas de TODOS os sistemas fonte (as mesmas pastas do modo estendido de
`dlctl.core.global_scope`): para cada arquivo, descobre o objeto que ele
CRIA/POPULA (a "tabela destino") e as tabelas que ele referencia via
FROM/JOIN (as "tabelas origem", ignorando aliases de CTE) — montando um
grafo de dependência tabela -> tabela que permite rastrear pra trás, a
partir de uma tabela Gold já conhecida, até a(s) tabela(s) Silver/Bronze
que a alimentam.

Como o "destino" de um `.tab`/`.vw` é o próprio objeto criado (CREATE
TABLE/VIEW), mas o de um `.sql`/`.prc` (procedures/ETL sem CREATE) só dá
pra inferir por convenção (INSERT INTO/MERGE INTO/UPDATE), isso é
puramente estático (regex) e best-effort — não substitui uma análise real
de lineage de um motor SQL, mas é o suficiente para apontar candidatos a
tabela Bronze/Silver upstream que os outros artefatos (baseados só em
nome/prefixo) não enxergavam.

Os jobs DataStage exportados (`.dsx`) também entram, mas por um caminho
diferente: o campo `StageNames "A|Transform|B"` de cada job de cópia lista
as etapas do pipeline em ordem — o primeiro e o último pedaço são a
tabela/view de origem e destino da cópia (o(s) estágio(s) do meio são só o
nome do transform, ex.: "Copy_26"). É o elo que fecha View Silver -> Tabela
Gold que os `.vw`/`.sql`/`.prc` sozinhos não enxergam (a view raramente
referencia a tabela Gold final; quem faz essa cópia é o job DataStage).

E a fonte MAIS confiável de todas: a própria aba "Tabelas" do Excel
"Projeto Lakehouse - Tabelas e Pipelines.xlsx" já tem, por LINHA (= mesmo
pipeline), as colunas Bronze/Silver/Gold preenchidas pelo cliente —
`read_excel_pipeline_edges` liga essas colunas direto, sem precisar de
nenhuma heurística sobre script. É o que fecha o rastreio até a última
camada Bronze nos casos em que os scripts não têm nenhum sinal de destino
(ex.: SELECT solto sem CREATE/INSERT, ou nome de arquivo que não bate com
nenhuma tabela conhecida)."""
from __future__ import annotations

import re
from pathlib import Path

from dlctl.core.global_scope import (
    EXTENDED_SCAN_FOLDERS,
    OTHER_SOURCES_DIR_NAME,
    OTHER_SOURCES_SCAN_EXTENSIONS,
    _CREATE_OBJECT_PATTERN,
    _CTE_ALIAS_PATTERN,
    _cte_aliases,
    _extract_tables_from_sql,
    _FROM_JOIN_PATTERN,
    _SQL_TABLE_STOPLIST,
    read_excel_pipeline_edges,
    _norm,
)

# Alvo de scripts .sql/.prc que não usam CREATE TABLE/VIEW (ETLs que fazem
# INSERT/MERGE/UPDATE direto na tabela de destino, ex.: "UPDATE
# FSSUPRI.PR_PURCHASE_ORDER A SET ...").
_TARGET_DML_PATTERN = re.compile(
    r"\b(?:INSERT\s+INTO|MERGE\s+INTO|UPDATE)\s+([A-Za-z_][A-Za-z0-9_$#]*\.[A-Za-z_][A-Za-z0-9_$#]*)",
    re.IGNORECASE,
)

# Pipeline de um job de cópia DataStage: "Origem|EstagioDeTransform|Destino"
# (só o 1º e o último pedaço interessam; o(s) do meio é o nome do estágio,
# não uma tabela — ex.: "DW_AGREEMENT_CF|Copy_26|PR_AGREEMENT").
_DSX_STAGE_NAMES_PATTERN = re.compile(r'StageNames\s+"([^"]+)"')


def _extract_dsx_lineage(content: str) -> set[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    for match in _DSX_STAGE_NAMES_PATTERN.finditer(content):
        parts = [p.strip() for p in match.group(1).split("|") if p.strip()]
        if len(parts) < 3:
            continue  # sem 3+ partes não dá pra distinguir estágio de tabela destino
        source, target = _norm(parts[0]), _norm(parts[-1])
        if source and target and source != target:
            edges.add((source, target))
    return edges


def _extract_targets_and_sources(content: str, suffix: str) -> tuple[set[str], set[str]]:
    cte_aliases = _cte_aliases(content)

    sources: set[str] = set()
    for match in _FROM_JOIN_PATTERN.finditer(content):
        name = _norm(match.group(1).split(".")[-1])
        if name and name not in _SQL_TABLE_STOPLIST and name not in cte_aliases:
            sources.add(name)

    targets: set[str] = set()
    suffix = suffix.lower()
    if suffix in (".tab", ".vw"):
        for match in _CREATE_OBJECT_PATTERN.finditer(content):
            name = _norm(match.group(1))
            if name:
                targets.add(name)
    elif suffix in (".sql", ".prc", ".txt"):
        for match in _TARGET_DML_PATTERN.finditer(content):
            name = _norm(match.group(1).split(".")[-1])
            if name:
                targets.add(name)

    sources -= targets
    return targets, sources


def build_table_dependency_graph(sharedpoint_input: str = "input/sharedpoint", known_tables: set[str] | None = None) -> dict[str, set[str]]:
    """Varre TODAS as subpastas de TODOS os sistemas fonte em
    `input/sharedpoint` (as mesmas do modo estendido) por arquivos
    `.sql`/`.prc`/`.tab`/`.vw`/`.dsx`, mais a pasta solta `input/other_sources/`
    (irmã de `sharedpoint_input`, incluindo `.txt`), e retorna
    `upstream_by_table`: tabela -> conjunto de tabelas que a alimentam
    (FROM/JOIN do script/view que a cria/popula, ou origem do job de cópia
    DataStage que a preenche). Pode ter arquivo duplicado entre as duas
    pastas; a dedup é por nome de tabela (chave do dict retornado).

    Muitos scripts de `3. Script Bronze x Silver` são só um SELECT solto
    (às vezes até comentado), sem CREATE/INSERT/MERGE/UPDATE — sem
    nenhum sinal de qual tabela eles alimentam. Nesses casos, o único
    sinal que sobra é o próprio nome do arquivo: quando o nome do arquivo
    (sem extensão) bate EXATAMENTE com uma tabela já conhecida (achada via
    CREATE TABLE/VIEW em algum outro arquivo, via DataStage, ou passada em
    `known_tables` — ex.: as do Excel/escopo estendido), usamos esse nome
    como destino. Só aceita o nome do arquivo quando ele já é uma tabela
    conhecida de verdade — nunca inventa uma tabela nova a partir só do
    nome do arquivo, pra não poluir a linhagem com destinos fictícios."""
    root = Path(sharedpoint_input)
    upstream: dict[str, set[str]] = {}
    if not root.exists():
        return upstream

    known: set[str] = set(known_tables or ())
    pending: list[tuple[str, set[str]]] = []  # (nome do arquivo normalizado, sources) sem destino confirmado

    def _scan_file(path: Path) -> None:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        if path.suffix.lower() == ".dsx":
            for source, target in _extract_dsx_lineage(content):
                known.add(target)
                upstream.setdefault(target, set()).add(source)
            return
        targets, sources = _extract_targets_and_sources(content, path.suffix)
        if targets:
            known.update(targets)
            if sources:
                for target in targets:
                    upstream.setdefault(target, set()).update(sources)
        elif sources:
            pending.append((_norm(path.stem), sources))

    for domain_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for stage_folder_name in EXTENDED_SCAN_FOLDERS:
            stage_root = domain_dir / stage_folder_name
            if not stage_root.exists():
                continue
            for ext in (".sql", ".prc", ".tab", ".vw", ".dsx"):
                for path in stage_root.rglob(f"*{ext}"):
                    _scan_file(path)

    other_root = root.parent / OTHER_SOURCES_DIR_NAME
    if other_root.exists():
        for ext in OTHER_SOURCES_SCAN_EXTENSIONS:
            for path in other_root.rglob(f"*{ext}"):
                _scan_file(path)

    # Segunda passada: só agora que já sabemos TODAS as tabelas confirmadas
    # (CREATE TABLE/VIEW, DataStage, Excel via known_tables), resolve os
    # scripts pendentes cujo nome de arquivo bate com uma tabela conhecida.
    for stem, sources in pending:
        if stem in known:
            upstream.setdefault(stem, set()).update(sources)

    # Fonte mais confiável de todas: a ligação Bronze/Silver/Gold que o
    # próprio cliente já mapeou, linha a linha, na aba "Tabelas" do Excel.
    for source, target in read_excel_pipeline_edges(sharedpoint_input):
        upstream.setdefault(target, set()).add(source)

    return upstream


def build_mapped_table_dependency_graph(
    sharedpoint_input: str = "input/sharedpoint",
    mapped_tables: set[str] | None = None,
) -> dict[str, set[str]]:
    """Rastreia recursivamente apenas tabelas mapeadas no Excel.

    Para cada semente do Excel, procura arquivos `.sql` e `.vw` cujo nome
    seja a tabela ou uma view equivalente (`TABELA`, `VW_TABELA`,
    `V_TABELA`). As dependências `FROM`/`JOIN` encontradas tornam-se novas
    sementes e são seguidas enquanto houver arquivo correspondente. Assim,
    uma tabela que não está no Excel nem foi alcançada pelo caminho de
    dashboards ainda pode ser descoberta por ser necessária a uma tabela que
    o cliente explicitamente pediu para migrar.

    O nome da tabela é a chave de deduplicação: o mesmo objeto referenciado
    por vários arquivos ou encontrado em `sharedpoint` e `other_sources`
    produz uma única tabela e uma única aresta.
    """
    root = Path(sharedpoint_input)
    if not root.exists():
        return {}

    seeds = {_norm(name) for name in (mapped_tables or set()) if _norm(name)}
    if not seeds:
        return {}

    file_by_stem: dict[str, list[Path]] = {}
    scan_extensions = {".sql", ".vw"}
    scan_roots = [root]
    other_root = root.parent / OTHER_SOURCES_DIR_NAME
    if other_root.exists():
        scan_roots.append(other_root)
    for scan_root in scan_roots:
        for path in scan_root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in scan_extensions:
                continue
            file_by_stem.setdefault(_norm(path.stem), []).append(path)

    def _candidate_stems(table: str) -> set[str]:
        table = _norm(table)
        stems = {table}
        if table.startswith("VW_"):
            stems.add(table[3:])
        elif table.startswith("V_"):
            stems.add(table[2:])
        else:
            stems.update({f"VW_{table}", f"V_{table}"})
        return stems

    upstream: dict[str, set[str]] = {}
    pending = list(seeds)
    visited_tables: set[str] = set()
    visited_files: set[Path] = set()
    while pending:
        target = pending.pop()
        if target in visited_tables:
            continue
        visited_tables.add(target)
        for stem in _candidate_stems(target):
            for path in file_by_stem.get(stem, []):
                if path in visited_files:
                    continue
                visited_files.add(path)
                try:
                    content = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                sources = _extract_tables_from_sql(content, path.suffix)
                sources.discard(target)
                if not sources:
                    continue
                upstream.setdefault(target, set()).update(sources)
                pending.extend(source for source in sources if source not in visited_tables)

    return upstream


def trace_upstream(seed_tables: set[str], upstream_by_table: dict[str, set[str]], max_depth: int = 12) -> tuple[set[str], set[tuple[str, str]]]:
    """BFS retroativo a partir de `seed_tables` seguindo `upstream_by_table`
    até não achar mais nada (ou `max_depth`). Retorna (todas as tabelas
    visitadas, incluindo as seeds; arestas (tabela_origem, tabela_destino))."""
    visited: set[str] = set(seed_tables)
    edges: set[tuple[str, str]] = set()
    frontier = list(seed_tables)
    depth = 0
    while frontier and depth < max_depth:
        next_frontier = []
        for table in frontier:
            for src in upstream_by_table.get(table, ()):
                edges.add((src, table))
                if src not in visited:
                    visited.add(src)
                    next_frontier.append(src)
        frontier = next_frontier
        depth += 1
    return visited, edges
