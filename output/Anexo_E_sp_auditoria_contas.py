from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from sqlalchemy import BigInteger, ForeignKey, Numeric, String, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Constantes de Domínio
STATUS_CONTA_ATIVA: Final[str] = "ATIVA"


class Base(DeclarativeBase):
    pass


class Conta(Base):
    __tablename__ = "contas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    saldo: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)

    transacoes_origem: Mapped[list["Transacao"]] = relationship(
        "Transacao", back_populates="conta_origem"
    )


class Transacao(Base):
    __tablename__ = "transacoes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conta_origem_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("contas.id"), nullable=False, index=True
    )

    conta_origem: Mapped[Conta] = relationship("Conta", back_populates="transacoes_origem")


@dataclass(slots=True, frozen=True)
class ItemAuditoriaContaDTO:
    conta_id: int
    saldo: Decimal
    total_transacoes: int


async def sp_auditoria_contas(session: AsyncSession) -> Sequence[ItemAuditoriaContaDTO]:
    """
    Executa auditoria em lote para contas com status 'ATIVA'.

    Elimina o gargalo N+1 da procedure original via agregação direta
    no banco de dados com LEFT OUTER JOIN e GROUP BY.
    """
    stmt = (
        select(
            Conta.id.label("conta_id"),
            Conta.saldo.label("saldo"),
            func.count(Transacao.id).label("total_transacoes"),
        )
        .outerjoin(Transacao, Transacao.conta_origem_id == Conta.id)
        .where(Conta.status == STATUS_CONTA_ATIVA)
        .group_by(Conta.id, Conta.saldo)
    )

    result = await session.execute(stmt)

    return [
        ItemAuditoriaContaDTO(
            conta_id=row.conta_id,
            saldo=row.saldo,
            total_transacoes=row.total_transacoes,
        )
        for row in result.all()
    ]