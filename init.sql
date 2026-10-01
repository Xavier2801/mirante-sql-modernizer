-- DDL de inicialização da base de dados PostgreSQL para rastreio do pipeline
CREATE TABLE IF NOT EXISTS modernization_history (
                                                     id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_code TEXT NOT NULL,
    generated_code TEXT,
    report JSONB NOT NULL,
    status VARCHAR(20) NOT NULL CHECK (status IN ('sucesso', 'falha', 'parcial')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );

-- Índice para consultas frequentes por status e ordenação temporal
CREATE INDEX IF NOT EXISTS idx_modernization_status ON modernization_history (status);
CREATE INDEX IF NOT EXISTS idx_modernization_created_at ON modernization_history (created_at DESC);

-- Extensões necessárias
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- -------------------------------------------------------------
-- Tabelas de Negócio Legadas (Contexto DDL - Anexo A)
-- -------------------------------------------------------------

CREATE TABLE IF NOT EXISTS clientes (
                                        id BIGSERIAL PRIMARY KEY,
                                        nome VARCHAR(150) NOT NULL,
    documento VARCHAR(20) UNIQUE NOT NULL,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    criado_em TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                            );

CREATE TABLE IF NOT EXISTS contas (
                                      id BIGSERIAL PRIMARY KEY,
                                      cliente_id BIGINT NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    numero_conta VARCHAR(20) UNIQUE NOT NULL,
    saldo NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    status VARCHAR(20) NOT NULL DEFAULT 'ATIVA',
    criado_em TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                                                                                             );

CREATE TABLE IF NOT EXISTS transacoes (
                                          id BIGSERIAL PRIMARY KEY,
                                          conta_origem_id BIGINT REFERENCES contas(id),
    conta_destino_id BIGINT REFERENCES contas(id),
    valor NUMERIC(15, 2) NOT NULL,
    tipo VARCHAR(20) NOT NULL,
    data_transacao TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                                 );

-- Índices para otimização de concorrência e filtros
CREATE INDEX IF NOT EXISTS idx_contas_cliente ON contas(cliente_id);
CREATE INDEX IF NOT EXISTS idx_contas_status ON contas(status);
CREATE INDEX IF NOT EXISTS idx_transacoes_origem ON transacoes(conta_origem_id);

-- -------------------------------------------------------------
-- Tabela de Auditoria da Pipeline de Modernização (Obrigatória)
-- -------------------------------------------------------------

CREATE TABLE IF NOT EXISTS modernization_history (
                                                     id BIGSERIAL PRIMARY KEY,
                                                     source_code TEXT NOT NULL,
                                                     generated_code TEXT,
                                                     report JSONB NOT NULL,
                                                     status VARCHAR(20) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
                             );

CREATE INDEX IF NOT EXISTS idx_history_created_at ON modernization_history(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_history_status ON modernization_history(status);