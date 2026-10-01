"""
Suite de Testes Automatizados com Pytest.
Valida o comportamento dos nós determinísticos e do Grafo LangGraph sobre os Anexos B a F.
"""
import pytest
from src.parser.sql_parser import SQLParser
from src.analyzer.semantic_analyzer import SemanticAnalyzer
from src.validator.syntax_validator import SyntaxValidator
from src.graph.workflow import modernization_graph

# Fixtures com o SQL exato dos Anexos do Desafio

SQL_ANEXO_B = """
              CREATE OR REPLACE FUNCTION fn_saldo_cliente (p_cliente_id BIGINT)
RETURNS NUMERIC(18,2)
LANGUAGE plpgsql
AS $$
DECLARE
              v_total NUMERIC(18,2);
              BEGIN
              SELECT COALESCE(SUM(saldo), 0)
              INTO v_total
              FROM contas
              WHERE cliente_id = p_cliente_id
                AND status = 'ATIVA';
              RETURN v_total;
              END;
$$; \
              """

SQL_ANEXO_C = """
              CREATE OR REPLACE PROCEDURE sp_atualizar_status_contas_inativas (
    IN p_dias INT,
    OUT p_afetadas INT
)
LANGUAGE plpgsql
AS $$
              BEGIN
    IF p_dias IS NULL OR p_dias <= 0 THEN
        RAISE EXCEPTION 'Parametro p_dias deve ser positivo, recebido: %', p_dias;
              END IF;

              UPDATE contas c
              SET status = 'INATIVA'
              WHERE c.status = 'ATIVA'
                AND NOT EXISTS (
                  SELECT 1 FROM transacoes t
                  WHERE (t.conta_origem_id = c.id OR t.conta_destino_id = c.id)
                    AND t.data_transacao >= NOW() - (p_dias || ' days')::INTERVAL
              );

              GET DIAGNOSTICS p_afetadas = ROW_COUNT;
              END;
$$; \
              """

SQL_ANEXO_D = """
              CREATE OR REPLACE PROCEDURE sp_transferir_entre_contas (
    IN p_conta_origem BIGINT,
    IN p_conta_destino BIGINT,
    IN p_valor NUMERIC(18,2)
)
LANGUAGE plpgsql
AS $$
              BEGIN
    IF p_valor IS NULL OR p_valor <= 0 THEN
        RAISE EXCEPTION 'Valor invalido para transferencia: %', p_valor;
              END IF;

              SELECT saldo, status FROM contas WHERE id = p_conta_origem FOR UPDATE;
              SELECT status FROM contas WHERE id = p_conta_destino FOR UPDATE;

              UPDATE contas SET saldo = saldo - p_valor WHERE id = p_conta_origem;
              UPDATE contas SET saldo = saldo + p_valor WHERE id = p_conta_destino;
              END;
$$; \
              """

SQL_ANEXO_E = """
              CREATE OR REPLACE PROCEDURE sp_processar_lote_taxas (
    IN p_data_referencia DATE
)
LANGUAGE plpgsql
AS $$
DECLARE
              cur_transacoes CURSOR FOR
              SELECT id, conta_origem_id, tipo, valor FROM transacoes;
              BEGIN
              OPEN cur_transacoes;
              -- processamento com cursor
              CLOSE cur_transacoes;
              END;
$$; \
              """

SQL_ANEXO_F = """
              CREATE OR REPLACE FUNCTION sp_relatorio_mensal_cliente(
    p_cliente_id BIGINT,
    p_data_inicio DATE,
    p_data_fim DATE
)
RETURNS TABLE (
    mes_referencia DATE,
    total_creditos NUMERIC(18,2)
)
LANGUAGE plpgsql
AS $$
DECLARE
              v_saldo_atual NUMERIC(18,2);
              BEGIN
    v_saldo_atual := fn_saldo_cliente(p_cliente_id);
              RETURN QUERY
                  WITH RECURSIVE meses AS (
        SELECT DATE_TRUNC('month', p_data_inicio)::DATE AS mes
    )
              SELECT m.mes, 0::NUMERIC(18,2) FROM meses m;
              END;
$$; \
              """


@pytest.fixture
def parser():
    return SQLParser()


@pytest.fixture
def analyzer():
    return SemanticAnalyzer()


@pytest.fixture
def validator():
    return SyntaxValidator()


# -------------------------------------------------------------
# Testes Unitários dos Nós 1 e 2 (Parsing e Semântica)
# -------------------------------------------------------------

def test_anexo_b_saldo_cliente(parser, analyzer):
    """Valida extração simples de função escalar (Anexo B)."""
    parsed = parser.parse_procedure(SQL_ANEXO_B)
    metadata = analyzer.analyze(SQL_ANEXO_B, parsed)

    assert metadata["procedure_name"] == "fn_saldo_cliente"
    assert metadata["return_type"] == "NUMERIC(18,2)"
    assert len(metadata["parameters"]) == 1
    assert metadata["parameters"][0]["name"] == "p_cliente_id"
    assert metadata["parameters"][0]["type"] == "BIGINT"
    assert "contas" in metadata["tables_referenced"]


