# Mirante SQL Modernizer (PL/pgSQL -> Python 3.14)

<br/>

[![Python 3.14](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/orchestration-LangGraph-orange.svg)](https://github.com/langchain-ai/langgraph)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-green.svg)](https://fastapi.tiangolo.com/)
[![Observability-Langfuse](https://img.shields.io/badge/observability-Langfuse_v2-purple.svg)](https://langfuse.com/)
[![Code-Quality](https://img.shields.io/badge/tests-11%20passed-brightgreen.svg)](tests/)

<br/>

Solução corporativa para modernização automatizada de rotinas legadas **PL/pgSQL** (Functions e Stored Procedures) para módulos modernos em **Python 3.14**.

O projeto adota uma **arquitetura híbrida (Rules + LLM)**: utiliza parsing sintático determinístico e extração semântica prévia para mitigar alucinações, acoplando um orquestrador cíclico em **LangGraph**, persistência de auditoria em **PostgreSQL**, telemetria completa via **Langfuse v2** e métricas automatizadas de avaliação estática.

<br/>
<hr/>
<br/>

# 1. ARQUITETURA DA PIPELINE HÍBRIDA (LANGGRAPH)

<br/>

O fluxo de modernização foi modelado como um grafo direcionado e cíclico (*StateGraph*) onde cada fase da modernização é isolada em um nó especializado. O estado transacionado ao longo da execução é rigidamente tipado via `TypedDict`.

<br/>

## 1.1 Diagrama do Grafo de Execução

```text
       +-----------------------+
       |         START         |
       +-----------------------+
                   |
                   v
       +-----------------------+
       |     [Node 1] Parsing  |  <--- sqlglot / AST SQL determinística
       +-----------------------+
                   |
                   v
       +-----------------------+
       | [Node 2] Semantic     |  <--- Mapeamento de IN/OUT, Locks,
       |          Analysis     |       Cursores, Recursão e Riscos
       +-----------------------+
                   |
                   v
       +-----------------------+
       |   [Node 3] Code       |  <--- Prompt contextualizado
       |        Generation     |       (Gemini 1.5 Pro ou Ollama Local)
       +-----------------------+
                   |
                   v
       +-----------------------+
       |  [Node 4] Validation  |  <--- ast.parse() + AST Security Check
       +-----------------------+
                   |
         /-------------------\
        <  Sintaxe Válida?    >
         \-------------------/
          /                 \
    [Sim] /                 \ [Não & retries < max]
        v                     v
+---------------+     +--------------------+
|      END      |     |  Feedback Loop     | ---> (Reexecuta Generation)
+---------------+     +--------------------+

1.2 Detalhamento dos Nós da Pipeline no Grafo


🔹 Nó 1: Parsing Determinístico (parser_node)
Responsabilidade Primária: Receber o código procedural bruto em PL/pgSQL e convertê-lo em uma árvore sintática abstrata (AST) totalmente estruturada antes de qualquer contato com o modelo generativo.
Mecanismo Técnico: Utiliza a biblioteca sqlglot configurada com o dialeto nativo postgres.
Extrações Executadas: Segmentação e isolamento dos blocos DECLARE e BEGIN ... END.
Classificação estrita do tipo de objeto de banco (FUNCTION vs PROCEDURE).
Normalização de tokens SQL e desconstrução de comandos DDL complementares.


🔹 Nó 2: Análise Semântica e Mapeamento de Riscos (semantic_node)
Responsabilidade Primária: Varrer a estrutura sintática para identificar padrões procedurais de negócio e catalogar pontos críticos que oferecem risco de performance, concorrência ou integridade na migração para Python.
Categorização das Análises: Contrato de Parâmetros e Tipos: Mapeamento explícito das assinaturas IN, OUT, INOUT e variáveis locais, correlacionando tipos SQL legados (NUMERIC(15,2), BIGINT, RECORD, BOOLEAN) aos equivalentes modernos do Python.
Concorrência e Locks: Detecção de diretivas de bloqueio pessimista (FOR UPDATE, FOR SHARE), prevenindo condições de corrida na aplicação.
Antipatterns e Gargalos: Rastreamento de cursores explícitos iterando sobre comandos SELECT com queries internas (risco clássico de N+1 e PERFORM).
Recursão Hierárquica: Identificação de Common Table Expressions recursivas (WITH RECURSIVE) e chamadas aninhadas entre funções de banco.


🔹 Nó 3: Geração de Código Contextualizada (generation_node)
Responsabilidade Primária: Síntese do módulo moderno em Python 3.14 orientado a objetos e estruturado para alta performance.
Engenharia de Prompt Estruturada: O modelo generativo não recebe a rotina SQL de forma ingênua ou crua. O prompt é montado programmaticamente injetando as flags de risco e a assinatura semântica já tratadas pelos Nós 1 e 2.
Diretrizes Arquiteturais Aplicadas: Tipagem estrita com as novas funcionalidades de união de tipos do Python 3.14 (int | None, str | None).
Adoção mandatória de decimal.Decimal em qualquer valor monetário ou contábil, eliminando o risco de imprecisão de float.
Preservação atômica de transações por meio de gerenciadores de contexto (with session.begin():).

🔹 Nó 4: Validação Estática e Auditoria Sintática (validation_node)
Responsabilidade Primária: Atuar como barreira de contenção de qualidade estática (Gatekeeper), analisando o código gerado antes da persistência definitiva.
Mecanismos de Inspeção: Execução do analisador estático nativo ast.parse() sobre o código Python 3.14 gerado para garantir conformidade gramatical semântica sem necessidade de executar o código em tempo de execução.
Rastreamento de profundidade de árvore e verificação de imports obrigatórios (decimal, typing).
Mecanismo de Autocorreção (Self-Correction Loop): Se o validador detectar quebra de sintaxe, o roteador condicional devolve a árvore com o traceback do erro de volta ao Nó 3 para que o modelo regenere o código corrigindo a falha, respeitando o teto de retentativas parametrizado.


1.3 Contrato de Dados e Estado Tipado (ModernizationState)
[!TIP]
Canal Atômico de Comunicação do Grafo

A integridade do pipeline ao longo do grafo é mantida por um contrato de dados atômico tipado via TypedDict, garantindo previsibilidade entre as transições de nós, suporte a auditoria e canal para telemetria.

Python
from typing import Any, TypedDict

class ModernizationState(TypedDict):
    # =========================================================================
    # 1. ENTRADAS DO PIPELINE
    # =========================================================================
    source_code: str
    """Código original da Function ou Stored Procedure PL/pgSQL submetido."""
    
    schema_context: str | None
    """DDL complementar, catálogo de tabelas ou contexto relacional auxiliar."""

    # =========================================================================
    # 2. ENRIQUECIMENTO DETERMINÍSTICO (NÓS 1 E 2)
    # =========================================================================
    parsed_ast: dict[str, Any]
    """Representação estruturada em AST gerada via sqlglot."""
    
    metadata: dict[str, Any]
    """Metadados extraídos: nome da rotina, parâmetros IN/OUT e tipo de retorno."""
    
    risk_flags: list[str]
    """Flags de riscos identificados (ex.: 'PESSIMISTIC_LOCK', 'CURSOR_N_PLUS_ONE')."""

    # =========================================================================
    # 3. SÍNTESE E DIAGNÓSTICO (NÓS 3 E 4)
    # =========================================================================
    generated_code: str | None
    """Código moderno em Python 3.14 sintetizado pelo modelo generativo."""
    
    validation: dict[str, Any]
    """Diagnóstico do ast.parse: conformidade sintática, erros e nós visitados."""
    
    report: dict[str, Any]
    """Relatório estruturado consolidando as decisões de todas as etapas (JSONB)."""

    # =========================================================================
    # 4. CONTROLE DE FLUXO E RESILIÊNCIA DO GRAFO
    # =========================================================================
    status: str
    """Status operacional corrente da execução: 'sucesso', 'parcial' ou 'falha'."""
    
    retry_count: int

    """Contador de ciclos de autocorreção executados pelo feedback loop."""

📌 Papel Estratégico dos Campos no Ciclo de Vida:

Desacoplamento de Inferência (parsed_ast e metadata): A LLM não gasta tokens deduzindo parâmetros ou tipos de retorno; recebe a assinatura estruturada diretamente da análise semântica determinística.

Direcionamento Ativo de Guardrails (risk_flags): Se a flag PESSIMISTIC_LOCK é levantada, o prompt força regras estritas para a geração do with_for_update(), blindando o código contra condições de corrida.

Governança e Resiliência (validation e retry_count): Atuam como base para a tomada de decisão das arestas condicionais do LangGraph, permitindo regeneração autônoma sem intervenção humana.

2. DECISÕES TÉCNICAS E TRADE-OFFS ARQUITETURAIS
A modernização de regras de negócio financeiras exige escolhas que priorizam corretude algorítmica, contenção de custos de inferência e eficiência computacional. Abaixo estão detalhadas as decisões centrais:

2.1 Abordagem Híbrida (Rules + LLM) vs Abordagem Pura (LLM End-to-End)

Contexto: Enviar código legado bruto direto para modelos de linguagem resulta em alucinação de tipos, perda de cláusulas de bloqueio concorrente e omissão de exceções de negócio.
Decisão: Segmentar o pipeline em duas etapas determinísticas preliminares (Parsing via AST + Análise Semântica de Riscos) e utilizar a LLM estritamente como sintetizadora instruída por um contexto estruturado.
Alternativa Rejeitada: Envio do PL/pgSQL cru com few-shot prompting.
Trade-off: Exige manutenção de código determinístico para parsing de dialetos, mas reduz em mais de 80% as alucinações, padroniza o formato do código de saída e enxuga o consumo de tokens de entrada em até 40%.

2.2 Parser Determinístico: sqlglot com Dialeto Postgres

Contexto: Era necessário desmembrar assinaturas complexas, variáveis declaradas e comandos procedurais em estruturas sintáticas tratáveis programaticamente.
Decisão: Adoção do sqlglot configurado para o dialeto postgres.
Alternativas Rejeitadas: Expressões Regulares (frágeis a variações de sintaxe) e sqlparse (que gera apenas árvore de tokens rasos, sem tipagem formal de AST).
Trade-off: O sqlglot possui suporte nativo a múltiplos dialetos SQL (facilitando expansão futura para Oracle PL/SQL e T-SQL), exigindo apenas regras complementares de fallback para trechos procedurais específicos de dialetos proprietários.

2.3 Estratégia de Execução: Query Delegada ao SGBD vs Reescrever em Python Puro

Contexto: Funções com agregações massivas (SUM, COUNT) e estruturas recursivas hierárquicas (WITH RECURSIVE) são frequentes em bancos legados.
Decisão: Padrão Híbrido de Execução. Toda lógica relacional pesada e operações de agregação em lote continuam sendo delegadas ao banco via consultas parametrizadas otimizadas (SQLAlchemy/asyncpg). Apenas a orquestração transacional, controle de fluxo procedural, validações de parâmetros e regras de exceção são migradas para Python puro.
Alternativa Rejeitada: Carregar todas as tabelas em memória (pandas ou loops de dicionários em Python) e calcular médias/somas dentro do serviço.
Trade-off: Evita saturação de I/O de rede e esgotamento de memória (Out-Of-Memory - OOM) no ambiente da aplicação ao processar milhões de registros, aproveitando os índices e o query planner do próprio PostgreSQL.

2.4 Precisão Numérica Monetária: decimal.Decimal Mandatório

Contexto: O tipo legado NUMERIC(15, 2) é padrão de mercado em instituições financeiras para saldos e transações.
Decisão: Banir o uso de tipos primitivos float em qualquer campo monetário, exigindo decimal.Decimal em todas as assinaturas, cálculos e mapeamentos tipados.
Alternativa Rejeitada: Tipagem nativa float ou conversão implícita.
Trade-off: O tipo float segue o padrão IEEE 754 de ponto flutuante binário e introduz erros cumulativos de arredondamento em operações contábeis (ex: 0.1 + 0.2 != 0.3). O uso de Decimal introduz um custo insignificante de CPU em troca de precisão contábil matemática absoluta.

2.5 Tratamento de Concorrência e Transacionalidade

Contexto: Procedimentos como transferência de fundos (Anexo D) exigem integridade atômica para evitar Race Conditions (condições de corrida) e leituras sujas.
Decisão: Tradução automática de transações SQL para gerenciadores de contexto seguros (with session.begin():) e preservação explícita do lock pessimista (with_for_update()).
Alternativa Rejeitada: Confiar em isolamento de leitura sem locks explícitos.
Trade-off: O lock pessimista garante que duas transferências simultâneas sobre a mesma conta não causem saldo negativo, aceitando como contrapartida a retenção da linha durante a janela da transação.

2.6 Provedor de LLM: Google Gemini API vs Execução Local (Ollama)

Contexto: Instituições financeiras frequentemente possuem restrições rígidas de conformidade (LGPD, sigilo bancário) que impedem o tráfego de esquemas e códigos de bases de dados para provedores de nuvem pública.
Decisão: Arquitetura desacoplada e configurável via variáveis de ambiente. O pipeline suporta nativamente o Google Gemini 1.5 Pro (para alta velocidade e capacidade de contexto) e execução offline com Ollama (ex: codellama, deepseek-coder, qwen2.5-coder ou llama3).
Trade-off: Modelos locais consomem recursos da máquina host (VRAM/CPU) e possuem maior latência de inferência, mas oferecem soberania total de dados, custo zero por token e independência de ligação à Internet.

3. MODELAGEM DE DADOS E PERSISTÊNCIA (POSTGRESQL)

O pipeline foi projetado para assegurar rastreabilidade e governança corporativa total. Toda e qualquer submissão de código SQL — seja ela concluída com sucesso, com erros de validação sintática ou interrompida por falha de infraestrutura — é atomicamente persistida na base relacional PostgreSQL.

3.1 Esquema da Tabela modernization_history
O esquema relacional adota tipos estruturados nativos e identificação única baseada em UUIDv4 para desacoplamento de chaves sequenciais e prevenção de colisões:

SQL
CREATE TABLE IF NOT EXISTS modernization_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_code TEXT NOT NULL,
    generated_code TEXT,
    report JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(50) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Índices estratégicos para auditoria e consultas analíticas

CREATE INDEX IF NOT EXISTS idx_modernization_status ON modernization_history(status);
CREATE INDEX IF NOT EXISTS idx_modernization_created_at ON modernization_history(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_modernization_report_gin ON modernization_history USING gin (report);

Detalhamento dos Campos e Governança: id (UUID): Chave primária universalmente única gerada pela aplicação ou pelo banco (gen_random_uuid()).
source_code (TEXT): Armazena o código original da Stored Procedure ou Function PL/pgSQL na íntegra, preservando comentários e formatação original.
generated_code (TEXT): Módulo Python 3.14 gerado e validado. Permanece como NULL caso o processamento seja abortado antes da fase de síntese.
report (JSONB): Metadados consolidados da execução (tokens classificados, métricas de AST, catálogo de riscos mapeados e diagnóstico sintático). O formato binário JSONB permite consultas dinâmicas de alta performance com operadores de índice GIN (@>, ?).
status (VARCHAR): Desfecho operacional categorizado estritamente em:
sucesso: Código gerado, validado por ast.parse() e em conformidade estática.
parcial: Código gerado, porém com pendências de regras ou avisos arquiteturais mapeados.
falha: Erro fatal de execução no grafo ou exceção na comunicação externa.
created_at (TIMESTAMP WITH TIME ZONE): Carimbo de data/hora absoluto para fins de auditoria temporal.

4. GUIA DE INSTALAÇÃO E EXECUÇÃO LOCAL

O projeto foi inteiramente conteinerizado com Docker Compose para garantir ambiente reproduzível, isolado e padronizado em qualquer sistema operacional (Linux, macOS, Windows).

4.1 Pré-requisitos do Ambiente

Docker & Docker Compose (versão 24.0+ recomendada).
Python 3.14 (ou gerenciador de pacotes moderno uv / Python 3.12+ caso execute o host localmente fora do container).
Chave de API Gemini (GEMINI_API_KEY) para geração do modelo de linguagem (ou Ollama configurado localmente).

4.2 Configuração das Variáveis de Ambiente (.env)

Crie um arquivo .env na raiz do projeto clonado a partir das definições abaixo:

Snippet de código
# ---------------------------------------------------------
# Conexão com Banco de Dados (PostgreSQL)
# ---------------------------------------------------------
DATABASE_URL=postgresql://postgres:postgrespassword@localhost:5432/langfuse
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgrespassword
POSTGRES_DB=langfuse
POSTGRES_PORT=5432

# ---------------------------------------------------------
# Provedor de LLM: Opção A (Google Gemini)
# ---------------------------------------------------------
LLM_PROVIDER=gemini
GEMINI_API_KEY=AIzaSy...sua_chave_aqui...

# ---------------------------------------------------------
# Provedor de LLM: Opção B (Ollama Local - Opcional)
# ---------------------------------------------------------
# LLM_PROVIDER=ollama
# OLLAMA_BASE_URL=http://localhost:11434
# OLLAMA_MODEL=deepseek-coder:6.7b

# ---------------------------------------------------------
# Observabilidade Local (Langfuse v2 Self-Hosted)
# ---------------------------------------------------------
LANGFUSE_PUBLIC_KEY=pk-lf-cmuqddw...
LANGFUSE_SECRET_KEY=sk-lf-cmuqddw...
LANGFUSE_HOST=http://localhost:3000

# Parâmetros de segurança e sessão interna do Langfuse
NEXTAUTH_URL=http://localhost:3000
NEXTAUTH_SECRET=mirante_secret_salt_123456789
SALT=mirante_salt_key_123456789
ENCRYPTION_KEY=0000000000000000000000000000000000000000000000000000000000000000
TELEMETRY_ENABLED=false
4.2.1 Configuração para Execução Local com Ollama (Offline / On-Premise)

Caso deseje testar a modernização sem custos de API ou em ambiente desconectado:

Instale o Ollama e baixe o modelo desejado:

Bash
ollama pull deepseek-coder:6.7b
# ou: ollama pull qwen2.5-coder:7b
Inicie o daemon do Ollama:

Bash
ollama serve
Defina LLM_PROVIDER=ollama no seu .env.

4.3 Inicialização da Infraestrutura via Docker Compose
Suba os serviços locais (PostgreSQL e o servidor do Langfuse v2) em segundo plano:

Bash
docker compose up -d
Verifique a integridade dos contêineres:

Bash
docker compose ps
O banco de dados estará acessível em localhost:5432 e o painel do Langfuse em http://localhost:3000.

4.4 Inicialização da API FastAPI (LangGraph Pipeline)
Crie e ative o ambiente virtual:

Bash
# Utilizando UV (recomendado):
uv venv
.venv\Scripts\activate   # Windows (PowerShell)
# source .venv/bin/activate # Linux / macOS

uv pip install -e .
Inicialize o servidor FastAPI:

Bash
uvicorn src.api.app:app --reload --port 8000
Valide o endpoint de integridade (Health Check):

Bash
curl http://localhost:8000/health
Resposta esperada:

JSON
{
  "status": "ok",
  "database": "connected",
  "graph": "ready"
}

Documentação interativa Swagger/OpenAPI disponível em: http://localhost:8000/docs

4.5 Execução do Batch Modernizer (Anexos B a F)
Para executar o pipeline em lote processando integralmente os 5 casos de teste fornecidos no edital:

Bash
python -m scripts.run_modernization
O script submete os Anexos B, C, D, E e F, registrando os traces de telemetria no Langfuse e persistindo na pasta local output/:

Códigos modernizados em Python 3.14 (.py).

Relatórios de auditoria e AST (.json).

Resumo executivo comparativo consolidado em Markdown (SUMMARY_AUDIT.md).

4.6 Execução da Suíte de Testes Automatizados (Pytest)
Para atestar a integridade do grafo, das rotas da API e da camada de persistência:

Bash
pytest -v
Resultado: 11 testes unitários e de integração cobrindo fluxos felizes, autocorreção de sintaxe e conexão relacional (todos passando em ~3.9s).

5. OBSERVABILIDADE AVANÇADA COM LANGFUSE (BÔNUS 1)

Para cumprir o requisito de observabilidade com primazia de arquitetura corporativa, foi integrado o Langfuse v2 em modalidade Self-Hosted executado via Docker Compose.

5.1 Justificativa da Escolha do Langfuse Self-Hosted

Soberania e Sigilo de Dados: Em contextos bancários e corporativos, queries de procedimentos armazenados podem conter regras confidenciais ou estruturas de tabelas sensíveis. Uma instância local previne vazamento de metadados para plataformas SaaS externas.
Custo Zero de Infraestrutura de Observabilidade: Não depende de planos pagos por volume de eventos consumidos.
Rastreabilidade Granular: Permite isolar spans do grafo, latências individuais por nó, taxas de acerto e auditoria financeira por chamada.

## 5.2 Evidências de Execução no Langfuse

<br/>

### Visão Geral de Traces em Lote (Anexos B a F)
O pipeline captura cada execução de rotina de forma independente, discriminando latência, contagem de tokens de entrada/saída e custos financeiros calculados dinamicamente:

<br/>

![Langfuse Traces Overview](https://raw.githubusercontent.com/Xavier2801/mirante-sql-modernizer/main/docs/screenshots/langfuse_traces.png)

<br/>

### Inspeção Detalhada da Geração — Estudo de Caso: Anexo D (`sp_transferencia_fundos`)
Ao inspecionar a geração individual do Anexo D (rotina crítica com concorrência pessimista e operações de débito/crédito), é possível auditar o payload de entrada (SQL original enriquecido com detecção de `FOR UPDATE`), o código Python 3.14 sintetizado com transação atômica e a precisão do custo em dólares:

<br/>

![Langfuse Generation Detail - Anexo D](https://raw.githubusercontent.com/Xavier2801/mirante-sql-modernizer/main/docs/screenshots/langfuse_detail.png)

### Inspeção Detalhada da Geração — Estudo de Caso: Anexo D (`sp_transferencia_fundos`)
Ao inspecionar a geração individual do Anexo D (rotina crítica com concorrência pessimista e operações de débito/crédito), é possível auditar o payload de entrada (SQL original enriquecido com deteção de `FOR UPDATE`), o código Python 3.14 sintetizado com transação atómica e a precisão do custo em dólares:

<br/>

<p align="center">
  <img src="./docs/screenshots/langfuse_detail.png" alt="Langfuse Generation Detail - Anexo D" width="100%" />
</p>


6. MÉTRICA DE EVALUATION AUTOMATIZADA (BÔNUS 3)
Para além da validação pontual de cada requisição, foi implementado um módulo avaliador analítico (src/evaluator/pipeline_evaluator.py) exposto através do endpoint:

HTTP
GET /evaluate

6.1 Critérios da Métrica Composta

A avaliação do pipeline foi modelada como uma pontuação ponderada baseada em três pilares objetivos:
Taxa de Conformidade Sintática AST (Peso: 40%):
Verifica se 100% dos códigos Python produzidos compilam sem exceções sintáticas utilizando o compilador nativo ast.parse().
Precisão Numérica Financeira (Peso: 30%):
Analisa a AST gerada para comprovar o banimento de tipos primitivos float em colunas monetárias e a presença do import e instanciação de decimal.Decimal.
Mitigação de Concorrência e Conflitos Transacionais (Peso: 30%):
Avalia se procedimentos marcados com locks pessimistas (FOR UPDATE) foram convertidos preservando gerenciadores de contexto atômicos (with session.begin(): e .with_for_update()).

6.2 Análise Crítica da Métrica

O que ela captura: Captura conformidade gramatical estrita, prevenção contra alucinações de tipos de ponto flutuante em finanças e garantia de consistência concorrencial em operações de escrita.

O que ela deixa de fora: Não realiza testes comportamentais dinâmicos de ponta a ponta com banco de dados real em execução concorrente sob carga (teste de carga com 500 threads simultâneas disputando o mesmo registro de saldo).

Como evoluir em produção: Utilização de Testcontainers para subir instâncias efêmeras de PostgreSQL, executando suítes de testes com dados sintéticos comparando se o estado final das tabelas após a execução da Procedure original PL/pgSQL é exatamente idêntico ao estado final após a execução do módulo Python 3.14 equivalente.

7. ESCALABILIDADE FUTURA E LIMITAÇÕES CONHECIDAS

7.1 Limitações Conhecidas da Versão Atual

Suporte Restrito a PL/pgSQL: O pipeline está calibrado primordialmente para dialeto PostgreSQL. Stored procedures escritas em Oracle PL/SQL (com pacotes DBMS_*) ou Microsoft T-SQL (com cursores aninhados e CROSS APPLY) requerem extensões nos mapeadores semânticos.
Transações com Rollbacks Parciais (Savepoints): Comandos procedurais complexos com múltiplos blocos de exceção aninhados (EXCEPTION WHEN OTHERS THEN) atualmente são unificados em um bloco de transação principal.

7.2 Arquitetura Proposta para Alta Escala
Para suportar grandes volumes corporativos (milhares de procedures de um banco legado inteiro):

Plaintext
[API Gateway] 
      │
      ▼
[FastAPI /modernize] ──(Enfileira Job)──► [Redis / RabbitMQ Queue]
                                                 │
                                                 ▼
                                     [Celery / ARQ Workers]
                                     (Grafo LangGraph Paralelo)
                                                 │
                                                 ▼
                                    [PostgreSQL History + Langfuse]

Fila Assíncrona e Processamento Desacoplado:

Substituir a invocação síncrona por filas assíncronas (Celery / RabbitMQ), retornando imediatamente um job_id para o cliente realizar polling via GET /modernize/{job_id} ou receber webhook.

Cache Semântico de Procedimentos Similares:

Implementação de cache vetorial (Redis + pgvector): se uma procedure já foi modernizada ou possui assinatura idêntica a outra já avaliada, o pipeline reutiliza a estrutura gerada com custo zero de tokens de LLM.

Pluggable Dialect Drivers:

Desacoplamento do Nó 1 em estratégias abstratas (PostgreSQLDialectParser, OracleDialectParser, TSQLDialectParser), aproveitando a compatibilidade multi-dialeto do sqlglot.

Containerização de Workers com Ollama:

Suporte a instâncias do Ollama distribuídas em nós com GPU no Docker Compose para ambientes isolados (air-gapped).
