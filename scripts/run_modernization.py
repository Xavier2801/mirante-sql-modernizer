"""
Script de Execução em Lote (Batch Modernizer com Langfuse e Métricas de Custo).
Processa os Anexos B, C, D, E e F persistindo os códigos modernizados, relatórios
e registrando consumo de tokens e custos financeiros no Langfuse.
"""
import sys
from pathlib import Path

# Garante que a raiz do projeto esteja no PYTHONPATH
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import os
import json
import time
from dotenv import load_dotenv
from langfuse import Langfuse

from src.graph.workflow import modernization_graph
from src.repository.history_repository import HistoryRepository

load_dotenv()

OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

history_repo = HistoryRepository()

# Configuração do cliente de observabilidade Langfuse
pk = os.getenv("LANGFUSE_PUBLIC_KEY")
sk = os.getenv("LANGFUSE_SECRET_KEY")
host = os.getenv("LANGFUSE_HOST", "http://localhost:3000")
langfuse_client = Langfuse(public_key=pk, secret_key=sk, host=host) if (pk and sk) else None

# Tabela de precificação do Gemini (por token em USD)
PRICE_INPUT_PER_TOKEN = 0.00000125   # $1.25 / 1M tokens
PRICE_OUTPUT_PER_TOKEN = 0.00000500  # $5.00 / 1M tokens

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


def invoke_with_retry(graph, state, retries=3, delay=5):
    """Executa o grafo tratando eventuais oscilações ou sobrecarga da API (503)."""
    for attempt in range(1, retries + 1):
        try:
            return graph.invoke(state)
        except Exception as e:
            if "503" in str(e) or "UNAVAILABLE" in str(e):
                if attempt < retries:
                    print(f"      [!] API sobrecarregada (503). Aguardando {delay}s antes da tentativa {attempt + 1}/{retries}...")
                    time.sleep(delay)
                    continue
            raise e


def run_batch():
    summary_report = []
    print("[*] Iniciando modernização em lote com rastreamento no Langfuse...\n")

    for name, sql in ANEXOS.items():
        print(f"-> Processando {name}...")
        initial_state = {"source_code": sql.strip(), "schema_context": None}

        trace = None
        generation = None
        if langfuse_client:
            trace = langfuse_client.trace(
                name=f"modernize_{name}",
                metadata={"procedure": name, "target": "Python 3.14"}
            )
            generation = trace.generation(
                name="langgraph_modernization_generation",
                model="gemini-1.5-pro",
                input=sql.strip()
            )

        try:
            result_state = invoke_with_retry(modernization_graph, initial_state)

            generated_code = result_state.get("generated_code", "")
            report = result_state.get("report", {})
            metadata = result_state.get("metadata", {})

            # Extração de tokens reais ou estimativa sintética aproximada
            input_tokens = metadata.get("prompt_tokens") or max(len(sql.strip()) // 4, 150)
            output_tokens = metadata.get("completion_tokens") or max(len(generated_code) // 4, 1200)

            # Cálculo explícito do custo
            input_cost = input_tokens * PRICE_INPUT_PER_TOKEN
            output_cost = output_tokens * PRICE_OUTPUT_PER_TOKEN
            total_cost = input_cost + output_cost

            if generation:
                generation.end(
                    output=generated_code,
                    usage={
                        "input": input_tokens,
                        "output": output_tokens,
                        "total": input_tokens + output_tokens,
                        "unit": "TOKENS",
                        "input_cost": input_cost,
                        "output_cost": output_cost,
                        "total_cost": total_cost,
                    }
                )

            status_exec = result_state.get("status", "falha")
            proc_name = metadata.get("procedure_name") or name

            # 1. Salva o código Python gerado
            py_file = OUTPUT_DIR / f"{name}.py"
            with open(py_file, "w", encoding="utf-8") as f:
                f.write(generated_code)

            # 2. Salva o relatório analítico JSON
            json_file = OUTPUT_DIR / f"{name}_report.json"
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)

            # 3. Salva no banco relacional para auditoria
            try:
                history_repo.save_execution(
                    source_code=sql.strip(),
                    generated_code=generated_code,
                    report=report,
                    status=status_exec,
                )
            except Exception:
                pass

            risk_flags = report.get("risk_flags", [])
            syntax_valid = report.get("validation", {}).get("is_valid_syntax", False)

            summary_report.append({
                "Anexo": name,
                "Status": status_exec,
                "Rotina": proc_name,
                "Sintaxe AST": "Válida" if syntax_valid else "Inválida",
                "Alertas / Riscos": ", ".join(risk_flags) if risk_flags else "Nenhum risco crítico"
            })

            print(f"   [+] Concluído: {status_exec.upper()} | Tokens: {input_tokens + output_tokens} | Custo: ${total_cost:.5f}")

            # Pequeno intervalo para não estourar rate limit da API
            time.sleep(2)

        except Exception as e:
            if generation:
                generation.end(level="ERROR", status_message=str(e))
            print(f"   [!] Erro no processamento de {name}: {e}")

    if langfuse_client:
        print("\n[*] Enviando dados de telemetria ao Langfuse...")
        langfuse_client.flush()
        time.sleep(3)

    summary_md_path = OUTPUT_DIR / "SUMMARY_AUDIT.md"
    with open(summary_md_path, "w", encoding="utf-8") as f:
        f.write("# Relatório Consolidado de Modernização PL/pgSQL -> Python 3.14\n\n")
        f.write("| Anexo | Rotina | Status | Validação AST | Riscos Arquiteturais Mapeados |\n")
        f.write("| :--- | :--- | :--- | :--- | :--- |\n")
        for row in summary_report:
            f.write(f"| {row['Anexo']} | {row['Rotina']} | {row['Status']} | {row['Sintaxe AST']} | {row['Alertas / Riscos']} |\n")

    print(f"\n[OK] Lote concluído com sucesso! Relatório gerado em: {summary_md_path}")


if __name__ == "__main__":
    run_batch()