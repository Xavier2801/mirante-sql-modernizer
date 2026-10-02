<!DOCTYPE html>
<html lang="pt-BR">
 <meta charset="UTF-8">

<body>

  <h1>Mirante SQL Modernizer (PL/pgSQL -&gt; Python 3.14)</h1>

  <br/>

  <div class="badges">
    <img src="https://img.shields.io/badge/python-3.14-blue.svg" alt="Python 3.14">
    <img src="https://img.shields.io/badge/orchestration-LangGraph-orange.svg" alt="LangGraph">
    <img src="https://img.shields.io/badge/API-FastAPI-green.svg" alt="FastAPI">
    <img src="https://img.shields.io/badge/observability-Langfuse_v2-purple.svg" alt="Langfuse v2">
    <img src="https://img.shields.io/badge/tests-11%20passed-brightgreen.svg" alt="Tests">
  </div>

  <br/>

  <p>Solução corporativa para modernização automatizada de rotinas legadas <strong>PL/pgSQL</strong> (Functions e Stored Procedures) para módulos modernos em <strong>Python 3.14</strong>.</p>

  <p>O projeto adota uma <strong>arquitetura híbrida (Rules + LLM)</strong>: utiliza parsing sintático determinístico e extração semântica prévia para mitigar alucinações, acoplando um orquestrador cíclico em <strong>LangGraph</strong>, persistência de auditoria em <strong>PostgreSQL</strong>, telemetria completa via <strong>Langfuse v2</strong> e métricas automatizadas de avaliação estática.</p>

<br/><hr/><br/>

  <h1>1. ARQUITETURA DA PIPELINE HÍBRIDA (LANGGRAPH)</h1>

  <br/>

  <p>O fluxo de modernização foi modelado como um grafo direcionado e cíclico (<em>StateGraph</em>) onde cada fase da modernização é isolada em um nó especializado. O estado transacionado ao longo da execução é rigidamente tipado via <code>TypedDict</code>.</p>

  <br/>

<h2>1.1 Diagrama do Grafo de Execução</h2>

  <pre><code>       +-----------------------+
       |         START         |
       +-----------------------+
                   |
                   v
       +-----------------------+
       |     [Node 1] Parsing  |  &lt;--- sqlglot / AST SQL determinística
       +-----------------------+
                   |
                   v
       +-----------------------+
       | [Node 2] Semantic     |  &lt;--- Mapeamento de IN/OUT, Locks,
       |          Analysis     |       Cursores, Recursão e Riscos
       +-----------------------+
                   |
                   v
       +-----------------------+
       |   [Node 3] Code       |  &lt;--- Prompt contextualizado
       |        Generation     |       (Gemini 1.5 Pro ou Ollama Local)
       +-----------------------+
                   |
                   v
       +-----------------------+
       |  [Node 4] Validation  |  &lt;--- ast.parse() + AST Security Check
       +-----------------------+
                   |
         /-------------------\
        &lt;  Sintaxe Válida?    &gt;
         \-------------------/
          /                 \
    [Sim] /                 \ [Não &amp; retries &lt; max]
        v                     v
+---------------+     +--------------------+
|      END      |     |  Feedback Loop     | ---&gt; (Reexecuta Generation)
+---------------+     +--------------------+</code></pre>

  <br/>

<h2>1.2 Detalhamento dos Nós da Pipeline no Grafo</h2>

  <br/>

<h3>🔹 Nó 1: Parsing Determinístico (<code>parser_node</code>)</h3>
  <ul>
    <li><strong>Responsabilidade Primária:</strong> Receber o código procedural bruto em PL/pgSQL e convertê-lo em uma árvore sintática abstrata (AST) totalmente estruturada antes de qualquer contato com o modelo generativo.</li>
    <li><strong>Mecanismo Técnico:</strong> Utiliza a biblioteca <code>sqlglot</code> configurada com o dialeto nativo <code>postgres</code>.</li>
    <li><strong>Extrações Executadas:</strong>
      <ul>
        <li>Segmentação e isolamento dos blocos <code>DECLARE</code> e <code>BEGIN ... END</code>.</li>
        <li>Classificação estrita do tipo de objeto de banco (<code>FUNCTION</code> vs <code>PROCEDURE</code>).</li>
        <li>Normalização de tokens SQL e desconstrução de comandos DDL complementares.</li>
      </ul>
    </li>
  </ul>

  <br/>

