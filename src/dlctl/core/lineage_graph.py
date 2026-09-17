"""dlctl.core.lineage_graph

Construção e isolamento do grafo de linhagem (portado/adaptado de
`lineage_app.py` do Skill-LineageFabric), operando sobre os registros
persistidos em `dlctl.core.state.LineageDependency` — a mesma fonte usada
pelo CLI (`dlctl lineage isolate`) e pelo dashboard (página de Grafo).

O "Mapa Isolado" de uma tabela/fonte é o subgrafo formado pelos ancestrais
(upstream) e/ou descendentes (downstream) daquele nó, exatamente a regra
documentada em `docs/lineage-report.md` do projeto original.
"""
from __future__ import annotations

from typing import Iterable, Optional

import networkx as nx

DATA_LAYER_ORDER = ["bronze", "silver", "gold", "semantic", "other_layer"]
DATA_LAYER_POSITION = {name: index for index, name in enumerate(DATA_LAYER_ORDER)}

DATA_LAYER_COLORS = {
    "bronze": "#B66A36",
    "silver": "#4EA5B7",
    "gold": "#D6A233",
    "semantic": "#8B6FC7",
    "other_layer": "#8E8E93",
}
DATA_LAYER_LABELS = {
    "bronze": "Bronze",
    "silver": "Silver",
    "gold": "Gold",
    "semantic": "Semântica (MLV)",
    "other_layer": "Outra camada / Fonte",
}

Direction = str  # "Downstream" | "Upstream" | "Linhagem completa"


def clean_value(value: object, fallback: str = "NÃO INFORMADO") -> str:
    text = str(value).strip()
    return text if text and text.lower() != "nan" else fallback


def data_layer_name(value: object) -> str:
    layer = clean_value(value).lower()
    return layer if layer in DATA_LAYER_POSITION else "other_layer"


def layer_node_id(layer: object, lakehouse: object, schema: object, table: object) -> str:
    return "TABLE::" + "::".join(clean_value(value) for value in (layer, lakehouse, schema, table))


def _add_node(
    graph: nx.DiGraph,
    layer: object, lakehouse: object, schema: object, table: object,
    status: object = "", domain: object = "", note: object = "",
) -> str:
    node_id = layer_node_id(layer, lakehouse, schema, table)
    if graph.has_node(node_id):
        return node_id

    layer_type = data_layer_name(layer)
    layer_name = clean_value(layer)
    lakehouse_name = clean_value(lakehouse)
    schema_name = clean_value(schema)
    table_name = clean_value(table)
    status_name = clean_value(status, "Não informado")
    domain_name = clean_value(domain, "Não informado")
    note_name = clean_value(note, "")
    tooltip = (
        f"<b>{table_name}</b><br>Camada: {layer_name}<br>"
        f"Lakehouse: {lakehouse_name}<br>Schema: {schema_name}<br>"
        f"Status: {status_name}<br>Domínio: {domain_name}"
    )
    if note_name:
        tooltip += f"<br>Observação: {note_name}"

    graph.add_node(
        node_id,
        label=table_name, node_type=layer_type, layer=DATA_LAYER_POSITION[layer_type],
        tooltip=tooltip, lakehouse=lakehouse_name, schema=schema_name, table=table_name,
        data_layer=layer_name, status=status_name, domain=domain_name,
    )
    return node_id


def build_dependency_graph(dependencies: Iterable) -> nx.DiGraph:
    """Constrói o grafo dirigido origem->destino a partir de registros
    `LineageDependency` (ou de dicts com as mesmas chaves em inglês)."""
    graph = nx.DiGraph()
    for row in dependencies:
        get = row.get if isinstance(row, dict) else lambda field, default="": getattr(row, field, default)
        source_id = _add_node(
            graph, get("source_layer", ""), get("source_lakehouse", ""),
            get("source_schema", ""), get("source_table", ""),
            status=get("source_status", ""), domain=get("domain", ""), note=get("note", ""),
        )
        target_id = _add_node(
            graph, get("target_layer", ""), get("target_lakehouse", ""),
            get("target_schema", ""), get("target_table", ""),
            status=get("target_status", ""), domain=get("domain", ""), note=get("note", ""),
        )
        graph.add_edge(source_id, target_id, dependency=get("dependency_type", ""))
    return graph


def node_option_label(graph: nx.DiGraph, node_id: str) -> str:
    data = graph.nodes[node_id]
    values = [str(v).strip() for v in (data.get("data_layer"), data.get("lakehouse"), data.get("schema"), data.get("table")) if str(v).strip()]
    return " | ".join(values)


def find_nodes_by_term(graph: nx.DiGraph, term: str) -> list[str]:
    term = term.strip().casefold()
    if not term:
        return []
    return [
        node for node, data in graph.nodes(data=True)
        if term in " ".join(str(data.get(f, "")) for f in ("label", "table", "schema", "lakehouse", "data_layer")).casefold()
        or term in str(node).casefold()
    ]


