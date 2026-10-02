"""Módulo de modernização da rotina de fechamento financeiro de contas.

Substitui a procedure legada PL/pgSQL `sp_processa_fechamento` por uma
implementação moderna em Python 3.14 com SQLAlchemy 2.x, tipagem estática rigorosa,
controle transacional e tratamento estrito de precisão financeira decimal.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN
import json
import logging
from typing import Any, Final

from sqlalchemy import (
    BigInteger,
    Column,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    func,
    select,
    update,
)
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

# Configuração do Logger Estruturado
logger: logging.Logger = logging.getLogger("financeiro.fechamento")
logger.setLevel(logging.INFO)

# Definição dos Metadados das Tabelas
metadata: MetaData = MetaData()

contas_table: Final[Table] = Table(
    "contas",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("status", String(50), nullable=False),
)

transacoes_table: Final[Table] = Table(
    "transacoes",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("conta_origem_id", BigInteger, nullable=False),
    Column("valor", Numeric(precision=15, scale=2), nullable=False),
)

DECIMAL_ZERO_DUAS_CASAS: Final[Decimal] = Decimal("0.00")
QUANTIZE_EXPONENT: Final[Decimal] = Decimal("0.01")


# Hierarquia de Exceções de Domínio
class FechamentoError(Exception):
    """Exceção base para erros durante o fechamento de contas."""

    def __init__(self, message: str, detalhes: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message: str = message
        self.detalhes: dict[str, Any] = detalhes or {}


class ContaInexistenteFechamentoError(FechamentoError):
    """Lançada quando a conta informada para fechamento não existe ou não pôde ser atualizada."""

    def __init__(self, conta_id: int) -> None:
        super().__init__(
            message="Conta inexistente para fechamento",
            detalhes={"conta_id": conta_id, "codigo_erro": "CONTA_INEXISTENTE"},
        )


# DTO de Resposta (Encapsulando Parâmetros OUT)
@dataclass(frozen=True, slots=True)
class ResultadoFechamentoDTO:
    """Encapsula os parâmetros OUT do processamento de fechamento."""

    conta_id: int
    total_processado: Decimal
    qtd_transacoes: int

    def __post_init__(self) -> None:
        if not isinstance(self.total_processado, Decimal):
            raise TypeError("O campo 'total_processado' deve ser estritamente do tipo Decimal.")
        if not isinstance(self.qtd_transacoes, int):
            raise TypeError("O campo 'qtd_transacoes' deve ser estritamente do tipo int.")


def _auditar_evento(evento: str, payload: dict[str, Any], nivel: int = logging.INFO) -> None:
    """Registra entradas de log em formato JSON padronizado para auditoria."""
    registro: dict[str, Any] = {
        "modulo": "sp_processa_fechamento",
        "evento": evento,
        "dados": payload,
    }
    logger.log(nivel, json.dumps(registro, default=str))


def processa_fechamento(session: Session, conta_id: int) -> ResultadoFechamentoDTO:
    """Executa o fechamento de uma conta e agrega as transações associadas.

    Equivalente à procedure legada `sp_processa_fechamento`. Atualiza o status
    da conta para 'EM_PROCESSAMENTO' obtendo lock implícito de linha no PostgreSQL,
    valida a alteração via rowcount e calcula a soma e a contagem das transações
    de origem em uma operação set-based atômica.

    Args:
        session: Sessão ativa do SQLAlchemy gerenciadora da conexão.
        conta_id: Identificador único da conta a ser processada.

    Returns:
        ResultadoFechamentoDTO: DTO imutável contendo o saldo agregado e a
        quantidade de transações processadas.

    Raises:
        ContaInexistenteFechamentoError: Se a conta não for encontrada.
        FechamentoError: Se ocorrer uma falha operacional de banco de dados.
    """
    _auditar_evento("INICIO_FECHAMENTO", {"conta_id": conta_id})

    try:
        with session.begin_nested() if session.in_transaction() else session.begin():
            # 1. Atualização do status com aquisição de trava atômica de linha
            stmt_update = (
                update(contas_table)
                .where(contas_table.c.id == conta_id)
                .values(status="EM_PROCESSAMENTO")
            )
            result_update = session.execute(stmt_update)

            # 2. Avaliação de linhas afetadas (GET DIAGNOSTICS v_rows = ROW_COUNT)
            if result_update.rowcount == 0:
                _auditar_evento(
                    "CONTA_NAO_ENCONTRADA",
                    {"conta_id": conta_id, "rowcount": result_update.rowcount},
                    nivel=logging.WARNING,
                )
                raise ContaInexistenteFechamentoError(conta_id=conta_id)

            # 3. Consulta agregada set-based direta (evita loops iterativos / N+1)
            stmt_agregacao = select(
                func.coalesce(
                    func.sum(transacoes_table.c.valor), DECIMAL_ZERO_DUAS_CASAS
                ).label("total_processado"),
                func.count().label("qtd_transacoes"),
            ).where(transacoes_table.c.conta_origem_id == conta_id)

            row = session.execute(stmt_agregacao).one()

            total_processado_raw: Any = row.total_processado
            qtd_transacoes_raw: Any = row.qtd_transacoes

            # 4. Assegurar precisão financeira estrita sem aproximações de ponto flutuante
            total_processado: Decimal = (
                total_processado_raw
                if isinstance(total_processado_raw, Decimal)
                else Decimal(str(total_processado_raw))
            ).quantize(QUANTIZE_EXPONENT, rounding=ROUND_HALF_EVEN)

            qtd_transacoes: int = int(qtd_transacoes_raw)

            resultado = ResultadoFechamentoDTO(
                conta_id=conta_id,
                total_processado=total_processado,
                qtd_transacoes=qtd_transacoes,
            )

            _auditar_evento(
                "SUCESSO_FECHAMENTO",
                {
                    "conta_id": conta_id,
                    "total_processado": str(resultado.total_processado),
                    "qtd_transacoes": resultado.qtd_transacoes,
                },
            )

            return resultado

    except ContaInexistenteFechamentoError:
        raise
    except SQLAlchemyError as ex:
        session.rollback()
        _auditar_evento(
            "ERRO_SISTEMICO_FECHAMENTO",
            {"conta_id": conta_id, "erro": str(ex)},
            nivel=logging.ERROR,
        )
        raise FechamentoError(
            message=f"Falha de integridade ao processar fechamento da conta {conta_id}.",
            detalhes={"conta_id": conta_id, "origem": str(ex)},
        ) from ex
    except Exception as ex:
        session.rollback()
        _auditar_evento(
            "ERRO_INESPERADO_FECHAMENTO",
            {"conta_id": conta_id, "erro": str(ex)},
            nivel=logging.CRITICAL,
        )
        raise FechamentoError(
            message=f"Erro inesperado no fechamento da conta {conta_id}.",
            detalhes={"conta_id": conta_id, "origem": str(ex)},
        ) from ex
