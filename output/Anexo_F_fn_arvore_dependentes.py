from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Column,
    Integer,
    MetaData,
    Numeric,
    Table,
    func,
    literal,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession

metadata = MetaData()

clientes = Table(
    "clientes",
    metadata,
    Column("id", BigInteger, primary_key=True),
)


@dataclass(frozen=True, slots=True)
class DependenteHierarquiaDTO:
    id: int
    nivel: int
    saldo_total: Decimal


async def fn_arvore_dependentes(
    session: AsyncSession,
    p_cliente_id: int,
) -> Sequence[DependenteHierarquiaDTO]:
    """Recupera a árvore hierárquica de dependentes e seus respectivos saldos via CTE recursiva.

    Equivalente à rotina PL/pgSQL fn_arvore_dependentes. Mantém execução
    delegada inteiramente ao SGBD em round-trip único para eliminar problemas de N+1.
    """
    # Âncora da CTE recursiva
    hierarquia_cte = (
        select(
            clientes.c.id.label("id"),
            literal(1, type_=Integer).label("nivel"),
        )
        .where(clientes.c.id == p_cliente_id)
        .cte(name="hierarquia", recursive=True)
    )

    # Alias para self-join recursivo
    cl = clientes.alias("cl")

    # Passo recursivo com critério de parada (nivel < 5)
    hierarquia_cte = hierarquia_cte.union_all(
        select(
            cl.c.id.label("id"),
            (hierarquia_cte.c.nivel + 1).label("nivel"),
        )
        .select_from(
            cl.join(
                hierarquia_cte,
                cl.c.id == hierarquia_cte.c.id + 1,
            )
        )
        .where(hierarquia_cte.c.nivel < 5)
    )

    # Consulta final delegando o cálculo monetário à função do banco em lote único
    stmt = select(
        hierarquia_cte.c.id,
        hierarquia_cte.c.nivel,
        func.fn_saldo_cliente(hierarquia_cte.c.id)
        .cast(Numeric(15, 2))
        .label("saldo_total"),
    )

    result = await session.execute(stmt)

    return [
        DependenteHierarquiaDTO(
            id=row.id,
            nivel=row.nivel,
            saldo_total=row.saldo_total,
        )
        for row in result.all()
    ]