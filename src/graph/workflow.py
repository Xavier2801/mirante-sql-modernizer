"""
Módulo de orquestração do LangGraph.
Define os nós da pipeline, o fluxo de transições e compila o grafo executável.
"""
from typing import Dict, Any
from langgraph.graph import StateGraph, START, END

from src.domain.state import ModernizationState
from src.parser.sql_parser import SQLParser
from src.analyzer.semantic_analyzer import SemanticAnalyzer
from src.generator.llm_service import LLMService
from src.validator.syntax_validator import SyntaxValidator


# Inicialização dos serviços que operam nos nós
sql_parser = SQLParser()
semantic_analyzer = SemanticAnalyzer()
llm_service = LLMService()
syntax_validator = SyntaxValidator()


# ---------------------------------------------------------
# Definição dos Nós do Grafo
# ---------------------------------------------------------

def parse_node(state: ModernizationState) -> Dict[str, Any]:
    """Nó 1: Parsing do SQL bruto e extração de AST/DML."""
    source_code = state.get("source_code", "")
    ast_result = sql_parser.parse_procedure(source_code)
    return {"ast_representation": ast_result}


def analyze_node(state: ModernizationState) -> Dict[str, Any]:
    """Nó 2: Análise semântica, identificação de tipos e catalogação de riscos."""
    source_code = state.get("source_code", "")
    ast_result = state.get("ast_representation", {})
    metadata = semantic_analyzer.analyze(source_code, ast_result)
    return {"metadata": metadata}


def generate_node(state: ModernizationState) -> Dict[str, Any]:
    """Nó 3: Geração de código Python 3.14 via LLM enriquecido com metadados."""
    source_code = state.get("source_code", "")
    metadata = state.get("metadata", {})
    schema_context = state.get("schema_context")

    generated_code = llm_service.generate(
        source_code=source_code,
        metadata=metadata,
        schema_context=schema_context
    )
    return {
        "generated_code": generated_code,
        "generation_rationale": "Tradução idiomática em Python 3.14 preservando regras transacionais e financeiras."
    }


def validate_node(state: ModernizationState) -> Dict[str, Any]:
    """Nó 4: Validação sintática (ast.parse) e montagem do relatório executivo."""
    generated_code = state.get("generated_code")
    metadata = state.get("metadata", {})

    val_result = syntax_validator.validate(generated_code, metadata)

    status = "sucesso" if val_result["is_valid_syntax"] else "falha"
    if val_result["is_valid_syntax"] and val_result["warnings"]:
        status = "parcial"

    report = {
        "procedure_name": metadata.get("procedure_name"),
        "risk_flags": metadata.get("risk_flags", []),
        "parameters_analyzed": len(metadata.get("parameters", [])),
        "tables_referenced": metadata.get("tables_referenced", []),
        "validation": val_result,
        "status": status
    }

    return {
        "validation": val_result,
        "report": report,
        "status": status
    }


# ---------------------------------------------------------
# Construção e Conexão do StateGraph
# ---------------------------------------------------------

def create_modernization_graph():
    """Monta e compila o grafo LangGraph com estado tipado."""
    workflow = StateGraph(ModernizationState)

    workflow.add_node("parsing", parse_node)
    workflow.add_node("analysis", analyze_node)
    workflow.add_node("generation", generate_node)
    workflow.add_node("validation", validate_node)

    workflow.add_edge(START, "parsing")
    workflow.add_edge("parsing", "analysis")
    workflow.add_edge("analysis", "generation")
    workflow.add_edge("generation", "validation")
    workflow.add_edge("validation", END)

    return workflow.compile()


# Objeto compilado exportado para uso nos testes e na API
modernization_graph = create_modernization_graph()