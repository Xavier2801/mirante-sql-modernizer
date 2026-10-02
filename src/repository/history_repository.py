"""
Módulo de Repositório para Persistência no PostgreSQL.
Gerencia a gravação e consulta do histórico de modernização na tabela modernization_history.
"""
import os
import json
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/mirante_modernizer"
)


class HistoryRepository:
    """Repositório responsável pelas operações de I/O na tabela modernization_history."""

    def __init__(self, db_url: Optional[str] = None):
        self.engine = create_engine(db_url or DATABASE_URL, echo=False)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

    def save_execution(
            self,
            source_code: str,
            generated_code: Optional[str],
            report: Dict[str, Any],
            status: str
    ) -> Any:
        """
        Insere um novo registro de modernização na tabela modernization_history.
        Retorna o ID gerado na base de dados.
        """
        insert_query = text("""
                            INSERT INTO modernization_history (
                                source_code,
                                generated_code,
                                report,
                                status,
                                created_at
                            )
                            VALUES (
                                       :source_code,
                                       :generated_code,
                                       CAST(:report AS jsonb),
                                       :status,
                                       :created_at
                                   )
                                RETURNING id;
                            """)

        with self.SessionLocal() as session:
            with session.begin():
                result = session.execute(
                    insert_query,
                    {
                        "source_code": source_code,
                        "generated_code": generated_code or "",
                        "report": json.dumps(report),
                        "status": status,
                        "created_at": datetime.now(timezone.utc)
                    }
                )
                return result.scalar()

    def list_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retorna os registros históricos mais recentes."""
        query = text("""
                     SELECT id, source_code, generated_code, report, status, created_at
                     FROM modernization_history
                     ORDER BY created_at DESC
                         LIMIT :limit;
                     """)
        with self.SessionLocal() as session:
            rows = session.execute(query, {"limit": limit}).fetchall()
            return [
                {
                    "id": r[0],
                    "source_code": r[1],
                    "generated_code": r[2],
                    "report": r[3],
                    "status": r[4],
                    "created_at": r[5].isoformat() if r[5] else None,
                }
                for r in rows
            ]

    def check_connection(self) -> bool:
        """Verifica a integridade da conexão com o PostgreSQL (Healthcheck)."""
        try:
            with self.SessionLocal() as session:
                session.execute(text("SELECT 1;"))
                return True
        except Exception:
            return False