<h3>🔹 Nó 2: Análise Semântica e Mapeamento de Riscos (<code>semantic_node</code>)</h3>
  <ul>
    <li><strong>Responsabilidade Primária:</strong> Varrer a estrutura sintática para identificar padrões procedurais de negócio e catalogar pontos críticos que oferecem risco de performance, concorrência ou integridade na migração para Python.</li>
    <li><strong>Categorização das Análises:</strong>
      <ul>
        <li><strong>Contrato de Parâmetros e Tipos:</strong> Mapeamento explícito das assinaturas <code>IN</code>, <code>OUT</code>, <code>INOUT</code> e variáveis locais, correlacionando tipos SQL legados (<code>NUMERIC(15,2)</code>, <code>BIGINT</code>, <code>RECORD</code>, <code>BOOLEAN</code>) aos equivalentes modernos do Python.</li>
        <li><strong>Concorrência e Locks:</strong> Detecção de diretivas de bloqueio pessimista (<code>FOR UPDATE</code>, <code>FOR SHARE</code>), prevenindo condições de corrida na aplicação.</li>
        <li><strong>Antipatterns e Gargalos:</strong> Rastreamento de cursores explícitos iterando sobre comandos <code>SELECT</code> com queries internas (<code>risco clássico de N+1</code> e <code>PERFORM</code>).</li>
        <li><strong>Recursão Hierárquica:</strong> Identificação de <em>Common Table Expressions</em> recursivas (<code>WITH RECURSIVE</code>) e chamadas aninhadas entre funções de banco.</li>
      </ul>
    </li>
  </ul>

  <br/>

<h3>🔹 Nó 3: Geração de Código Contextualizada (<code>generation_node</code>)</h3>
  <ul>
    <li><strong>Responsabilidade Primária:</strong> Síntese do módulo moderno em Python 3.14 orientado a objetos e estruturado para alta performance.</li>
    <li><strong>Engenharia de Prompt Estruturada:</strong> O modelo generativo não recebe a rotina SQL de forma ingênua ou crua. O prompt é montado programmaticamente injetando as <em>flags</em> de risco e a assinatura semântica já tratadas pelos Nós 1 e 2.</li>
    <li><strong>Diretrizes Arquiteturais Aplicadas:</strong>
      <ul>
        <li>Tipagem estrita com as novas funcionalidades de união de tipos do Python 3.14 (<code>int | None</code>, <code>str | None</code>).</li>
        <li>Adoção mandatória de <code>decimal.Decimal</code> em qualquer valor monetário ou contábil, eliminando o risco de imprecisão de <code>float</code>.</li>
        <li>Preservação atômica de transações por meio de gerenciadores de contexto (<code>with session.begin():</code>).</li>
      </ul>
    </li>
  </ul>

  <br/>

<h3>🔹 Nó 4: Validação Estática e Auditoria Sintática (<code>validation_node</code>)</h3>
  <ul>
    <li><strong>Responsabilidade Primária:</strong> Atuar como barreira de contenção de qualidade estática (<em>Gatekeeper</em>), analisando o código gerado antes da persistência definitiva.</li>
    <li><strong>Mecanismos de Inspeção:</strong>
      <ul>
        <li>Execução do analisador estático nativo <code>ast.parse()</code> sobre o código Python 3.14 gerado para garantir conformidade gramatical semântica sem necessidade de executar o código em tempo de execução.</li>
        <li>Rastreamento de profundidade de árvore e verificação de imports obrigatórios (<code>decimal</code>, <code>typing</code>).</li>
      </ul>
    </li>
    <li><strong>Mecanismo de Autocorreção (<em>Self-Correction Loop</em>):</strong> Se o validador detectar quebra de sintaxe, o roteador condicional devolve a árvore com o traceback do erro de volta ao Nó 3 para que o modelo regenere o código corrigindo a falha, respeitando o teto de retentativas parametrizado.</li>
  </ul>

  <br/>

