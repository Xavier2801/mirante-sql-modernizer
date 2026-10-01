"""
Módulo de Engenharia de Prompts para o Pipeline de Modernização PL/pgSQL -> Python 3.14.
Define diretrizes corporativas, contextualização enriquecida e templates de auto-healing.
"""
from typing import Dict, Any, Optional

SYSTEM_PROMPT = (
    "Você é um Engenheiro de Software Staff especialista em arquiteturas distribuídas e modernização de bases legadas críticas.\n"
    "Sua responsabilidade é converter rotinas procedurais PL/pgSQL legadas em módulos Python 3.14 modernos, robustos, seguros e prontos para produção em microsserviços.\n\n"
    "DIRETRIZES DE ARQUITETURA E QUALIDADE:\n"
    "1. TIPAGEM ESTÁTICA E PYTHON 3.14:\n"
    "   - Aplique type hints estritos em todos os argumentos e retornos funcionais.\n"
    "   - Utilize dataclass(frozen=True) ou Pydantic BaseModel para encapsular múltiplos parâmetros OUT, diagnósticos e DTOs de resposta.\n"
    "   - Utilize typing.Optional, typing.List e tipagens modernas de Python 3.14.\n\n"
    "2. PRECISÃO FINANCEIRA:\n"
    "   - Para quaisquer colunas ou cálculos envolvendo valores monetários, taxas ou saldo (ex: NUMERIC), utilize estritamente decimal.Decimal. O uso de tipos primitivos de ponto flutuante (float) é estritamente proibido.\n\n"
    "3. CONCORRÊNCIA E ISOLAMENTO TRANSACIONAL:\n"
    "   - Cláusulas FOR UPDATE devem ser mapeadas utilizando locks pessimistas no SQLAlchemy (ex: .with_for_update()) e envoltas num gerenciador de contexto atômico explícito (with session.begin():).\n"
    "   - Garanta que rollbacks e tratamento de exceções mantenham a consistência da base de dados.\n\n"
    "4. TRADUÇÃO DE CURSORES E MITIGAÇÃO N+1:\n"
    "   - Se a procedure de origem empregar cursores iterativos (CURSOR FOR ... LOOP), NUNCA gere loops que executem consultas unitárias repetitivas contra o banco de dados.\n"
    "   - Reescreva a solução utilizando processamento em lote (bulk fetching / chunks) ou consultas set-based diretas, documentando a decisão na docstring.\n\n"
    "5. PROCEDIMENTOS SET-RETURNING E CTES RECURSIVAS:\n"
    "   - Queries analíticas complexas e CTEs recursivas (WITH RECURSIVE) devem ser preservadas como consultas SQL gerenciadas via SQLAlchemy (text(...) parametrizado) ou transpostas para geradores (Iterable/Generator) com controle de paginação.\n\n"
    "6. HIERARQUIA DE ERROS E AUDITORIA:\n"
    "   - Converta instruções RAISE EXCEPTION em classes de exceção personalizadas em Python, derivadas de Exception.\n"
    "   - Mantenha chamadas a logs de auditoria em estruturas JSON nativas (dicionários).\n\n"
    "FORMATO DA SAÍDA:\n"
    "- Retorne EXCLUSIVAMENTE código Python 3.14 válido e executável.\n"
    "- Inclua todos os imports necessários (from decimal import Decimal, from dataclasses import dataclass, from sqlalchemy ..., etc.).\n"
    "- NÃO inclua introduções, explicações soltas ou comentários fora dos blocos de código/docstrings.\n"
)


def build_modernization_prompt(
        source_code: str,
        metadata: Dict[str, Any],
        schema_context: Optional[str] = None
) -> str:
    """Constrói a mensagem enriquecida combinando código fonte, metadados e schema."""
    if schema_context and schema_context.strip():
        schema_block = f"### CONTEXTO DE ESQUEMA DO BANCO (ANEXO A):\n```sql\n{schema_context.strip()}\n```\n"
    else:
        schema_block = "### CONTEXTO DE ESQUEMA DO BANCO:\nNenhum esquema adicional fornecido. Infira a estrutura a partir do código SQL legado.\n"

    params_formatted = []
    for param in metadata.get("parameters", []):
        params_formatted.append(f"- Nome: `{param.get('name')}`, Modo: `{param.get('mode')}`, Tipo SQL: `{param.get('type')}`")
    params_str = "\n".join(params_formatted) if params_formatted else "- Nenhum parâmetro declarado."

    risks = metadata.get("risk_flags", [])
    if risks:
        risks_formatted = "\n".join([f"- ALERTA CRÍTICO: {r}" for r in risks])
    else:
        risks_formatted = "- Nenhuma flag de risco operacional ou de concorrência detectada."

    tables = ", ".join(metadata.get("tables_referenced", [])) or "Nenhuma tabela explícita identificada."
    proc_name = metadata.get("procedure_name", "procedimento")
    ret_type = metadata.get("return_type", "VOID")

    lines = [
        f"### TAREFA DE MODERNIZAÇÃO:",
        f"Procedimento Legado a Modernizar: `{proc_name}`",
        "",
        schema_block,
        "### METADADOS EXTRAÍDOS PELO PARSER:",
        f"- Nome: {proc_name}",
        f"- Tipo de Retorno Esperado: {ret_type}",
        f"- Tabelas Acessadas: {tables}",
        "- Parâmetros Identificados:",
        params_str,
        "",
        "### DIRETIVAS DE RISCO (NÓ SEMÂNTICO):",
        risks_formatted,
        "",
        "### CÓDIGO FONTE PL/PGSQL LEGADO:",
        "```sql",
        source_code.strip(),
        "```",
        "",
        "INSTRUÇÃO:",
        "Gere o módulo Python 3.14 equivalente, implementando tipagem estática rigorosa, suporte a SQLAlchemy Core/Session, manipulação decimal financeira e tratamento das flags de risco acima identificadas."
    ]

    return "\n".join(lines).strip()


def build_healing_prompt(
        broken_code: str,
        syntax_error: str,
        metadata: Dict[str, Any]
) -> str:
    """Gera o prompt para o LLM corrigir erros de sintaxe identificados pelo validador."""
    proc_name = metadata.get("procedure_name", "procedimento")
    lines = [
        "### REQUISITO DE CORREÇÃO SINTÁTICA (AUTO-HEALING):",
        f"O código Python 3.14 gerado anteriormente para o procedimento `{proc_name}` falhou na validação estática de AST.",
        "",
        "### DIAGNÓSTICO DO ERRO DE SINTAXE:",
        "```text",
        syntax_error.strip(),
        "```",
        "",
        "### CÓDIGO GERADO COM ERRO:",
        "```python",
        broken_code.strip(),
        "```",
        "",
        "INSTRUÇÃO DE CORREÇÃO:",
        "Corrija o erro sintático imediatamente, preservando a lógica de negócio, os imports necessários e a tipagem estática.",
        "Retorne APENAS o código Python 3.14 corrigido e válido para o interpretador."
    ]
    return "\n".join(lines).strip()