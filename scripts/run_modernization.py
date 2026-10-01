"""
Script de Execução em Lote (Batch Modernizer).
Processa os Anexos B, C, D, E e F, persistindo os códigos modernizados
e os relatórios analíticos na pasta output/.
"""
import os
import json
import httpx
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
API_URL = os.getenv("API_URL", "http://localhost:8000/modernize")

# SQLs dos Anexos de Teste da Avaliação
ANEXOS = {
    "Anexo_B_fn_saldo_cliente": """
                                CREATE OR REPLACE FUNCTION fn_saldo_cliente(p_cliente_id BIGINT)
RETURNS NUMERIC(15, 2)
LANGUAGE plpgsql
AS $$
DECLARE
                                v_saldo_total NUMERIC(15, 2) := 0.00;
                                BEGIN
                                SELECT COALESCE(SUM(saldo), 0.00)
                                INTO v_saldo_total
                                FROM contas
                                WHERE cliente_id = p_cliente_id
                                  AND status = 'ATIVA';

                                RETURN v_saldo_total;
                                END;
$$;
                                """,
    "Anexo_C_sp_processa_fechamento": """
                                      CREATE OR REPLACE PROCEDURE sp_processa_fechamento(
    IN p_conta_id BIGINT,
    OUT p_total_processado NUMERIC(15, 2),
    OUT p_qtd_transacoes INTEGER
)
LANGUAGE plpgsql
AS $$
DECLARE
                                      v_rows INTEGER;
                                      BEGIN
                                      UPDATE contas
                                      SET status = 'EM_PROCESSAMENTO'
                                      WHERE id = p_conta_id;

                                      GET DIAGNOSTICS v_rows = ROW_COUNT;

                                      IF v_rows = 0 THEN
        RAISE EXCEPTION 'Conta inexistente para fechamento';
                                      END IF;

                                      SELECT COALESCE(SUM(valor), 0.00), COUNT(*)
                                      INTO p_total_processado, p_qtd_transacoes
                                      FROM transacoes
                                      WHERE conta_origem_id = p_conta_id;
                                      END;
$$;
                                      """,
    "Anexo_D_sp_transferencia_fundos": """
                                       CREATE OR REPLACE PROCEDURE sp_transferencia_fundos(
    IN p_conta_origem BIGINT,
    IN p_conta_destino BIGINT,
    IN p_valor NUMERIC(15, 2)
)
LANGUAGE plpgsql
AS $$
DECLARE
                                       v_saldo_origem NUMERIC(15, 2);
                                       BEGIN
    -- Concorrência: Lock pessimista
                                       SELECT saldo INTO v_saldo_origem
                                       FROM contas
                                       WHERE id = p_conta_origem
                                           FOR UPDATE;

                                       IF v_saldo_origem < p_valor THEN
        RAISE EXCEPTION 'Saldo insuficiente';
                                       END IF;

                                       UPDATE contas SET saldo = saldo - p_valor WHERE id = p_conta_origem;
                                       UPDATE contas SET saldo = saldo + p_valor WHERE id = p_conta_destino;

                                       INSERT INTO transacoes (conta_origem_id, conta_destino_id, valor, tipo)
                                       VALUES (p_conta_origem, p_conta_destino, p_valor, 'TRANSFERENCIA');
                                       END;
$$;
                                       """,
    "Anexo_E_sp_auditoria_contas": """
                                   CREATE OR REPLACE PROCEDURE sp_auditoria_contas()
LANGUAGE plpgsql
AS $$
DECLARE
                                   cur_contas CURSOR FOR SELECT id, saldo FROM contas WHERE status = 'ATIVA';
                                   v_id BIGINT;
    v_saldo NUMERIC(15, 2);
                                   BEGIN
                                   OPEN cur_contas;
                                   LOOP
                                   FETCH cur_contas INTO v_id, v_saldo;
        EXIT WHEN NOT FOUND;

        -- Risco clássico de N+1
        PERFORM COUNT(*) FROM transacoes WHERE conta_origem_id = v_id;
                                   END LOOP;
                                   CLOSE cur_contas;
                                   END;
$$;
                                   """,
    "Anexo_F_fn_arvore_dependentes": """
                                     CREATE OR REPLACE FUNCTION fn_arvore_dependentes(p_cliente_id BIGINT)
RETURNS TABLE(id BIGINT, nivel INT, saldo_total NUMERIC(15, 2))
LANGUAGE plpgsql
AS $$
                                     BEGIN
                                     RETURN QUERY
                                         WITH RECURSIVE hierarquia AS (
        SELECT c.id, 1 as nivel
        FROM clientes c
        WHERE c.id = p_cliente_id
        UNION ALL
        SELECT cl.id, h.nivel + 1
        FROM clientes cl
        JOIN hierarquia h ON cl.id = h.id + 1
        WHERE h.nivel < 5
    )
                                     SELECT h.id, h.nivel, fn_saldo_cliente(h.id)
                                     FROM hierarquia h;
                                     END;
$$;
                                     """
}


def run_batch():
    """Submete todos os anexos e exporta artefatos."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summary_report = []

    print(f"[*] Iniciando modernização em lote via API ({API_URL})...\n")

    for name, sql in ANEXOS.items():
        print(f"-> Processando {name}...")
        try:
            response = httpx.post(
                API_URL,
                json={"source_code": sql.strip(), "schema_context": None},
                timeout=120.0
            )

            if response.status_code != 200:
                print(f"   [!] Erro HTTP {response.status_code}: {response.text}")
                continue

            data = response.json()
            status_exec = data.get("status")
            proc_name = data.get("procedure_name") or name
            generated_code = data.get("generated_code", "")
            report = data.get("report", {})

            # 1. Salva o código Python gerado
            py_file = OUTPUT_DIR / f"{name}.py"
            with open(py_file, "w", encoding="utf-8") as f:
                f.write(generated_code)

            # 2. Salva o relatório JSON analítico
            json_file = OUTPUT_DIR / f"{name}_report.json"
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)

            # 3. Consolidação para o sumário executivo
            risk_flags = report.get("analysis", {}).get("risk_flags", [])
            syntax_valid = report.get("validation", {}).get("is_valid_syntax", False)

            summary_report.append({
                "Anexo": name,
                "Status": status_exec,
                "Rotina": proc_name,
                "Sintaxe AST": "Válida" if syntax_valid else "Inválida",
                "Alertas / Riscos": ", ".join(risk_flags) if risk_flags else "Nenhum risco crítico"
            })

            print(f"   [+] Concluído: {status_exec.upper()} | Arquivos salvos em {OUTPUT_DIR.name}/")

        except Exception as e:
            print(f"   [!] Falha de conexão ou execução: {str(e)}")

    # 4. Salva o sumário consolidado em Markdown
    summary_md_path = OUTPUT_DIR / "SUMMARY_AUDIT.md"
    with open(summary_md_path, "w", encoding="utf-8") as f:
        f.write("# Relatório Consolidado de Modernização PL/pgSQL -> Python 3.14\n\n")
        f.write("| Anexo | Rotina | Status | Validação AST | Riscos Arquiteturais Mapeados |\n")
        f.write("| :--- | :--- | :--- | :--- | :--- |\n")
        for row in summary_report:
            f.write(f"| {row['Anexo']} | {row['Rotina']} | {row['Status']} | {row['Sintaxe AST']} | {row['Alertas / Riscos']} |\n")

    print(f"\n[OK] Execução em lote finalizada. Relatório gerado em: {summary_md_path}")


if __name__ == "__main__":
    run_batch()