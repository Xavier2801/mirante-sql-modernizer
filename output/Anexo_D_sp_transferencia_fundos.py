"""Módulo de modernização da procedure legada sp_transferencia_fundos.

Este módulo implementa a lógica transacional para transferência de fundos
entre contas bancárias com precisão decimal, bloqueio pessimista de concorrência
(FOR UPDATE) e isolamento ACID via SQLAlchemy.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import logging
from typing import Any, Final

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String, select
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

logger = logging.getLogger(__name__)

TIPO_TRANSACAO_TRANSFERENCIA: Final[str] = "TRANSFERENCIA"
VALOR_MINIMO_TRANSFERENCIA: Final[Decimal] = Decimal("0.01")


# ---------------------------------------------------------------------------
# HIERARQUIA DE EXCEÇÕES DE NEGÓCIO
# ---------------------------------------------------------------------------


class TransferenciaError(Exception):
    """Exceção base para falhas operacionais e de negócio na transferência."""

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.context = context or {}


class SaldoInsuficienteError(TransferenciaError):
    """Lançada quando a conta de origem não possui saldo suficiente (RAISE EXCEPTION legado)."""


class ContaNaoEncontradaError(TransferenciaError):
    """Lançada quando a conta de origem ou destino não existe no banco de dados."""


class ValorInvalidoError(TransferenciaError):
    """Lançada quando o montante a ser transferido é menor ou igual a zero."""


class ContasIdenticasError(TransferenciaError):
    """Lançada quando as contas de origem e destino são idênticas."""


# ---------------------------------------------------------------------------
# MODELAGEM ORM (SQLAlchemy 2.0+)
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    """Classe base declarativa para mapeamento de entidades ORM."""


class Conta(Base):
    """Mapeamento da tabela de contas bancárias."""

    __tablename__ = "contas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    saldo: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)


class Transacao(Base):
    """Mapeamento do histórico de transações financeiras."""

    __tablename__ = "transacoes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conta_origem_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("contas.id"), nullable=False
    )
    conta_destino_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("contas.id"), nullable=False
    )
    valor: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    tipo: Mapped[str] = mapped_column(String(50), nullable=False)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


# ---------------------------------------------------------------------------
# DATA TRANSFER OBJECTS (DTO)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TransferenciaInput:
    """Parâmetros de entrada para execução da transferência bancária."""

    conta_origem_id: int
    conta_destino_id: int
    valor: Decimal


@dataclass(frozen=True, slots=True)
class TransferenciaOutput:
    """DTO imutável contendo o recibo e diagnósticos de execução da transferência."""

    transacao_id: int
    conta_origem_id: int
    conta_destino_id: int
    valor: Decimal
    saldo_origem_remanescente: Decimal
    saldo_destino_atualizado: Decimal
    data_hora: datetime


# ---------------------------------------------------------------------------
# SERVIÇO DE EXECUÇÃO DA TRANSFERÊNCIA
# ---------------------------------------------------------------------------


def transferir_fundos(
    session: Session,
    dados: TransferenciaInput,
) -> TransferenciaOutput:
    """Executa transferência de fundos com bloqueio pessimista e integridade ACID.

    Substitui a rotina legada `sp_transferencia_fundos`. Aplica ordenação determinística
    de locks para mitigar deadlocks concorrentes e validações estritas de saldo monetário.

    Args:
        session: Sessão transacional ativa do SQLAlchemy.
        dados: Objeto tipado contendo contas e valor monetário com precisão Decimal.

    Returns:
        TransferenciaOutput: DTO com metadados do processamento e saldos consolidados.

    Raises:
        ValorInvalidoError: Se o valor for inferior ao limite mínimo permitido.
        ContasIdenticasError: Se origem e destino forem idênticos.
        ContaNaoEncontradaError: Se uma das contas informadas não existir.
        SaldoInsuficienteError: Se o saldo for insuficiente para cobrir o débito.
        TransferenciaError: Falhas de persistência ou concorrência relativas ao banco.
    """
    if not isinstance(dados.valor, Decimal):
        raise TypeError(f"O valor deve ser decimal.Decimal, recebido: {type(dados.valor)}")

    if dados.valor < VALOR_MINIMO_TRANSFERENCIA:
        raise ValorInvalidoError(
            f"O valor de transferência deve ser maior ou igual a {VALOR_MINIMO_TRANSFERENCIA}",
            context={"valor_fornecido": str(dados.valor)},
        )

    if dados.conta_origem_id == dados.conta_destino_id:
        raise ContasIdenticasError(
            "Transferência não permitida entre a mesma conta bancária",
            context={"conta_id": dados.conta_origem_id},
        )

    # Identificação determinística da ordem dos locks para prevenção de deadlocks distribuídos
    ids_ordenados: list[int] = sorted([dados.conta_origem_id, dados.conta_destino_id])

    try:
        with session.begin_nested() if session.is_active else session.begin():
            # Executa aquisição de lock pessimista (SELECT ... FOR UPDATE) em ordem determinística
            stmt = (
                select(Conta)
                .where(Conta.id.in_(ids_ordenados))
                .with_for_update()
            )
            contas_bloqueadas = {c.id: c for c in session.scalars(stmt).all()}

            conta_origem = contas_bloqueadas.get(dados.conta_origem_id)
            if conta_origem is None:
                raise ContaNaoEncontradaError(
                    f"Conta de origem ID {dados.conta_origem_id} não encontrada.",
                    context={"conta_origem_id": dados.conta_origem_id},
                )

            conta_destino = contas_bloqueadas.get(dados.conta_destino_id)
            if conta_destino is None:
                raise ContaNaoEncontradaError(
                    f"Conta de destino ID {dados.conta_destino_id} não encontrada.",
                    context={"conta_destino_id": dados.conta_destino_id},
                )

            # Regra de negócio legada: IF v_saldo_origem < p_valor THEN RAISE EXCEPTION
            if conta_origem.saldo < dados.valor:
                audit_falha = {
                    "evento": "FALHA_SALDO_INSUFICIENTE",
                    "conta_origem_id": dados.conta_origem_id,
                    "saldo_atual": str(conta_origem.saldo),
                    "valor_tentativa": str(dados.valor),
                }
                logger.warning("Falha na validação de saldo: %s", audit_falha)
                raise SaldoInsuficienteError(
                    "Saldo insuficiente",
                    context=audit_falha,
                )

            # Efetuação dos débitos e créditos com precisão exata
            conta_origem.saldo -= dados.valor
            conta_destino.saldo += dados.valor

            # Registro da auditoria transacional
            nova_transacao = Transacao(
                conta_origem_id=dados.conta_origem_id,
                conta_destino_id=dados.conta_destino_id,
                valor=dados.valor,
                tipo=TIPO_TRANSACAO_TRANSFERENCIA,
                criado_em=datetime.now(timezone.utc),
            )
            session.add(nova_transacao)
            session.flush()

            audit_sucesso = {
                "evento": "TRANSFERENCIA_SUCESSO",
                "transacao_id": nova_transacao.id,
                "conta_origem_id": dados.conta_origem_id,
                "conta_destino_id": dados.conta_destino_id,
                "valor": str(dados.valor),
                "timestamp": nova_transacao.criado_em.isoformat(),
            }
            logger.info("Transferência finalizada com sucesso: %s", audit_sucesso)

            return TransferenciaOutput(
                transacao_id=nova_transacao.id,
                conta_origem_id=dados.conta_origem_id,
                conta_destino_id=dados.conta_destino_id,
                valor=dados.valor,
                saldo_origem_remanescente=conta_origem.saldo,
                saldo_destino_atualizado=conta_destino.saldo,
                data_hora=nova_transacao.criado_em,
            )

    except (TransferenciaError, TypeError):
        raise
    except (DBAPIError, SQLAlchemyError) as db_exc:
        logger.error(
            "Erro de banco de dados durante a execução da transferência: %s",
            str(db_exc),
            exc_info=True,
        )
        raise TransferenciaError(
            "Falha operacional interna durante processamento transacional",
            context={"database_error": str(db_exc)},
        ) from db_exc