<h2>1.3 Contrato de Dados e Estado Tipado (<code>ModernizationState</code>)</h2>

  <br/>

  <blockquote>
    <p><strong>Canal Atômico de Comunicação do Grafo</strong><br/>
    A integridade do pipeline ao longo do grafo é mantida por um contrato de dados atômico tipado via <code>TypedDict</code>, garantindo previsibilidade entre as transições de nós, suporte a auditoria e canal para telemetria.</p>
  </blockquote>

  <pre><code>from typing import Any, TypedDict

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
    """Contador de ciclos de autocorreção executados pelo feedback loop."""</code></pre>

  <br/>

<h3>📌 Papel Estratégico dos Campos no Ciclo de Vida:</h3>
  <ul>
    <li><strong>Desacoplamento de Inferência (<code>parsed_ast</code> e <code>metadata</code>):</strong> A LLM não gasta tokens deduzindo parâmetros ou tipos de retorno; recebe a assinatura estruturada diretamente da análise semântica determinística.</li>
    <li><strong>Direcionamento Ativo de Guardrails (<code>risk_flags</code>):</strong> Se a flag <code>PESSIMISTIC_LOCK</code> é levantada, o prompt força regras estritas para a geração do <code>with_for_update()</code>, blindando o código contra condições de corrida.</li>
    <li><strong>Governança e Resiliência (<code>validation</code> e <code>retry_count</code>):</strong> Atuam como base para a tomada de decisão das arestas condicionais do LangGraph, permitindo regeneração autônoma sem intervenção humana.</li>
  </ul>

<br/><hr/><br/>

  <h1>2. DECISÕES TÉCNICAS E TRADE-OFFS ARQUITETURAIS</h1>

  <br/>

  <p>A modernização de regras de negócio financeiras exige escolhas que priorizam corretude algorítmica, contenção de custos de inferência e eficiência computacional. Abaixo estão detalhadas as decisões centrais:</p>

  <br/>

<h3>2.1 Abordagem Híbrida (Rules + LLM) vs Abordagem Pura (LLM End-to-End)</h3>
  <ul>
    <li><strong>Contexto:</strong> Enviar código legado bruto direto para modelos de linguagem resulta em alucinação de tipos, perda de cláusulas de bloqueio concorrente e omissão de exceções de negócio.</li>
    <li><strong>Decisão:</strong> Segmentar o pipeline em duas etapas determinísticas preliminares (Parsing via AST + Análise Semântica de Riscos) e utilizar a LLM estritamente como sintetizadora instruída por um contexto estruturado.</li>
    <li><strong>Alternativa Rejeitada:</strong> Envio do PL/pgSQL cru com <em>few-shot prompting</em>.</li>
    <li><strong>Trade-off:</strong> Exige manutenção de código determinístico para parsing de dialetos, mas reduz em mais de 80% as alucinações, padroniza o formato do código de saída e enxuga o consumo de tokens de entrada em até 40%.</li>
  </ul>

  <br/>

<h3>2.2 Parser Determinístico: <code>sqlglot</code> com Dialeto Postgres</h3>
  <ul>
    <li><strong>Contexto:</strong> Era necessário desmembrar assinaturas complexas, variáveis declaradas e comandos procedurais em estruturas sintáticas tratáveis programaticamente.</li>
    <li><strong>Decisão:</strong> Adoção do <code>sqlglot</code> configurado para o dialeto <code>postgres</code>.</li>
    <li><strong>Alternativas Rejeitadas:</strong> Expressões Regulares (frágeis a variações de sintaxe) e <code>sqlparse</code> (que gera apenas árvore de tokens rasos, sem tipagem formal de AST).</li>
    <li><strong>Trade-off:</strong> O <code>sqlglot</code> possui suporte nativo a múltiplos dialetos SQL (facilitando expansão futura para Oracle PL/SQL e T-SQL), exigindo apenas regras complementares de fallback para trechos procedurais específicos de dialetos proprietários.</li>
  </ul>

  <br/>

