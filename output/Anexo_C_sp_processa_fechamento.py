from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated

from sqlalchemy import BigInteger, ForeignKey, Numeric, String, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Conta(Base):
    __tablename__ = "contas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)


class Transacao(Base):
    __tablename__ = "transacoes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conta_origem_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("contas.id"), nullable=False, index=True
    )
    valor: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)


class ContaInexistenteError(Exception):
    """Exceção levantada quando a conta informada não existe para fechamento."""


@dataclass(frozen=True, slots=True)
class ResultadoFechamento:
    total_processado: Decimal
    qtd_transacoes: int


async def processa_fechamento(
    session: AsyncSession,
    conta_id: int,
) -> ResultadoFechamento:
    """Executa a rotina de fechamento de conta e agregação de transações."""
    stmt_update = (
        update(Conta)
        .where(Conta.id == conta_id)
        .values(status="EM_PROCESSAMENTO")
    )
    result_update = await session.execute(stmt_update)

    if result_update.rowcount == 0:
        raise ContaInexistenteError("Conta inexistente para fechamento")

    stmt_aggregate = (
        select(
            func.coalesce(func.sum(Transacao.valor), Decimal("0.00")).label(
                "total_processado"
            ),
            func.count(Transacao.id).label("qtd_transacoes"),
        )
        .select_from(Transacao)
        .where(Transacao.conta_origem_id == conta_id)
    )

    agg_result = await session.execute(stmt_aggregate)
    row = agg_result.one()

    return ResultadoFechamento(
        total_processado=Decimal(row.total_processado),
        qtd_transacoes=int(row.qtd_transacoes),
    )