def isolate_nodes(graph: nx.DiGraph, node_ids: Iterable[str], direction: Direction = "Linhagem completa") -> nx.DiGraph:
    """Isola o "Mapa Isolado" de um ou mais nós: upstream (ancestrais),
    downstream (descendentes) ou ambos, conforme `direction`."""
    node_ids = [n for n in node_ids if graph.has_node(n)]
    if not node_ids:
        return nx.DiGraph()

    related = set(node_ids)
    for node in node_ids:
        if direction in ("Downstream", "Linhagem completa"):
            related.update(nx.descendants(graph, node))
        if direction in ("Upstream", "Linhagem completa"):
            related.update(nx.ancestors(graph, node))
    return graph.subgraph(related).copy()


def isolate_by_term(graph: nx.DiGraph, term: str, direction: Direction = "Linhagem completa") -> tuple[nx.DiGraph, list[str]]:
    matches = find_nodes_by_term(graph, term)
    return isolate_nodes(graph, matches, direction), matches


def summarize_by_layer(graph: nx.DiGraph) -> dict[str, list[str]]:
    """Agrupa os nós do (sub)grafo por camada, para relatórios em texto
    (equivalente ao `docs/lineage-report.md` original)."""
    summary: dict[str, list[str]] = {layer: [] for layer in DATA_LAYER_ORDER}
    for _, data in graph.nodes(data=True):
        layer = data.get("node_type", "other_layer")
        summary.setdefault(layer, []).append(data.get("table", ""))
    for layer in summary:
        summary[layer] = sorted(set(filter(None, summary[layer])))
    return summary


def hierarchical_layout(graph: nx.DiGraph, x_gap: float = 3.0, y_gap: float = 2.0) -> dict:
    layers: dict[int, list] = {}
    for node, data in graph.nodes(data=True):
        layers.setdefault(data.get("layer", 0), []).append(node)

    pos = {}
    for layer_idx, nodes in sorted(layers.items()):
        x = layer_idx * x_gap
        n = len(nodes)
        for i, node in enumerate(sorted(nodes)):
            y = (i - (n - 1) / 2) * y_gap
            pos[node] = (x, y)
    return pos


def build_plotly_figure(graph: nx.DiGraph, title: str = "Mapa de Linhagem"):
    """Renderiza o (sub)grafo em Plotly (requer `plotly`, dependência do
    extra `dashboard`). Import feito localmente para manter este módulo
    utilizável pelo CLI (texto) sem exigir plotly instalado."""
    import plotly.graph_objects as go

    if len(graph.nodes) == 0:
        fig = go.Figure()
        fig.add_annotation(text="Nenhum nó encontrado para os filtros atuais.", x=0.5, y=0.5, showarrow=False, font=dict(size=16))
        fig.update_layout(paper_bgcolor="#0E1117", plot_bgcolor="#0E1117", font=dict(color="white"))
        return fig

    pos = hierarchical_layout(graph)

    edge_x, edge_y = [], []
    for u, v in graph.edges():
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]

    traces = [
        go.Scatter(x=edge_x, y=edge_y, mode="lines", line=dict(width=1.2, color="#AAAAAA"), hoverinfo="none", showlegend=False),
        go.Scatter(
            x=[pos[v][0] for _, v in graph.edges()], y=[pos[v][1] for _, v in graph.edges()],
            mode="markers", marker=dict(symbol="arrow", size=10, color="#888888", angleref="previous", standoff=12),
            hoverinfo="none", showlegend=False,
        ),
    ]

    for node_type in DATA_LAYER_ORDER:
        nodes_of_type = [n for n, d in graph.nodes(data=True) if d.get("node_type") == node_type]
        if not nodes_of_type:
            continue
        nx_list, ny_list, labels, tooltips = [], [], [], []
        for n in nodes_of_type:
            x, y = pos[n]
            nx_list.append(x)
            ny_list.append(y)
            labels.append(graph.nodes[n].get("label", n)[:30])
            tooltips.append(graph.nodes[n].get("tooltip", n))
        traces.append(go.Scatter(
            x=nx_list, y=ny_list, mode="markers+text", name=DATA_LAYER_LABELS[node_type],
            marker=dict(size=18, color=DATA_LAYER_COLORS[node_type], line=dict(color="white", width=1.5)),
            text=labels, textposition="top center", textfont=dict(size=9),
            hovertext=tooltips, hoverinfo="text",
        ))

    fig = go.Figure(data=traces)
    fig.update_layout(
        title=dict(text=title, font=dict(size=16)), showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="closest", margin=dict(l=20, r=20, t=60, b=20),
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        paper_bgcolor="#0E1117", plot_bgcolor="#0E1117", font=dict(color="white"), height=700,
    )
    return fig
