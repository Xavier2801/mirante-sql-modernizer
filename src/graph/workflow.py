"""
Módulo de orquestração do LangGraph.
Define os nós da pipeline, o fluxo de transições condicionais e compila o grafo executável.
"""
from typing import Dict, Any
from langgraph.graph import StateGraph, START, END

from src.domain.state import ModernizationState
from src.parser.sql_parser import SQLParser
from src.analyzer.semantic_analyzer import SemanticAnalyzer
from src.generator.llm_service import LLMService
from src.generator.prompts import (
    build_modernization_prompt,
    build_healing_prompt,
    SYSTEM_PROMPT,
)
from src.validator.syntax_validator import SyntaxValidator


# Inicialização dos serviços que operam nos nós
sql_parser = SQLParser()
semantic_analyzer = SemanticAnalyzer()
llm_service = LLMService()
syntax_validator = SyntaxValidator()

MAX_RETRIES = 2


# ---------------------------------------------------------
# Definição dos Nós do Grafo
# ---------------------------------------------------------

def parse_node(state: ModernizationState) -> Dict[str, Any]:
    """Nó 1: Parsing do SQL bruto e extração de AST/DML."""
    source_code = state.get("source_code", "")
    ast_result = sql_parser.parse_procedure(source_code)
    return {
        "ast_representation": ast_result,
        "retry_count": state.get("retry_count", 0),
        "error_history": state.get("error_history", []),
    }


def analyze_node(state: ModernizationState) -> Dict[str, Any]:
    """Nó 2: Análise semântica, identificação de tipos e catalogação de riscos."""
    source_code = state.get("source_code", "")
    ast_result = state.get("ast_representation", {})
    metadata = semantic_analyzer.analyze(source_code, ast_result)
    return {"metadata": metadata}


def generate_node(state: ModernizationState) -> Dict[str, Any]:
    """Nó 3: Geração de código Python 3.14 via LLM com prompts especializados e auto-healing."""
    source_code = state.get("source_code", "")
    metadata = state.get("metadata", {})
    schema_context = state.get("schema_context")
    retry_count = state.get("retry_count", 0)
    validation = state.get("validation", {})
    error_history = list(state.get("error_history", []))

    # Se for uma tentativa de correção disparada pelo validador
    if retry_count > 0 and not validation.get("is_valid_syntax", True):
        syntax_err = validation.get("syntax_error", "Erro de sintaxe desconhecido")
        error_history.append(syntax_err)
        prompt_content = build_healing_prompt(
            broken_code=state.get("generated_code", ""),
            syntax_error=syntax_err,
            metadata=metadata,
        )
        final_prompt = f"{SYSTEM_PROMPT}\n\n{prompt_content}"
        rationale = f"Tentativa de auto-healing #{retry_count} para corrigir falhas de sintaxe AST."
    else:
        # Prompt inicial com metadados estruturados
        prompt_content = build_modernization_prompt(
            source_code=source_code,
            metadata=metadata,
            schema_context=schema_context,
        )
        final_prompt = f"{SYSTEM_PROMPT}\n\n{prompt_content}"
        rationale = "Tradução idiomática em Python 3.14 orientada por metadados e SQLAlchemy 2.0."

    generated_code = llm_service.generate(prompt=final_prompt)
    telemetry_data = getattr(llm_service, "last_telemetry", {}).copy()

    return {
        "generated_code": generated_code,
        "generation_rationale": rationale,
        "telemetry": telemetry_data,
        "retry_count": retry_count + 1,
        "error_history": error_history,
    }


def validate_node(state: ModernizationState) -> Dict[str, Any]:
    """Nó 4: Validação sintática (ast.parse) e montagem do relatório executivo."""
    generated_code = state.get("generated_code")
    metadata = state.get("metadata", {})
    telemetry = state.get("telemetry", {})

    val_result = syntax_validator.validate(generated_code, metadata)

    status = "sucesso" if val_result["is_valid_syntax"] else "falha"
    if val_result["is_valid_syntax"] and val_result["warnings"]:
        status = "parcial"

    report = {
        "procedure_name": metadata.get("procedure_name"),
        "risk_flags": metadata.get("risk_flags", []),
        "parameters_analyzed": len(metadata.get("parameters", [])),
        "tables_referenced": metadata.get("tables_referenced", []),
        "telemetry": telemetry,
        "validation": val_result,
        "retries_applied": state.get("retry_count", 1) - 1,
        "status": status,
    }

    return {
        "validation": val_result,
        "report": report,
        "status": status,
    }


def check_validation_route(state: ModernizationState) -> str:
    """Decisão condicional: se a sintaxe falhar e não estourou o limite de retries, tenta auto-healing."""
    validation = state.get("validation", {})
    retry_count = state.get("retry_count", 0)

    # Se a sintaxe for inválida e ainda houver tentativas permitidas
    if not validation.get("is_valid_syntax", False) and retry_count <= MAX_RETRIES:
        return "generation"

    return END


# ---------------------------------------------------------
# Construção e Conexão do StateGraph
# ---------------------------------------------------------

def create_modernization_graph():
    """Monta e compila o grafo LangGraph com transição condicional de auto-healing."""
    workflow = StateGraph(ModernizationState)

    workflow.add_node("parsing", parse_node)
    workflow.add_node("analysis", analyze_node)
    workflow.add_node("generation", generate_node)
    workflow.add_node("validation", validate_node)

    workflow.add_edge(START, "parsing")
    workflow.add_edge("parsing", "analysis")
    workflow.add_edge("analysis", "generation")
    workflow.add_edge("generation", "validation")

    # Aresta condicional para auto-healing
    workflow.add_conditional_edges(
        "validation",
        check_validation_route,
        {
            "generation": "generation",
            END: END,
        },
    )

    return workflow.compile()


modernization_graph = create_modernization_graph()