def test_anexo_c_parametros_in_out(parser, analyzer):
    """Valida mapeamento de parâmetros IN/OUT e GET DIAGNOSTICS (Anexo C)."""
    parsed = parser.parse_procedure(SQL_ANEXO_C)
    metadata = analyzer.analyze(SQL_ANEXO_C, parsed)

    assert metadata["procedure_name"] == "sp_atualizar_status_contas_inativas"
    assert len(metadata["parameters"]) == 2
    assert metadata["parameters"][0]["mode"] == "IN"
    assert metadata["parameters"][1]["mode"] == "OUT"
    assert any("GET_DIAGNOSTICS" in flag for flag in metadata["risk_flags"])
    assert any("RAISE_EXCEPTION" in flag for flag in metadata["risk_flags"])


def test_anexo_d_lock_concorrente(parser, analyzer):
    """Valida detecção de lock pessimista FOR UPDATE (Anexo D)."""
    parsed = parser.parse_procedure(SQL_ANEXO_D)
    metadata = analyzer.analyze(SQL_ANEXO_D, parsed)

    assert metadata["procedure_name"] == "sp_transferir_entre_contas"
    assert any("CONCURRENCY_LOCK_FOR_UPDATE" in flag for flag in metadata["risk_flags"])


def test_anexo_e_deteccao_cursor(parser, analyzer):
    """Valida detecção de cursor iterativo com risco N+1 (Anexo E)."""
    parsed = parser.parse_procedure(SQL_ANEXO_E)
    metadata = analyzer.analyze(SQL_ANEXO_E, parsed)

    assert metadata["procedure_name"] == "sp_processar_lote_taxas"
    assert any("CURSOR_DETECTED" in flag for flag in metadata["risk_flags"])


def test_anexo_f_cte_recursiva_e_dependencia(parser, analyzer):
    """Valida flags de CTE recursiva e dependência externa (Anexo F)."""
    parsed = parser.parse_procedure(SQL_ANEXO_F)
    metadata = analyzer.analyze(SQL_ANEXO_F, parsed)

    assert metadata["procedure_name"] == "sp_relatorio_mensal_cliente"
    assert any("RECURSIVE_CTE" in flag for flag in metadata["risk_flags"])
    assert any("EXTERNAL_FUNCTION_DEPENDENCY" in flag for flag in metadata["risk_flags"])


# -------------------------------------------------------------
# Testes do Validador Sintático (Nó 4)
# -------------------------------------------------------------

def test_syntax_validator_rejeita_codigo_quebrado(validator):
    """Garante que código com falha sintática é marcado como inválido."""
    codigo_quebrado = "def funcao_incompleta(:"
    res = validator.validate(codigo_quebrado, metadata={"parameters": []})
    assert res["is_valid_syntax"] is False
    assert res["ast_parsed"] is False
    assert res["syntax_error"] is not None


def test_syntax_validator_alerta_falha_decimal(validator):
    """Garante emissão de alerta se NUMERIC for usado sem Decimal."""
    codigo_sem_decimal = "def soma(valor: float) -> float: return valor"
    metadata_financeiro = {"parameters": [{"name": "p_valor", "type": "NUMERIC(18,2)"}]}
    res = validator.validate(codigo_sem_decimal, metadata_financeiro)
    assert res["is_valid_syntax"] is True
    assert any("ALERTA FINANCEIRO" in w for w in res["warnings"])


# -------------------------------------------------------------
# Teste de Integração: Ciclo de Vida do Grafo LangGraph
# -------------------------------------------------------------

from unittest.mock import patch


# -------------------------------------------------------------
# Teste de Integração: Ciclo de Vida do Grafo LangGraph
# -------------------------------------------------------------

def test_grafo_execucao_completa_anexo_b():
    """Valida a transição do estado pelos 4 nós do LangGraph de forma determinística e rápida."""
    initial_state = {
        "source_code": SQL_ANEXO_B,
        "schema_context": None
    }

    # Código Python 3.14 simulado que o Nó 3 geraria, permitindo validar o Nó 4 e o Grafo
    mock_python_code = '''"""
Módulo gerado para modernização de fn_saldo_cliente.
"""
from decimal import Decimal
from sqlalchemy import text
from sqlalchemy.orm import Session

def fn_saldo_cliente(session: Session, p_cliente_id: int) -> Decimal:
    """Calcula o saldo total de contas ativas do cliente."""
    stmt = text("""
        SELECT COALESCE(SUM(saldo), 0)
        FROM contas
        WHERE cliente_id = :cliente_id
          AND status = 'ATIVA'
    """)
    result = session.execute(stmt, {"cliente_id": p_cliente_id}).scalar()
    return Decimal(str(result or 0))
'''

    # O patch intercepta a chamada ao LLM apenas durante este teste, eliminando chamadas HTTP externas
    with patch("src.generator.llm_service.LLMService.generate", return_value=mock_python_code):
        final_state = modernization_graph.invoke(initial_state)

    # Asserções estruturais do resultado
    assert "ast_representation" in final_state
    assert "metadata" in final_state
    assert "generated_code" in final_state
    assert "validation" in final_state
    assert "report" in final_state
    assert final_state["status"] in ("sucesso", "parcial")
    assert final_state["validation"]["is_valid_syntax"] is True