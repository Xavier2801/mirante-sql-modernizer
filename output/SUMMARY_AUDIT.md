# Relatório Consolidado de Modernização PL/pgSQL -> Python 3.14

| Anexo | Rotina | Status | Validação AST | Riscos Arquiteturais Mapeados |
| :--- | :--- | :--- | :--- | :--- |
| Anexo_B_fn_saldo_cliente | fn_saldo_cliente | sucesso | Válida | EXTERNAL_FUNCTION_DEPENDENCY: Dependência da função aninhada 'fn_saldo_cliente'. Exige injeção de dependência modular. |
| Anexo_C_sp_processa_fechamento | sp_processa_fechamento | sucesso | Válida | RAISE_EXCEPTION: Validações de negócio devem ser traduzidas para exceções personalizadas em Python., GET_DIAGNOSTICS_ROW_COUNT: Retorno de quantidade de registos alterados em comandos de UPDATE/INSERT em massa. |
| Anexo_D_sp_transferencia_fundos | sp_transferencia_fundos | sucesso | Válida | CONCURRENCY_LOCK_FOR_UPDATE: Requer isolamento transacional estrito e lock pessimista no SQLAlchemy., RAISE_EXCEPTION: Validações de negócio devem ser traduzidas para exceções personalizadas em Python. |
| Anexo_E_sp_auditoria_contas | sp_auditoria_contas | sucesso | Válida | CURSOR_DETECTED: Potencial gargalo de I/O (N+1 queries). Requer batching ou consulta em lote. |
| Anexo_F_fn_arvore_dependentes | fn_arvore_dependentes | sucesso | Válida | RECURSIVE_CTE: Lógica de encadeamento analítico. Recomenda-se execução nativa delegada ao banco., EXTERNAL_FUNCTION_DEPENDENCY: Dependência da função aninhada 'fn_saldo_cliente'. Exige injeção de dependência modular. |