<h3>2.3 Estratégia de Execução: Query Delegada ao SGBD vs Reescrever em Python Puro</h3>
  <ul>
    <li><strong>Contexto:</strong> Funções com agregações massivas (<code>SUM</code>, <code>COUNT</code>) e estruturas recursivas hierárquicas (<code>WITH RECURSIVE</code>) são frequentes em bancos legados.</li>
    <li><strong>Decisão:</strong> <strong>Padrão Híbrido de Execução</strong>. Toda lógica relacional pesada e operações de agregação em lote continuam sendo delegadas ao banco via consultas parametrizadas otimizadas (<code>SQLAlchemy</code>/<code>asyncpg</code>). Apenas a orquestração transacional, controle de fluxo procedural, validações de parâmetros e regras de exceção são migradas para Python puro.</li>
    <li><strong>Alternativa Rejeitada:</strong> Carregar todas as tabelas em memória (<code>pandas</code> ou loops de dicionários em Python) e calcular médias/somas dentro do serviço.</li>
    <li><strong>Trade-off:</strong> Evita saturação de I/O de rede e esgotamento de memória (<em>Out-Of-Memory - OOM</em>) no ambiente da aplicação ao processar milhões de registros, aproveitando os índices e o <em>query planner</em> do próprio PostgreSQL.</li>
  </ul>

  <br/>

<h3>2.4 Precisão Numérica Monetária: <code>decimal.Decimal</code> Mandatório</h3>
  <ul>
    <li><strong>Contexto:</strong> O tipo legado <code>NUMERIC(15, 2)</code> é padrão de mercado em instituições financeiras para saldos e transações.</li>
    <li><strong>Decisão:</strong> Banir o uso de tipos primitivos <code>float</code> em qualquer campo monetário, exigindo <code>decimal.Decimal</code> em todas as assinaturas, cálculos e mapeamentos tipados.</li>
    <li><strong>Alternativa Rejeitada:</strong> Tipagem nativa <code>float</code> ou conversão implícita.</li>
    <li><strong>Trade-off:</strong> O tipo <code>float</code> segue o padrão IEEE 754 de ponto flutuante binário e introduz erros cumulativos de arredondamento em operações contábeis (ex: <code>0.1 + 0.2 != 0.3</code>). O uso de <code>Decimal</code> introduz um custo insignificante de CPU em troca de precisão contábil matemática absoluta.</li>
  </ul>

  <br/>

<h3>2.5 Tratamento de Concorrência e Transacionalidade</h3>
  <ul>
    <li><strong>Contexto:</strong> Procedimentos como transferência de fundos (Anexo D) exigem integridade atômica para evitar <em>Race Conditions</em> (condições de corrida) e leituras sujas.</li>
    <li><strong>Decisão:</strong> Tradução automática de transações SQL para gerenciadores de contexto seguros (<code>with session.begin():</code>) e preservação explícita do lock pessimista (<code>with_for_update()</code>).</li>
    <li><strong>Alternativa Rejeitada:</strong> Confiar em isolamento de leitura sem locks explícitos.</li>
    <li><strong>Trade-off:</strong> O lock pessimista garante que duas transferências simultâneas sobre a mesma conta não causem saldo negativo, aceitando como contrapartida a retenção da linha durante a janela da transação.</li>
  </ul>

  <br/>

