"""Módulo de modernização da rotina de auditoria de contas (sp_auditoria_contas).

Decisão de Arquitetura e Mitigação de Riscos:
- Erradicação de N+1: O procedimento legado utilizava um CURSOR iterativo com
  PERFORM COUNT(*) para cada conta ativa, gerando degradação exponencial de I/O
  (O(N) queries).
- Estratégia Adotada: Substituição por agregação set-based única via LEFT JOIN
  e GROUP BY, combinada com processamento em fluxo paginado/streamed via
  'yield_per' para preservar a memória operacional do container/microsserviço
  sem onerar a base com requisições repetitivas.
- Precisão Financeira: Valores monetários utilizam estritamente decimal.Decimal.
"""

from dataclasses import asdict, dataclass
from decimal import Decimal
import json
import logging
import time
from typing import Generator, Sequence
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Column,
    MetaData,
    Numeric,
    String,
    Table,
    func,
    select,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

# Configuração de Logger Estruturado JSON
logger = logging.getLogger("auditoria.contas")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# --- Hierarquia de Exceções de Domínio ---
class AuditoriaError(Exception):
    """Exceção base para falhas de domínio na rotina de auditoria."""


class AuditoriaDatabaseError(AuditoriaError):
    """Exceção levantada em caso de falha de conexão ou execução SQL."""


# --- Metadados e Modelagem Core ---
metadata = MetaData()

contas_table = Table(
    "contas",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("saldo", Numeric(15, 2), nullable=False),
    Column("status", String(20), nullable=False),
)

transacoes_table = Table(
    "transacoes",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("conta_origem_id", BigInteger, nullable=False),
)


# --- DTOs e Tipagem com Imutabilidade ---
@dataclass(frozen=True, slots=True)
class ItemAuditoriaDTO:
    """Representação imutável da auditoria de uma conta individual."""

    conta_id: int
    saldo: Decimal
    total_transacoes: int


@dataclass(frozen=True, slots=True)
class RelatorioAuditoriaDTO:
    """Resultado consolidado da auditoria de contas."""

    execution_id: str
    total_contas_auditadas: int
    tempo_execucao_ms: Decimal
    itens: tuple[ItemAuditoriaDTO, ...]


def _log_audit_event(
    execution_id: str,
    event: str,
    payload: dict[str, object],
    level: int = logging.INFO,
) -> None:
    """Emite logs de auditoria padronizados em JSON estruturado."""
    log_data = {
        "timestamp": time.time(),
        "execution_id": execution_id,
        "event": event,
        "payload": payload,
    }
    logger.log(level, json.dumps(log_data, default=str))


def _build_auditoria_query() -> select:
    """Constrói a query set-based unificada, eliminando o problema clássico de N+1.

    Realiza agregação (COUNT) diretamente no motor do banco de dados em uma
    única varredura via LEFT OUTER JOIN e agrupamento determinístico.
    """
    return (
        select(
            contas_table.c.id.label("conta_id"),
            contas_table.c.saldo.label("saldo"),
            func.coalesce(func.count(transacoes_table.c.id), 0).label(
                "total_transacoes"
            ),
        )
        .select_from(
            contas_table.outerjoin(
                transacoes_table,
                transacoes_table.c.conta_origem_id == contas_table.c.id,
            )
        )
        .where(contas_table.c.status == "ATIVA")
        .group_by(contas_table.c.id, contas_table.c.saldo)
        .order_by(contas_table.c.id.asc())
    )


def stream_auditoria_contas(
    session: Session,
    chunk_size: int = 1000,
) -> Generator[ItemAuditoriaDTO, None, None]:
    """Transmite os registros auditados em blocos (chunk streaming).

    Preserva a estabilidade de consumo de memória da aplicação via cursor
    server-side/yield_per, eliminando gargalos de queries unitárias.

    :param session: Sessão ativa do SQLAlchemy.
    :param chunk_size: Quantidade de registros por lote de busca do cursor.
    :return: Generator contendo itens imutáveis de auditoria.
    """
    stmt = _build_auditoria_query()

    try:
        result_proxy = session.execute(stmt.execution_options(yield_per=chunk_size))
        for row in result_proxy:
            yield ItemAuditoriaDTO(
                conta_id=int(row.conta_id),
                saldo=Decimal(str(row.saldo)),
                total_transacoes=int(row.total_transacoes),
            )
    except SQLAlchemyError as exc:
        raise AuditoriaDatabaseError(
            f"Falha de banco ao processar streaming de auditoria: {exc}"
        ) from exc


def executar_auditoria_contas(
    session: Session,
    chunk_size: int = 1000,
) -> RelatorioAuditoriaDTO:
    """Executa a rotina modernizada de auditoria de contas ativas.

    Substitui a chamada procedural 'sp_auditoria_contas()' por uma transação
    isolada atômica de leitura, mitigando contenções e calculando agregações
    em nível relacional otimizado.

    :param session: Sessão do SQLAlchemy.
    :param chunk_size: Tamanho do chunk para processamento em streaming.
    :return: DTO imutável com sumário e detalhamento auditado.
    """
    execution_id = str(uuid4())
    start_time = time.perf_counter()

    _log_audit_event(
        execution_id=execution_id,
        event="AUDITORIA_INICIADA",
        payload={"chunk_size": chunk_size},
    )

    try:
        with session.begin():
            itens_auditados: list[ItemAuditoriaDTO] = list(
                stream_auditoria_contas(session=session, chunk_size=chunk_size)
            )

        elapsed_ms = Decimal(str(round((time.perf_counter() - start_time) * 1000, 2)))

        relatorio = RelatorioAuditoriaDTO(
            execution_id=execution_id,
            total_contas_auditadas=len(itens_auditados),
            tempo_execucao_ms=elapsed_ms,
            itens=tuple(itens_auditados),
        )

        _log_audit_event(
            execution_id=execution_id,
            event="AUDITORIA_CONCLUIDA",
            payload={
                "total_contas": relatorio.total_contas_auditadas,
                "tempo_ms": str(relatorio.tempo_execucao_ms),
            },
        )

        return relatorio

    except AuditoriaDatabaseError as exc:
        _log_audit_event(
            execution_id=execution_id,
            event="AUDITORIA_FALHA_DB",
            payload={"error": str(exc)},
            level=logging.ERROR,
        )
        raise

    except Exception as exc:
        _log_audit_event(
            execution_id=execution_id,
            event="AUDITORIA_FALHA_FATAL",
            payload={"error": str(exc)},
            level=logging.CRITICAL,
        )
        raise AuditoriaError(
            f"Erro inesperado durante a execução da auditoria: {exc}"
        ) from exc