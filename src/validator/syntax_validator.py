"""
Módulo de Validação Sintática e de Integridade Estrutural do Python gerado.
Executa ast.parse (Python 3.14) e valida conformidade de assinatura.
"""
import ast
from typing import Dict, Any, List, Optional
from src.domain.state import ValidationResult


class SyntaxValidator:
    """Validador determinístico para o código Python 3.14 produzido pela pipeline."""

    def validate(self, generated_code: Optional[str], metadata: Dict[str, Any]) -> ValidationResult:
        """
        Analisa o código Python gerado para garantir conformidade sintática
        e consistência em relação aos metadados de entrada.
        """
        if not generated_code or not generated_code.strip():
            return {
                "is_valid_syntax": False,
                "ast_parsed": False,
                "syntax_error": "Código gerado vazio ou nulo.",
                "warnings": ["Nenhum código foi produzido pelo gerador."]
            }

        warnings: List[str] = []
        clean_code = self._sanitize_markdown_blocks(generated_code)

        # 1. Validação Sintática via AST nativo do Python 3.14
        try:
            parsed_ast = ast.parse(clean_code)
            ast_parsed = True
            syntax_error = None
        except SyntaxError as e:
            return {
                "is_valid_syntax": False,
                "ast_parsed": False,
                "syntax_error": f"Erro de Sintaxe Python na linha {e.lineno}, coluna {e.offset}: {e.msg}",
                "warnings": warnings
            }

        # 2. Inspecção Estática da AST: Verificar definição de funções/classes
        defined_functions = [
            node.name for node in ast.walk(parsed_ast)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]

        if not defined_functions:
            warnings.append("Nenhuma função ou método executável foi encontrado no módulo gerado.")

        # 3. Verificação de Preservação de Tipos Críticos
        # Regra de negócio: códigos com NUMERIC devem importar Decimal
        has_numeric = any("NUMERIC" in p.get("type", "").upper() for p in metadata.get("parameters", []))
        if has_numeric and "Decimal" not in clean_code:
            warnings.append("ALERTA FINANCEIRO: Parâmetro monetário NUMERIC detectado, mas a classe 'Decimal' não foi importada.")

        return {
            "is_valid_syntax": True,
            "ast_parsed": ast_parsed,
            "syntax_error": None,
            "warnings": warnings
        }

    def _sanitize_markdown_blocks(self, code: str) -> str:
        """Remove blocos de formatação markdown caso o LLM os tenha incluído."""
        text = code.strip()
        if text.startswith("```python"):
            text = text[len("```python"):].strip()
        elif text.startswith("```"):
            text = text[len("```"):].strip()
        if text.endswith("```"):
            text = text[:-3].strip()
        return text