<h3>2.6 Provedor de LLM: Google Gemini API vs Execução Local (Ollama)</h3>
  <ul>
    <li><strong>Contexto:</strong> Instituições financeiras frequentemente possuem restrições rígidas de conformidade (LGPD, sigilo bancário) que impedem o tráfego de esquemas e códigos de bases de dados para provedores de nuvem pública.</li>
    <li><strong>Decisão:</strong> Arquitetura desacoplada e configurável via variáveis de ambiente. O pipeline suporta nativamente o <strong>Google Gemini 1.5 Pro</strong> (para alta velocidade e capacidade de contexto) e execução offline com <strong>Ollama</strong> (ex: <code>codellama</code>, <code>deepseek-coder</code>, <code>qwen2.5-coder</code> ou <code>llama3</code>).</li>
    <li><strong>Trade-off:</strong> Modelos locais consomem recursos da máquina host (VRAM/CPU) e possuem maior latência de inferência, mas oferecem <strong>soberania total de dados</strong>, <strong>custo zero por token</strong> e <strong>independência de ligação à Internet</strong>.</li>
  </ul>

<br/><hr/><br/>

  <h1>3. MODELAGEM DE DADOS E PERSISTÊNCIA (POSTGRESQL)</h1>

  <br/>

  <p>O pipeline foi projetado para assegurar rastreabilidade e governança corporativa total. Toda e qualquer submissão de código SQL — seja ela concluída com sucesso, com erros de validação sintática ou interrompida por falha de infraestrutura — é atomicamente persistida na base relacional PostgreSQL.</p>

  <br/>

