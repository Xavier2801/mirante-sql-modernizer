"""
Módulo de Análise Semântica para PL/pgSQL.
Mapeia assinaturas, tipos, variáveis e catalogação de riscos de migração.
"""
import re
from typing import Dict, Any, List
from src.domain.state import ProcedureMetadata


class SemanticAnalyzer:
    """Analisador de semântica e padrões de risco procedural."""

    def analyze(self, sql_code: str, parse_result: Dict[str, Any]) -> ProcedureMetadata:
        """
        Inspeciona o código e os blocos parsed para produzir metadados
        estruturados e avisos de risco de migração.
        """
        clean_sql = sql_code.strip()
        metadata: ProcedureMetadata = {
            "procedure_name": self._extract_name(clean_sql),
            "language": "plpgsql",
            "parameters": self._extract_parameters(clean_sql),
            "return_type": self._extract_return_type(clean_sql),
            "variables": self._extract_variables(parse_result.get("declare_block", "")),
            "risk_flags": self._catalog_risks(clean_sql),
            "tables_referenced": parse_result.get("tables_referenced", [])
        }
        return metadata

    def _extract_name(self, sql: str) -> str:
        match = re.search(r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:PROCEDURE|FUNCTION)\s+([a-zA-Z0-9_]+)", sql, re.IGNORECASE)
        return match.group(1) if match else "unknown_procedure"

    def _extract_parameters(self, sql: str) -> List[Dict[str, Any]]:
        params = []
        param_block_match = re.search(
            r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:PROCEDURE|FUNCTION)\s+[a-zA-Z0-9_]+\s*\((.*?)\)\s*(?:RETURNS|LANGUAGE)",
            sql,
            re.DOTALL | re.IGNORECASE
        )
        if not param_block_match:
            param_block_match = re.search(
                r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:PROCEDURE|FUNCTION)\s+[a-zA-Z0-9_]+\s*\((.*?)\)",
                sql,
                re.DOTALL | re.IGNORECASE
            )
            if not param_block_match:
                return params

        raw_block = param_block_match.group(1).strip()
        if not raw_block:
            return params

        # Split resiliente a tipos com escala e precisão como NUMERIC(18,2)
        raw_params = []
        current = []
        depth = 0
        for char in raw_block:
            if char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
            if char == ',' and depth == 0:
                raw_params.append("".join(current).strip())
                current = []
            else:
                current.append(char)
        if current:
            raw_params.append("".join(current).strip())

        for raw in raw_params:
            tokens = raw.strip().split()
            if not tokens:
                continue

            mode = "IN"
            if tokens[0].upper() in ("IN", "OUT", "INOUT"):
                mode = tokens[0].upper()
                tokens = tokens[1:]

            if len(tokens) >= 2:
                name = tokens[0]
                param_type = " ".join(tokens[1:])
                params.append({"name": name, "mode": mode, "type": param_type})
            elif len(tokens) == 1:
                params.append({"name": tokens[0], "mode": mode, "type": "UNKNOWN"})

        return params

    def _extract_return_type(self, sql: str) -> str:
        match = re.search(r"RETURNS\s+(TABLE\s*\(.*?\)|[a-zA-Z0-9_(),\s]+?)\s+LANGUAGE", sql, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return "VOID"

    def _extract_variables(self, declare_block: str) -> List[Dict[str, str]]:
        variables = []
        if not declare_block:
            return variables

        for line in declare_block.split(";"):
            line = line.strip()
            if not line or line.upper().startswith("CURSOR"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                var_name = parts[0]
                var_type = " ".join(parts[1:]).split(":=")[0].strip()
                variables.append({"name": var_name, "type": var_type})
        return variables

    def _catalog_risks(self, sql: str) -> List[str]:
        risks = []
        upper_sql = sql.upper()

        if "CURSOR FOR" in upper_sql or "OPEN " in upper_sql:
            risks.append("CURSOR_DETECTED: Potencial gargalo de I/O (N+1 queries). Requer batching ou consulta em lote.")

        if "FOR UPDATE" in upper_sql:
            risks.append("CONCURRENCY_LOCK_FOR_UPDATE: Requer isolamento transacional estrito e lock pessimista no SQLAlchemy.")

        if "WITH RECURSIVE" in upper_sql:
            risks.append("RECURSIVE_CTE: Lógica de encadeamento analítico. Recomenda-se execução nativa delegada ao banco.")

        if "RAISE EXCEPTION" in upper_sql:
            risks.append("RAISE_EXCEPTION: Validações de negócio devem ser traduzidas para exceções personalizadas em Python.")

        if "GET DIAGNOSTICS" in upper_sql:
            risks.append("GET_DIAGNOSTICS_ROW_COUNT: Retorno de quantidade de registos alterados em comandos de UPDATE/INSERT em massa.")

        if "FN_SALDO_CLIENTE" in upper_sql:
            risks.append("EXTERNAL_FUNCTION_DEPENDENCY: Dependência da função aninhada 'fn_saldo_cliente'. Exige injeção de dependência modular.")

        return risks