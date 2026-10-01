from src.parser.sql_parser import SQLParser
from src.analyzer.semantic_analyzer import SemanticAnalyzer

sql_test = """
           CREATE OR REPLACE PROCEDURE sp_transferir_entre_contas (
    IN p_conta_origem BIGINT,
    IN p_conta_destino BIGINT,
    IN p_valor NUMERIC(18,2)
)
LANGUAGE plpgsql
AS $$
           BEGIN
           SELECT saldo FROM contas WHERE id = p_conta_origem FOR UPDATE;
           UPDATE contas SET saldo = saldo - p_valor WHERE id = p_conta_origem;
           RAISE EXCEPTION 'Saldo insuficiente';
           END;
$$; \
           """

parser = SQLParser()
analyzer = SemanticAnalyzer()

parsed = parser.parse_procedure(sql_test)
metadata = analyzer.analyze(sql_test, parsed)

print("\n--- METADADOS EXTRAÍDOS ---")
print(f"Nome da Procedure: {metadata['procedure_name']}")
print(f"Parâmetros: {metadata['parameters']}")
print(f"Tabelas Detectadas: {metadata['tables_referenced']}")
print("\n--- FLAGS DE RISCO IDENTIFICADAS ---")
for flag in metadata["risk_flags"]:
    print(f"- {flag}")