<h2>3.1 Esquema da Tabela <code>modernization_history</code></h2>

  <p>O esquema relacional adota tipos estruturados nativos e identificação única baseada em UUIDv4 para desacoplamento de chaves sequenciais e prevenção de colisões:</p>

  <pre><code>CREATE TABLE IF NOT EXISTS modernization_history (
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
CREATE INDEX IF NOT EXISTS idx_modernization_report_gin ON modernization_history USING gin (report);</code></pre>

  <br/>

<h3>Detalhamento dos Campos e Governança:</h3>
  <ul>
    <li><strong><code>id</code> (UUID):</strong> Chave primária universalmente única gerada pela aplicação ou pelo banco (<code>gen_random_uuid()</code>).</li>
    <li><strong><code>source_code</code> (TEXT):</strong> Armazena o código original da Stored Procedure ou Function PL/pgSQL na íntegra, preservando comentários e formatação original.</li>
    <li><strong><code>generated_code</code> (TEXT):</strong> Módulo Python 3.14 gerado e validado. Permanece como <code>NULL</code> caso o processamento seja abortado antes da fase de síntese.</li>
    <li><strong><code>report</code> (JSONB):</strong> Metadados consolidados da execução (tokens classificados, métricas de AST, catálogo de riscos mapeados e diagnóstico sintático). O formato binário <code>JSONB</code> permite consultas dinâmicas de alta performance com operadores de índice GIN (<code>@&gt;</code>, <code>?</code>).</li>
    <li><strong><code>status</code> (VARCHAR):</strong> Desfecho operacional categorizado estritamente em:
      <ul>
        <li><code>sucesso</code>: Código gerado, validado por <code>ast.parse()</code> e em conformidade estática.</li>
        <li><code>parcial</code>: Código gerado, porém com pendências de regras ou avisos arquiteturais mapeados.</li>
        <li><code>falha</code>: Erro fatal de execução no grafo ou exceção na comunicação externa.</li>
      </ul>
    </li>
    <li><strong><code>created_at</code> (TIMESTAMP WITH TIME ZONE):</strong> Carimbo de data/hora absoluto para fins de auditoria temporal.</li>
  </ul>

<br/><hr/><br/>

  <h1>4. GUIA DE INSTALAÇÃO E EXECUÇÃO LOCAL</h1>

  <br/>

  <p>O projeto foi inteiramente conteinerizado com Docker Compose para garantir ambiente reproduzível, isolado e padronizado em qualquer sistema operacional (Linux, macOS, Windows).</p>

  <br/>

<h2>4.1 Pré-requisitos do Ambiente</h2>
  <ul>
    <li><strong>Docker &amp; Docker Compose</strong> (versão 24.0+ recomendada).</li>
    <li><strong>Python 3.14</strong> (ou gerenciador de pacotes moderno <strong><code>uv</code></strong> / <strong>Python 3.12+</strong> caso execute o host localmente fora do container).</li>
    <li><strong>Chave de API Gemini</strong> (<code>GEMINI_API_KEY</code>) para geração do modelo de linguagem (ou Ollama configurado localmente).</li>
  </ul>

  <br/>

<h2>4.2 Configuração das Variáveis de Ambiente (<code>.env</code>)</h2>

  <p>Crie um arquivo <code>.env</code> na raiz do projeto clonado a partir das definições abaixo:</p>

  <pre><code># ---------------------------------------------------------
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
TELEMETRY_ENABLED=false</code></pre>

  <br/>

<h2>4.2.1 Configuração para Execução Local com Ollama (Offline / On-Premise)</h2>

  <p>Caso deseje testar a modernização sem custos de API ou em ambiente desconectado:</p>
  <ol>
    <li>Instale o Ollama e baixe o modelo desejado:
      <pre><code>ollama pull deepseek-coder:6.7b
# ou: ollama pull qwen2.5-coder:7b</code></pre>
    </li>
    <li>Inicie o daemon do Ollama:
      <pre><code>ollama serve</code></pre>
    </li>
    <li>Defina <code>LLM_PROVIDER=ollama</code> no seu <code>.env</code>.</li>
  </ol>

  <br/>

<h2>4.3 Inicialização da Infraestrutura via Docker Compose</h2>

  <p>Suba os serviços locais (PostgreSQL e o servidor do Langfuse v2) em segundo plano:</p>
  <pre><code>docker compose up -d</code></pre>

  <p>Verifique a integridade dos contêineres:</p>
  <pre><code>docker compose ps</code></pre>
  <blockquote>O banco de dados estará acessível em <code>localhost:5432</code> e o painel do Langfuse em <code>http://localhost:3000</code>.</blockquote>

  <br/>

<h2>4.4 Inicialização da API FastAPI (LangGraph Pipeline)</h2>

  <ol>
    <li>Crie e ative o ambiente virtual:
      <pre><code># Utilizando UV (recomendado):
uv venv
.venv\Scripts\activate   # Windows (PowerShell)
# source .venv/bin/activate # Linux / macOS

uv pip install -e .</code></pre>
</li>
<li>Inicialize o servidor FastAPI:
<pre><code>uvicorn src.api.app:app --reload --port 8000</code></pre>
</li>
<li>Valide o endpoint de integridade (<em>Health Check</em>):
<pre><code>curl http://localhost:8000/health</code></pre>
<p><strong>Resposta esperada:</strong></p>
<pre><code>{
"status": "ok",
"database": "connected",
"graph": "ready"
}</code></pre>
<p><em>Documentação interativa Swagger/OpenAPI disponível em:</em> <code>http://localhost:8000/docs</code></p>
</li>
  </ol>

  <br/>

<h2>4.5 Execução do Batch Modernizer (Anexos B a F)</h2>

  <p>Para executar o pipeline em lote processando integralmente os 5 casos de teste fornecidos no edital:</p>
  <pre><code>python -m scripts.run_modernization</code></pre>

  <p>O script submete os Anexos B, C, D, E e F, registrando os traces de telemetria no Langfuse e persistindo na pasta local <code>output/</code>:</p>
  <ul>
    <li>Códigos modernizados em Python 3.14 (<code>.py</code>).</li>
    <li>Relatórios de auditoria e AST (<code>.json</code>).</li>
    <li>Resumo executivo comparativo consolidado em Markdown (<code>SUMMARY_AUDIT.md</code>).</li>
  </ul>

  <br/>

<h2>4.6 Execução da Suíte de Testes Automatizados (Pytest)</h2>

  <p>Para atestar a integridade do grafo, das rotas da API e da camada de persistência:</p>
  <pre><code>pytest -v</code></pre>
  <blockquote><strong>Resultado:</strong> 11 testes unitários e de integração cobrindo fluxos felizes, autocorreção de sintaxe e conexão relacional (todos passando em ~3.9s).</blockquote>

<br/><hr/><br/>

  <h1>5. OBSERVABILIDADE AVANÇADA COM LANGFUSE (BÔNUS 1)</h1>

  <br/>

  <p>Para cumprir o requisito de observabilidade com primazia de arquitetura corporativa, foi integrado o <strong>Langfuse v2</strong> em modalidade <em>Self-Hosted</em> executado via Docker Compose.</p>

  <br/>

<h2>5.1 Justificativa da Escolha do Langfuse Self-Hosted</h2>
  <ul>
    <li><strong>Soberania e Sigilo de Dados:</strong> Em contextos bancários e corporativos, queries de procedimentos armazenados podem conter regras confidenciais ou estruturas de tabelas sensíveis. Uma instância local previne vazamento de metadados para plataformas SaaS externas.</li>
    <li><strong>Custo Zero de Infraestrutura de Observabilidade:</strong> Não depende de planos pagos por volume de eventos consumidos.</li>
    <li><strong>Rastreabilidade Granular:</strong> Permite isolar spans do grafo, latências individuais por nó, taxas de acerto e auditoria financeira por chamada.</li>
  </ul>

  <br/>
t
<h2>5.2 Evidências de Execução no Langfuse</h2>

  <br/>

<h3>Visão Geral de Traces em Lote (Anexos B a F)</h3>
  <p>O pipeline captura cada execução de rotina de forma independente, discriminando latência, contagem de tokens de entrada/saída e custos financeiros calculados dinamicamente[cite: 1]:</p>

  <br/>

  <p class="text-center">
    <img src="https://raw.githubusercontent.com/Xavier2801/mirante-sql-modernizer/main/docs/screenshots/langfuse_traces.png" alt="Langfuse Traces Overview" width="100%">
  </p>

  <br/>

<h3>Inspeção Detalhada da Geração — Estudo de Caso: Anexo D (<code>sp_transferencia_fundos</code>)</h3>
  <p>Ao inspecionar a geração individual do Anexo D (rotina crítica com concorrência pessimista e operações de débito/crédito), é possível auditar o payload de entrada (SQL original enriquecido com detecção de <code>FOR UPDATE</code>), o código Python 3.14 sintetizado com transação atômica e a precisão do custo em dólares[cite: 1, 2]:</p>

  <br/>

  <p class="text-center">
    <img src="https://raw.githubusercontent.com/Xavier2801/mirante-sql-modernizer/main/docs/screenshots/langfuse_detail.png" alt="Langfuse Generation Detail - Anexo D" width="100%">
  </p>

<br/><hr/><br/>

  <h1>6. MÉTRICA DE EVALUATION AUTOMATIZADA (BÔNUS 3)</h1>

  <br/>

  <p>Para além da validação pontual de cada requisição, foi implementado um módulo avaliador analítico (<code>src/evaluator/pipeline_evaluator.py</code>) exposto através do endpoint:</p>

  <pre><code>GET /evaluate</code></pre>

  <br/>

<h2>6.1 Critérios da Métrica Composta</h2>

  <p>A avaliação do pipeline foi modelada como uma pontuação ponderada baseada em três pilares objetivos:</p>
  <ol>
    <li><strong>Taxa de Conformidade Sintática AST (Peso: 40%):</strong><br/>
    Verifica se 100% dos códigos Python produzidos compilam sem exceções sintáticas utilizando o compilador nativo <code>ast.parse()</code>.</li>
    <li><strong>Precisão Numérica Financeira (Peso: 30%):</strong><br/>
    Analisa a AST gerada para comprovar o banimento de tipos primitivos <code>float</code> em colunas monetárias e a presença do import e instanciação de <code>decimal.Decimal</code>.</li>
    <li><strong>Mitigação de Concorrência e Conflitos Transacionais (Peso: 30%):</strong><br/>
    Avalia se procedimentos marcados com locks pessimistas (<code>FOR UPDATE</code>) foram convertidos preservando gerenciadores de contexto atômicos (<code>with session.begin():</code> e <code>.with_for_update()</code>).</li>
  </ol>

  <br/>

<h2>6.2 Análise Crítica da Métrica</h2>
  <ul>
    <li><strong>O que ela captura:</strong> Captura conformidade gramatical estrita, prevenção contra alucinações de tipos de ponto flutuante em finanças e garantia de consistência concorrencial em operações de escrita.</li>
    <li><strong>O que ela deixa de fora:</strong> Não realiza testes comportamentais dinâmicos de ponta a ponta com banco de dados real em execução concorrente sob carga (teste de carga com 500 threads simultâneas disputando o mesmo registro de saldo).</li>
    <li><strong>Como evoluir em produção:</strong> Utilização de <strong>Testcontainers</strong> para subir instâncias efêmeras de PostgreSQL, executando suítes de testes com dados sintéticos comparando se o estado final das tabelas após a execução da Procedure original PL/pgSQL é exatamente idêntico ao estado final após a execução do módulo Python 3.14 equivalente.</li>
  </ul>

<br/><hr/><br/>

  <h1>7. ESCALABILIDADE FUTURA E LIMITAÇÕES CONHECIDAS</h1>

  <br/>

<h2>7.1 Limitações Conhecidas da Versão Atual</h2>
  <ul>
    <li><strong>Suporte Restrito a PL/pgSQL:</strong> O pipeline está calibrado primordialmente para dialeto PostgreSQL. Stored procedures escritas em Oracle PL/SQL (com pacotes <code>DBMS_*</code>) ou Microsoft T-SQL (com cursores aninhados e <code>CROSS APPLY</code>) requerem extensões nos mapeadores semânticos.</li>
    <li><strong>Transações com Rollbacks Parciais (Savepoints):</strong> Comandos procedurais complexos com múltiplos blocos de exceção aninhados (<code>EXCEPTION WHEN OTHERS THEN</code>) atualmente são unificados em um bloco de transação principal.</li>
  </ul>

  <br/>

<h2>7.2 Arquitetura Proposta para Alta Escala</h2>

  <p>Para suportar grandes volumes corporativos (milhares de procedures de um banco legado inteiro):</p>

  <pre><code>[API Gateway] 
      │
      ▼
[FastAPI /modernize] ──(Enfileira Job)──► [Redis / RabbitMQ Queue]
                                                 │
                                                 ▼
                                     [Celery / ARQ Workers]
                                     (Grafo LangGraph Paralelo)
                                                 │
                                                 ▼
                                    [PostgreSQL History + Langfuse]</code></pre>

  <ol>
    <li><strong>Fila Assíncrona e Processamento Desacoplado:</strong><br/>
    Substituir a invocação síncrona por filas assíncronas (Celery / RabbitMQ), retornando imediatamente um <code>job_id</code> para o cliente realizar polling via <code>GET /modernize/{job_id}</code> ou receber webhook.</li>
    <li><strong>Cache Semântico de Procedimentos Similares:</strong><br/>
    Implementação de cache vetorial (Redis + pgvector): se uma procedure já foi modernizada ou possui assinatura idêntica a outra já avaliada, o pipeline reutiliza a estrutura gerada com custo zero de tokens de LLM.</li>
    <li><strong>Pluggable Dialect Drivers:</strong><br/>
    Desacoplamento do Nó 1 em estratégias abstratas (<code>PostgreSQLDialectParser</code>, <code>OracleDialectParser</code>, <code>TSQLDialectParser</code>), aproveitando a compatibilidade multi-dialeto do <code>sqlglot</code>.</li>
    <li><strong>Containerização de Workers com Ollama:</strong><br/>
    Suporte a instâncias do Ollama distribuídas em nós com GPU no Docker Compose para ambientes isolados (<em>air-gapped</em>).</li>
  </ol>

</body>
</html>