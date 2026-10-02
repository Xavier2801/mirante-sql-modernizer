from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
import logging
from typing import Protocol
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


# =====================================================================
# HIERARQUIA DE ERROS DE DOMÍNIO E INFRAESTRUTURA
# =====================================================================

class ArvoreDependentesError(Exception):
    """Exceção base para operações de hierarquia de dependentes."""
    pass


class ClienteNaoEncontradoError(ArvoreDependentesError):
    """Lançada quando o cliente raiz informado não existe na base."""
    def __init__(self, cliente_id: int) -> None:
        super().__init__(f"Cliente raiz com identificador {cliente_id} não encontrado.")
        self.cliente_id = cliente_id


class SaldoClienteResolucaoError(ArvoreDependentesError):
    """Lançada quando ocorre falha na resolução de saldo via dependência externa."""
    pass


# =====================================================================
# DATA TRANSFER OBJECTS (DTO)
# =====================================================================

@dataclass(frozen=True, slots=True)
class DependenteHierarquiaDTO:
    """
    Representação imutável de um nó na árvore hierárquica de dependentes.
    
    Campos:
        id: Identificador único do cliente/dependente.
        nivel: Grau de profundidade na árvore hierárquica (1 = raiz).
        saldo_total: Saldo consolidado com precisão monetária estrita.
    """
    id: int
    nivel: int
    saldo_total: Decimal


# =====================================================================
# CONTRATO DE INJEÇÃO DE DEPENDÊNCIA (NÓ SEMÂNTICO: fn_saldo_cliente)
# =====================================================================

class SaldoClienteResolver(Protocol):
    """
    Protocolo para desacoplamento da função externa `fn_saldo_cliente`.
    
    Permite alternar entre resolução delegada no banco (batch set-based),
    chamada a microsserviço de saldos ou implementações em memória para testes.
    """
    def resolver_saldos(
        self, session: Session, cliente_ids: Sequence[int]
    ) -> Mapping[int, Decimal]:
        """
        Calcula ou recupera o saldo para um lote de IDs de clientes de forma set-based,
        eliminando problemas de N+1 queries.
        """
        ...


class DatabaseSaldoClienteResolver:
    """
    Implementação padrão que executa a função de banco legada 'fn_saldo_cliente'
    em lote através de unnest/set-based SQL, prevenindo round-trips N+1.
    """
    def resolver_saldos(
        self, session: Session, cliente_ids: Sequence[int]
    ) -> Mapping[int, Decimal]:
        if not cliente_ids:
            return {}

        stmt = text("""
            SELECT 
                item.id,
                CAST(fn_saldo_cliente(item.id) AS NUMERIC(15, 2)) AS saldo
            FROM unnest(:cliente_ids) AS item(id);
        """)

        try:
            result = session.execute(stmt, {"cliente_ids": list(cliente_ids)})
            saldos: dict[int, Decimal] = {}
            for row in result:
                saldos[row.id] = Decimal(str(row.saldo)) if row.saldo is not None else Decimal("0.00")
            return saldos
        except SQLAlchemyError as exc:
            logger.error(
                "Falha ao resolver saldos em lote no banco",
                extra={"audit_log": {"ids": list(cliente_ids), "error": str(exc)}}
            )
            raise SaldoClienteResolucaoError(
                "Erro de banco de dados ao executar fn_saldo_cliente em lote."
            ) from exc


# =====================================================================
# SERVIÇO PRINCIPAL: HIERARQUIA DE DEPENDENTES
# =====================================================================

