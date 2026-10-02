"""
Definição do contrato de dados e estado tipado para a pipeline de modernização LangGraph.
"""
from typing import TypedDict, Optional, List, Dict, Any


class ProcedureMetadata(TypedDict, total=False):
    """Metadados semânticos extraídos deterministicamente pelo Nó 2."""
    procedure_name: str
    language: str
    parameters: List[Dict[str, Any]]  # Nome, modo (IN/OUT), tipo
    return_type: Optional[str]
    variables: List[Dict[str, str]]
    risk_flags: List[str]             # CURSOR_DETECTED, FOR_UPDATE_LOCK, RECURSIVE_CTE, etc.
    tables_referenced: List[str]


class ValidationResult(TypedDict, total=False):
    """Resultado da análise sintática e checagens estáticas do Nó 4."""
    is_valid_syntax: bool
    ast_parsed: bool
    syntax_error: Optional[str]
    warnings: List[str]


class ModernizationState(TypedDict, total=False):
    """
    Estado global que transita pelos nós do Grafo LangGraph:
    1. Parsing -> 2. Semantic Analysis -> 3. Generation -> 4. Validation (com loop condicional)
    """
    # Entradas obrigatórias da requisição
    source_code: str
    schema_context: Optional[str]

    # Saídas intermediárias produzidas pelos nós determinísticos
    ast_representation: Dict[str, Any]
    metadata: ProcedureMetadata

    # Saída da geração LLM
    generated_code: Optional[str]
    generation_rationale: Optional[str]
    telemetry: Optional[Dict[str, Any]]

    # Controle de resiliência e auto-correção
    retry_count: int
    error_history: List[str]

    # Saída da etapa de validação
    validation: ValidationResult

    # Relatório final e desfecho para persistência
    report: Dict[str, Any]
    status: str  # 'sucesso' | 'falha' | 'parcial'