"""dlctl.connectors.oracle_connector

Conector real para Oracle Fusion: leitura via banco (python-oracledb, thin
mode — sem Oracle Client necessário) e extração via BI Publisher SOAP
(zeep), usado pelo `nb_bipublisher_fusion` na skill constellation_fusion_pattern.

As dependências oracledb/zeep são opcionais (extra `oracle`). Se ausentes, os
métodos levantam OracleConnectorError com uma mensagem manual_required em vez
de quebrar a importação do resto do CLI.
"""
from __future__ import annotations

from typing import Any, Optional

from dlctl.config import Profile


class OracleConnectorError(RuntimeError):
    pass


class OracleDbConnector:
    """Executa queries de leitura no Oracle via python-oracledb (thin mode)."""

    def __init__(self, profile: Profile):
        self.profile = profile
        self.oracle_cfg = profile.oracle
        if not (self.oracle_cfg.dsn and self.oracle_cfg.user and self.oracle_cfg.password):
            raise OracleConnectorError(
                "ORACLE_DB_DSN/ORACLE_DB_USER/ORACLE_DB_PASSWORD não configurados no .env."
            )

    def _connect(self):
        try:
            import oracledb  # type: ignore
        except ImportError as exc:
            raise OracleConnectorError(
                "Pacote 'oracledb' não instalado. Rode: pip install dlctl[oracle]"
            ) from exc
        return oracledb.connect(
            user=self.oracle_cfg.user,
            password=self.oracle_cfg.password,
            dsn=self.oracle_cfg.dsn,
        )

    def test_connection(self) -> dict:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT SYSDATE FROM DUAL")
            (dt,) = cur.fetchone()
            return {"status": "ok", "server_time": str(dt)}
        finally:
            conn.close()

    def fetch(self, sql: str, params: Optional[dict] = None, limit: int = 1000) -> list[dict]:
        """Executa uma query de LEITURA e retorna até `limit` linhas como dicts.
        Nunca deve ser usado para tabelas Bronze completas (usar BI Publisher /
        pipeline de ingestão para isso); serve para amostras/validação."""
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(sql, params or {})
            cur.arraysize = min(limit, 1000)
            columns = [d[0] for d in cur.description]
            rows = cur.fetchmany(limit)
            return [dict(zip(columns, row)) for row in rows]
        finally:
            conn.close()


class OracleBipConnector:
    """Cliente SOAP do Oracle BI Publisher (Fusion), usado pela ingestão
    Bronze genérica `nb_bipublisher_fusion`."""

    WSDL_SUFFIX = "/xmlpserver/services/ExternalReportWSSService?WSDL"

    def __init__(self, profile: Profile):
        self.profile = profile
        self.oracle_cfg = profile.oracle
        if not (self.oracle_cfg.bip_base_url and self.oracle_cfg.bip_user and self.oracle_cfg.bip_password):
            raise OracleConnectorError(
                "ORACLE_BIP_BASE_URL/ORACLE_BIP_USER/ORACLE_BIP_PASSWORD não configurados no .env."
            )

    def _client(self):
        try:
            from zeep import Client  # type: ignore
            from zeep.transports import Transport  # type: ignore
            from requests import Session
            from requests.auth import HTTPBasicAuth
        except ImportError as exc:
            raise OracleConnectorError(
                "Pacote 'zeep' não instalado. Rode: pip install dlctl[oracle]"
            ) from exc
        session = Session()
        session.auth = HTTPBasicAuth(self.oracle_cfg.bip_user, self.oracle_cfg.bip_password)
        transport = Transport(session=session)
        wsdl = f"{self.oracle_cfg.bip_base_url.rstrip('/')}{self.WSDL_SUFFIX}"
        return Client(wsdl, transport=transport)

    def run_report(self, report_absolute_path: str, parameters: Optional[dict[str, Any]] = None,
                   output_format: str = "CSV") -> bytes:
        """Executa um relatório BI Publisher e retorna os bytes do resultado
        (tipicamente CSV), para landing em Bronze."""
        client = self._client()
        report_request = {
            "reportAbsolutePath": report_absolute_path,
            "attributeFormat": output_format,
            "parameterNameValues": {
                "item": [{"name": k, "values": {"item": [v]}} for k, v in (parameters or {}).items()]
            },
        }
        response = client.service.runReport(reportRequest=report_request,
                                             userID=self.oracle_cfg.bip_user,
                                             password=self.oracle_cfg.bip_password)
        return response.reportBytes

    def test_connection(self) -> dict:
        client = self._client()
        return {"status": "ok", "wsdl_operations": list(client.service.__dir__())[:5]}
