"""
Teste unitário do HistoryRepository utilizando engine isolado.
"""
from sqlalchemy import text
from src.repository.history_repository import HistoryRepository

def test_history_repository_save_and_health():
    # Instancia com SQLite em memória para validar as queries e serialização JSON
    repo = HistoryRepository("sqlite:///:memory:")

    # Cria tabela temporária idêntica ao esquema do init.sql
    with repo.SessionLocal() as session:
        session.execute(text("""
                             CREATE TABLE modernization_history (
                                                                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                                                                    source_code TEXT NOT NULL,
                                                                    generated_code TEXT,
                                                                    report JSON NOT NULL,
                                                                    status VARCHAR(20) NOT NULL,
                                                                    created_at TIMESTAMP NOT NULL
                             );
                             """))
        session.commit()

    # Valida método check_connection
    assert repo.check_connection() is True

    # Valida inserção
    record_id = repo.save_execution(
        source_code="CREATE FUNCTION test() RETURNS void...",
        generated_code="def test(): pass",
        report={"procedure_name": "test", "risk_flags": []},
        status="sucesso"
    )

    assert record_id == 1