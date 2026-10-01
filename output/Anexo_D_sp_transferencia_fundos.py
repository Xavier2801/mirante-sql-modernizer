from decimal import Decimal
from enum import StrEnum
from typing import Final

from sqlalchemy import BigInteger, ForeignKey, Numeric, String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


# ==============================================================================
# Modelos Declarativos (SQLAlchemy 2.0+)
# ==============================================================================


class Base(DeclarativeBase):
    pass


class TipoTransacao(StrEnum):
    TRANSFERENCIA = "TRANSFERENCIA"


class Conta(Base):
    __tablename__ = "contas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    saldo: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)


class Transacao(Base):
    __tablename__ = "transacoes"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    conta_origem_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("contas.id"), nullable=False
    )
    conta_destino_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("contas.id"), nullable=False
    )
    valor: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    tipo: Mapped[str] = mapped_column(String(50), nullable=False)


# ==============================================================================
# Exceções de Domínio de Negócio
# ==============================================================================


class TransferenciaError(Exception):
    """Exceção base para erros ocorridos durante transferências."""


class ContaNaoEncontradaError(TransferenciaError):
    """Lançada quando a conta de origem ou destino não existe."""


class SaldoInsuficienteError(TransferenciaError):
    """Mapeamento direto do RAISE EXCEPTION 'Saldo insuficiente' do PL/pgSQL."""


class ValorTransferenciaInvalidoError(TransferenciaError):
    """Lançada quando o montante da transferência é menor ou igual a zero."""


# ==============================================================================
# Rotina de Negócio Migrada
# ==============================================================================

ZERO_MONETARIO: Final[Decimal] = Decimal("0.00")


async def sp_transferencia_fundos(
    session: AsyncSession,
    *,
    p_conta_origem: int,
    p_conta_destino: int,
    p_valor: Decimal,
) -> None:
    """Migração estrita e assíncrona da procedure `sp_transferencia_fundos`.

    Aplica lock pessimista determinístico para mitigar concorrência e evitar
    deadlocks entre transferências mútuas simultâneas.

    :param session: Sessão assíncrona do SQLAlchemy (com transação ativa).
    :param p_conta_origem: Identificador da conta debitada.
    :param p_conta_destino: Identificador da conta creditada.
    :param p_valor: Valor decimal com precisão monetária (15, 2).
    :raises ValorTransferenciaInvalidoError: Se o montante for <= 0.
    :raises TransferenciaError: Se conta origem e destino forem idênticas.
    :raises ContaNaoEncontradaError: Se uma das contas não existir.
    :raises SaldoInsuficienteError: Se a conta de origem não possuir fundos suficientes.
    """
    if p_valor <= ZERO_MONETARIO:
        raise ValorTransferenciaInvalidoError(
            "O valor da transferência deve ser estritamente positivo."
        )

    if p_conta_origem == p_conta_destino:
        raise TransferenciaError(
            "A conta de origem não pode ser idêntica à conta de destino."
        )

    # Ordenação dos IDs para prevenir Deadlocks ao aplicar FOR UPDATE concorrente
    ids_ordenados = sorted((p_conta_origem, p_conta_destino))

    # Concorrência: SELECT ... FOR UPDATE com isolamento estrito
    stmt = (
        select(Conta)
        .where(Conta.id.in_(ids_ordenados))
        .with_for_update()
        .order_by(Conta.id)
    )

    result = await session.execute(stmt)
    contas_map = {conta.id: conta for conta in result.scalars().all()}

    conta_origem = contas_map.get(p_conta_origem)
    if conta_origem is None:
        raise ContaNaoEncontradaError(
            f"Conta de origem ID {p_conta_origem} não encontrada."
        )

    conta_destino = contas_map.get(p_conta_destino)
    if conta_destino is None:
        raise ContaNaoEncontradaError(
            f"Conta de destino ID {p_conta_destino} não encontrada."
        )

    # Validação de Saldo (equivalente ao IF v_saldo_origem < p_valor)
    if conta_origem.saldo < p_valor:
        raise SaldoInsuficienteError("Saldo insuficiente")

    # Débito e Crédito rastreados pela Identity Map do SQLAlchemy
    conta_origem.saldo -= p_valor
    conta_destino.saldo += p_valor

    # Registro de auditoria da transação
    nova_transacao = Transacao(
        conta_origem_id=p_conta_origem,
        conta_destino_id=p_conta_destino,
        valor=p_valor,
        tipo=TipoTransacao.TRANSFERENCIA,
    )
    session.add(nova_transacao)

    await session.flush()