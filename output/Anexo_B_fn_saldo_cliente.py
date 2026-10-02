"""Módulo de modernização da rotina de cálculo de saldo consolidado de clientes.

Tradução e modernização da função legada PL/pgSQL `fn_saldo_cliente` para Python 3.14,
utilizando SQLAlchemy 2.0+, tipagem estática rigorosa, aritmética com Decimal e
injeção de dependência via Protocol/Service.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import logging
from typing import Protocol, runtime_checkable

from sqlalchemy import Column, Numeric, String, BigInteger, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# -----------------------------------------------------------------------------
# Configuração de Logging Estruturado
# -----------------------------------------------------------------------------
logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Hierarquia de Exceções
# -----------------------------------------------------------------------------
class SaldoClienteError(Exception):
    """Exceção base para operações de saldo de cliente."""


class ClienteInvalidoError(SaldoClienteError):
    """Lançada quando os parâmetros de cliente informados são inválidos."""


class PersistenciaSaldoError(SaldoClienteError):
    """Lançada quando ocorre uma falha na consulta à base de dados."""


# -----------------------------------------------------------------------------
# Modelos Declarativos (SQLAlchemy)
# -----------------------------------------------------------------------------
class Base(DeclarativeBase):
    """Base declarativa do SQLAlchemy."""


class ContaModel(Base):
    """Mapeamento da tabela legada `contas`."""

    __tablename__ = "contas"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    cliente_id = Column(BigInteger, nullable=False, index=True)
    saldo = Column(Numeric(precision=15, scale=2), nullable=False, default=Decimal("0.00"))
    status = Column(String(50), nullable=False)


# -----------------------------------------------------------------------------
# Data Transfer Objects (DTO)
# -----------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class SaldoClienteDTO:
    """Encapsula o resultado consolidado do cálculo de saldo."""

    cliente_id: int
    saldo_total: Decimal


# -----------------------------------------------------------------------------
# Interfaces e Protocolos (Injeção de Dependência)
# -----------------------------------------------------------------------------
@runtime_checkable
class SaldoClienteServiceProtocol(Protocol):
    """Contrato abstrato para injeção de dependência da rotina fn_saldo_cliente."""

    def calcular_saldo(self, cliente_id: int) -> SaldoClienteDTO:
        """Calcula o saldo consolidado de contas ativas do cliente."""
        ...


# -----------------------------------------------------------------------------
# Implementação de Serviço
# -----------------------------------------------------------------------------
class SaldoClienteService:
    """Serviço responsável pela apuração de saldos consolidados de clientes."""

    STATUS_ATIVA: str = "ATIVA"
    VALOR_PADRAO: Decimal = Decimal("0.00")

    def __init__(self, session_factory: sessionmaker[Session] | Engine) -> None:
        """Inicializa o serviço com uma fábrica de sessões ou um Engine SQLAlchemy.

        :param session_factory: sessionmaker configurado ou Engine do SQLAlchemy.
        """
        if isinstance(session_factory, Engine):
            self._session_factory = sessionmaker(bind=session_factory, expire_on_commit=False)
        else:
            self._session_factory = session_factory

    def calcular_saldo(self, cliente_id: int) -> SaldoClienteDTO:
        """Calcula a soma de saldo de todas as contas ativas de um cliente.

        Equivalente funcional de:
            SELECT COALESCE(SUM(saldo), 0.00)
            FROM contas
            WHERE cliente_id = p_cliente_id AND status = 'ATIVA';

        :param cliente_id: Identificador único do cliente (BIGINT).
        :return: Objeto imutável SaldoClienteDTO contendo o saldo em Decimal.
        :raises ClienteInvalidoError: Se o identificador do cliente for menor ou igual a zero.
        :raises PersistenciaSaldoError: Em caso de falha de conexão ou execução da query.
        """
        if not isinstance(cliente_id, int) or cliente_id <= 0:
            audit_payload = {
                "evento": "validacao_parametro_falha",
                "funcao": "fn_saldo_cliente",
                "cliente_id": cliente_id,
                "motivo": "cliente_id deve ser um inteiro positivo",
            }
            logger.warning("Falha de validação", extra={"audit": audit_payload})
            raise ClienteInvalidoError(f"cliente_id inválido: {cliente_id}")

        stmt = (
            select(func.coalesce(func.sum(ContaModel.saldo), self.VALOR_PADRAO))
            .where(
                ContaModel.cliente_id == cliente_id,
                ContaModel.status == self.STATUS_ATIVA,
            )
        )

        try:
            with self._session_factory() as session:
                resultado = session.execute(stmt).scalar_one_or_none()
                saldo_calculado: Decimal = (
                    Decimal(str(resultado)) if resultado is not None else self.VALOR_PADRAO
                )

                audit_payload = {
                    "evento": "consulta_saldo_sucesso",
                    "funcao": "fn_saldo_cliente",
                    "cliente_id": cliente_id,
                    "saldo_apurado": str(saldo_calculado),
                }
                logger.info("Consulta de saldo realizada com sucesso", extra={"audit": audit_payload})

                return SaldoClienteDTO(
                    cliente_id=cliente_id,
                    saldo_total=saldo_calculado,
                )

        except SQLAlchemyError as exc:
            audit_payload = {
                "evento": "erro_persistencia_saldo",
                "funcao": "fn_saldo_cliente",
                "cliente_id": cliente_id,
                "erro": str(exc),
            }
            logger.error("Erro ao consultar saldo no banco de dados", extra={"audit": audit_payload})
            raise PersistenciaSaldoError(
                f"Erro operacional ao calcular saldo para o cliente {cliente_id}"
            ) from exc


# -----------------------------------------------------------------------------
# Ponto de Entrada Funcional (Compatibilidade Direta com a Assinatura SQL)
# -----------------------------------------------------------------------------
def fn_saldo_cliente(
    p_cliente_id: int,
    service: SaldoClienteServiceProtocol,
) -> Decimal:
    """Ponto de entrada funcional de modernização da procedure legada fn_saldo_cliente.

    Permite a injeção modular da implementação do serviço de apuração de saldos,
    garantindo compatibilidade com chamadas aninhadas e arquiteturas desacopladas.

    :param p_cliente_id: ID do cliente.
    :param service: Instância que implementa SaldoClienteServiceProtocol.
    :return: Saldo consolidado como Decimal(15, 2).
    """
    dto: SaldoClienteDTO = service.calcular_saldo(cliente_id=p_cliente_id)
    return dto.saldo_total