class ArvoreDependentesService:
    """
    Serviço moderno para traversal de hierarquia e consolidação de saldos.
    
    Decisões Arquiteturais:
    - Delegação de CTE Recursiva: A resolução de hierarquia permanece delegada ao
      motor PostgreSQL para otimização de performance e baixa sobrecarga de rede.
    - Mitigação de N+1: A obtenção de dados hierárquicos e saldos pode ocorrer
      em fluxo unificado ou particionado via SaldoClienteResolver em lote.
    - Isolamento de Concorrência: A leitura é encapsulada em transação atômica.
    """

    def __init__(self, saldo_resolver: SaldoClienteResolver | None = None) -> None:
        self._saldo_resolver = saldo_resolver or DatabaseSaldoClienteResolver()

    def buscar_arvore_dependentes(
        self, session: Session, cliente_id: int
    ) -> list[DependenteHierarquiaDTO]:
        """
        Executa a busca da árvore hierárquica recursiva a partir do cliente raiz.
        
        Args:
            session: Sessão ativa do SQLAlchemy gerenciada externamente ou por contexto.
            cliente_id: Identificador do cliente raiz da busca.
            
        Returns:
            Lista de nós DTO contendo id, nível e saldo com precisão Decimal.
            
        Raises:
            ClienteNaoEncontradoError: Caso a consulta recursiva não retorne linhas.
            ArvoreDependentesError: Falhas de infraestrutura ou consistência relacional.
        """
        if cliente_id <= 0:
            raise ValueError("O identificador do cliente deve ser um inteiro positivo.")

        audit_payload = {
            "operation": "fn_arvore_dependentes",
            "p_cliente_id": cliente_id,
            "status": "INICIADO"
        }
        logger.info("Iniciando busca da árvore de dependentes", extra={"audit_log": audit_payload})

        # Consulta com CTE Recursiva nativa delegada ao banco
        query_cte = text("""
            WITH RECURSIVE hierarquia AS (
                SELECT c.id, 1 AS nivel
                FROM clientes c
                WHERE c.id = :cliente_id
                UNION ALL
                SELECT cl.id, h.nivel + 1 AS nivel
                FROM clientes cl
                JOIN hierarquia h ON cl.id = h.id + 1
                WHERE h.nivel < 5
            )
            SELECT id, nivel
            FROM hierarquia;
        """)

        try:
            # Garante escopo transacional seguro para leitura de consistência
            with session.begin_nested():
                result = session.execute(query_cte, {"cliente_id": cliente_id}).fetchall()

            if not result:
                audit_payload["status"] = "NAO_ENCONTRADO"
                logger.warning(
                    "Cliente raiz inexistente ou sem registros associados",
                    extra={"audit_log": audit_payload}
                )
                raise ClienteNaoEncontradoError(cliente_id=cliente_id)

            nos_hierarquia = [(row.id, row.nivel) for row in result]
            ids_unicos = list({row_id for row_id, _ in nos_hierarquia})

            # Resolução desacoplada e em lote para mitigar N+1 da função fn_saldo_cliente
            saldos_map = self._saldo_resolver.resolver_saldos(session, ids_unicos)

            dto_list: list[DependenteHierarquiaDTO] = []
            for row_id, nivel in nos_hierarquia:
                saldo_item = saldos_map.get(row_id, Decimal("0.00"))
                dto_list.append(
                    DependenteHierarquiaDTO(
                        id=row_id,
                        nivel=nivel,
                        saldo_total=saldo_item
                    )
                )

            audit_payload.update({
                "status": "SUCESSO",
                "total_registros": len(dto_list)
            })
            logger.info("Hierarquia processada com sucesso", extra={"audit_log": audit_payload})
            return dto_list

        except SQLAlchemyError as exc:
            audit_payload.update({"status": "ERRO_BANCO", "mensagem": str(exc)})
            logger.error("Falha relacional durante execução da CTE", extra={"audit_log": audit_payload})
            raise ArvoreDependentesError("Falha na consulta analítica hierárquica.") from exc
        except Exception:
            raise


# =====================================================================
# VARIANTE OTIMIZADA SET-BASED PURA (EXECUÇÃO DIRETA DE BANCO)
# =====================================================================

def executar_arvore_dependentes_nativa(
    session: Session, cliente_id: int
) -> list[DependenteHierarquiaDTO]:
    """
    Execução analítica set-based direta preservando a semântica integral legada em SQL nativo.
    Ideal para cenários onde a função `fn_saldo_cliente` reside obrigatoriamente no banco
    e não deve sofrer interceptação pela camada de microsserviço.
    """
    if cliente_id <= 0:
        raise ValueError("O identificador do cliente deve ser um inteiro positivo.")

    query = text("""
        WITH RECURSIVE hierarquia AS (
            SELECT c.id, 1 AS nivel
            FROM clientes c
            WHERE c.id = :cliente_id
            UNION ALL
            SELECT cl.id, h.nivel + 1 AS nivel
            FROM clientes cl
            JOIN hierarquia h ON cl.id = h.id + 1
            WHERE h.nivel < 5
        )
        SELECT 
            h.id, 
            h.nivel, 
            CAST(fn_saldo_cliente(h.id) AS NUMERIC(15, 2)) AS saldo_total
        FROM hierarquia h;
    """)

    try:
        with session.begin_nested():
            result = session.execute(query, {"cliente_id": cliente_id}).fetchall()

        if not result:
            raise ClienteNaoEncontradoError(cliente_id=cliente_id)

        return [
            DependenteHierarquiaDTO(
                id=row.id,
                nivel=row.nivel,
                saldo_total=Decimal(str(row.saldo_total)) if row.saldo_total is not None else Decimal("0.00")
            )
            for row in result
        ]
    except SQLAlchemyError as exc:
        logger.error(
            "Erro de execução SQL nativa em fn_arvore_dependentes",
            extra={"audit_log": {"p_cliente_id": cliente_id, "error": str(exc)}}
        )
        raise ArvoreDependentesError("Erro na consulta nativa de dependentes.") from exc