"""
Módulo responsável pelo Parsing estruturado e geração de AST via sqlglot.
"""
import re
from typing import Dict, Any, List
import sqlglot
from sqlglot import exp


class SQLParser:
    """Parser determinístico para PL/pgSQL suportado por sqlglot."""

    def __init__(self, dialect: str = "postgres"):
        self.dialect = dialect

    def parse_procedure(self, sql_code: str) -> Dict[str, Any]:
        """
        Recebe o código SQL bruto da procedure/função e gera uma
        representação estruturada de AST e blocos de comandos.
        """
        clean_sql = sql_code.strip()

        # 1. Extração do corpo entre os delimitadores AS $$ ... $$
        body_match = re.search(r"AS\s*\$\$(.*?)\$\$;?", clean_sql, re.DOTALL | re.IGNORECASE)
        body_content = body_match.group(1).strip() if body_match else clean_sql

        # 2. Decomposição de blocos DECLARE e BEGIN/EXCEPTION
        declare_block = ""
        execution_block = body_content

        declare_match = re.search(r"DECLARE\s*(.*?)\s*BEGIN", body_content, re.DOTALL | re.IGNORECASE)
        if declare_match:
            declare_block = declare_match.group(1).strip()
            execution_match = re.search(r"BEGIN\s*(.*?)\s*END;?", body_content, re.DOTALL | re.IGNORECASE)
            if execution_match:
                execution_block = execution_match.group(1).strip()

        # 3. Extração e parsing de instruções SQL embutidas (SELECT, UPDATE, INSERT)
        ast_queries = []
        tables_found = set()

        # Expressões SQL contidas no corpo
        statements = [stmt.strip() for stmt in execution_block.split(";") if stmt.strip()]
        for stmt in statements:
            # Filtra apenas instruções DML que o sqlglot valida nativamente
            if any(stmt.upper().startswith(prefix) for prefix in ("SELECT", "UPDATE", "INSERT", "DELETE", "WITH")):
                try:
                    parsed_expr = sqlglot.parse_one(stmt, read=self.dialect)
                    ast_queries.append({
                        "raw_statement": stmt,
                        "ast_type": parsed_expr.key,
                        "ast_json": parsed_expr.dump()
                    })
                    # Mapeia todas as tabelas referenciadas nas consultas
                    for table in parsed_expr.find_all(exp.Table):
                        tables_found.add(table.name.lower())
                except Exception:
                    # Em caso de cláusulas procedurais misturadas (ex: INTO v_total), mantém o registo léxico
                    ast_queries.append({
                        "raw_statement": stmt,
                        "ast_type": "procedural_dml",
                        "ast_json": None
                    })

        return {
            "raw_code": clean_sql,
            "declare_block": declare_block,
            "execution_block": execution_block,
            "parsed_dml_count": len(ast_queries),
            "ast_queries": ast_queries,
            "tables_referenced": sorted(list(tables_found))
        }