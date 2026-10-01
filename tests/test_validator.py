from src.validator.syntax_validator import SyntaxValidator

validator = SyntaxValidator()
dummy_metadata = {
    "parameters": [{"name": "p_valor", "mode": "IN", "type": "NUMERIC(18,2)"}]
}

# 1. Teste com código válido
codigo_valido = """
from decimal import Decimal

def transferir(origem: int, destino: int, valor: Decimal) -> bool:
    if valor <= 0:
        raise ValueError("Valor inválido")
    return True
"""
res_valido = validator.validate(codigo_valido, dummy_metadata)
print("Código Válido:", res_valido["is_valid_syntax"], "| AST:", res_valido["ast_parsed"], "| Alertas:", res_valido["warnings"])

# 2. Teste com código quebrado (SyntaxError)
codigo_invalido = """
def transferir(origem: int,
    # Parênteses não fechados intencionalmente
"""
res_invalido = validator.validate(codigo_invalido, dummy_metadata)
print("Código Inválido:", res_invalido["is_valid_syntax"], "| Erro Sintático:", res_invalido["syntax_error"])