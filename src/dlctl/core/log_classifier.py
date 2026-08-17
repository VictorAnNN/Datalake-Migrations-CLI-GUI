"""dlctl.core.log_classifier

Classificador phase-aware de logs (driver-log / Spark), replicando o
`finalize_execution.py` citado no Incidente 2 (P0 "Classificador phase-aware
de logs não está integrado à CLI"):

Famílias conhecidas de ruído/eventos "esperados" da plataforma:
- metadata sidecar com fallback
- descoberta de alvo durante criação inicial
- descoberta de shadow blue-green
- resolução inicial OneSecurity
- teardown pós-METRICS
- teardown de Storage client

Regra de segurança (não-negociável, conforme o incidente): **qualquer
assinatura desconhecida é classificada como NEVER_PASS por padrão** — ou
seja, o classificador nunca "deixa passar" silenciosamente um log que não
reconhece. Isso intencionalmente bloqueia, não permite, o desconhecido.

100% offline — opera sobre texto de log fornecido localmente (arquivo ou
string colada na UI). Nenhuma chamada de rede.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Cada família: (nome, regex, veredito quando casa)
KNOWN_FAMILIES: list[tuple[str, re.Pattern, str]] = [
    ("metadata_sidecar_fallback",
     re.compile(r"metadata sidecar.*fallback|sidecar.*not found.*fallback", re.IGNORECASE), "PASS"),
    ("target_discovery_initial_creation",
     re.compile(r"(discovering|resolving) target.*(initial|creation)", re.IGNORECASE), "PASS"),
    ("shadow_blue_green_discovery",
     re.compile(r"shadow.*(blue|green)|blue-green.*discovery", re.IGNORECASE), "PASS"),
    ("onesecurity_initial_resolution",
     re.compile(r"onesecurity.*resolv|initial.*onesecurity", re.IGNORECASE), "PASS"),
    ("post_metrics_teardown",
     re.compile(r"teardown.*metrics|metrics.*teardown|shutting down.*metrics", re.IGNORECASE), "PASS"),
    ("storage_client_teardown",
     re.compile(r"storage.?client.*(teardown|shutdown|closing)", re.IGNORECASE), "PASS"),
    ("interrupted_after_completed",
     re.compile(r"InterruptedException", re.IGNORECASE), "PASS_IF_AFTER_COMPLETED"),
    ("notebook_completed",
     re.compile(r"\b(job|notebook).*(completed|succeeded)\b", re.IGNORECASE), "COMPLETED_MARKER"),
    ("known_error_signature",
     re.compile(r"\b(FATAL|Traceback \(most recent call last\)|OutOfMemoryError|py4j\.protocol\.Py4JJavaError)\b"), "FAIL"),
]


@dataclass
class LogLineVerdict:
    line_number: int
    line: str
    family: str
    verdict: str  # PASS | FAIL | NEVER_PASS


@dataclass
class ClassificationOutcome:
    overall: str  # PASS | FAIL | NEVER_PASS
    total_lines: int
    completed_marker_seen: bool
    line_verdicts: list[LogLineVerdict] = field(default_factory=list)
    unknown_lines: list[str] = field(default_factory=list)
    functional_exit: str = ""  # linhas relevantes após --extract-notebook-exit


def classify_log(log_text: str, extract_notebook_exit: bool = True) -> ClassificationOutcome:
    """Classifica um log linha a linha. Regra dura: linha sem família
    reconhecida E que pareça relevante (não vazia/whitespace) é NEVER_PASS
    a menos que uma família conhecida de PASS já tenha coberto a linha."""
    lines = log_text.splitlines()
    verdicts: list[LogLineVerdict] = []
    unknown: list[str] = []
    completed_seen = False
    overall = "PASS"

    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue

        matched_family = None
        matched_verdict = None
        for family, pattern, verdict in KNOWN_FAMILIES:
            if pattern.search(stripped):
                matched_family = family
                matched_verdict = verdict
                break

        if matched_family == "notebook_completed":
            completed_seen = True
            verdicts.append(LogLineVerdict(i, stripped, matched_family, "PASS"))
            continue

        if matched_family == "interrupted_after_completed":
            verdict = "PASS" if completed_seen else "FAIL"
            verdicts.append(LogLineVerdict(i, stripped, matched_family, verdict))
            if verdict == "FAIL":
                overall = "FAIL"
            continue

        if matched_family == "known_error_signature":
            verdicts.append(LogLineVerdict(i, stripped, matched_family, "FAIL"))
            overall = "FAIL"
            continue

        if matched_family:
            verdicts.append(LogLineVerdict(i, stripped, matched_family, "PASS"))
            continue

        # Assinatura desconhecida: NEVER_PASS por padrão (regra dura do incidente).
        verdicts.append(LogLineVerdict(i, stripped, "unknown", "NEVER_PASS"))
        unknown.append(stripped)
        if overall != "FAIL":
            overall = "NEVER_PASS"

    functional_exit = ""
    if extract_notebook_exit:
        functional_lines = [
            v.line for v in verdicts
            if v.family in {"notebook_completed", "known_error_signature"}
            or (v.family == "interrupted_after_completed" and v.verdict == "FAIL")
        ]
        functional_exit = "\n".join(functional_lines)

    return ClassificationOutcome(
        overall=overall, total_lines=len(lines), completed_marker_seen=completed_seen,
        line_verdicts=verdicts, unknown_lines=unknown, functional_exit=functional_exit,
    )
