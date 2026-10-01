from decimal import Decimal
from typing import Final

from sqlalchemy import BigInteger, Numeric, String, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

STATUS_CONTA_ATIVA: Final[str] = "ATIVA"
VALOR_ZERO_PADRAO: Final[Decimal] = Decimal("0.00")


class Base(DeclarativeBase):
    pass


class Conta(Base):
    __tablename__ = "contas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    cliente_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    saldo: Mapped[Decimal] = mapped_column(Numeric(precision=15, scale=2), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)


async def fn_saldo_cliente_async(
    session: AsyncSession,
    p_cliente_id: int,
) -> Decimal:
    """Calcula de forma assíncrona o saldo consolidado de contas ativas do cliente.

    Equivalente à rotina PL/pgSQL fn_saldo_cliente(BIGINT).
    Garante agregação direta a nível de banco de dados (sem overhead N+1).
    """
    stmt = select(
        func.coalesce(
            func.sum(Conta.saldo),
            VALOR_ZERO_PADRAO,
        )
    ).where(
        Conta.cliente_id == p_cliente_id,
        Conta.status == STATUS_CONTA_ATIVA,
    )

    saldo_total = await session.scalar(stmt)
    return saldo_total if saldo_total is not None else VALOR_ZERO_PADRAO


def fn_saldo_cliente_sync(
    session: Session,
    p_cliente_id: int,
) -> Decimal:
    """Calcula de forma síncrona o saldo consolidado de contas ativas do cliente.

    Equivalente à rotina PL/pgSQL fn_saldo_cliente(BIGINT).
    Garante agregação direta a nível de banco de dados (sem overhead N+1).
    """
    stmt = select(
        func.coalesce(
            func.sum(Conta.saldo),
            VALOR_ZERO_PADRAO,
        )
    ).where(
        Conta.cliente_id == p_cliente_id,
        Conta.status == STATUS_CONTA_ATIVA,
    )

    saldo_total = session.scalar(stmt)
    return saldo_total if saldo_total is not None else VALOR_ZERO_PADRAO