"""
Módulo de Repositório para Persistência no PostgreSQL.
Gerencia a gravação e consulta do histórico de modernização na tabela modernization_history.
"""
import os
import json
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Configuração da URL da base de dados via variável de ambiente (12-Factor App)
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
    ) -> int:
        """
        Insere um novo registo de modernização na tabela modernization_history.
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
                                       :report,
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
                record_id = result.scalar()

            return record_id
        """
        Insere um novo registo de modernização na tabela modernization_history.
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
                                       :report,
                                       :status,
                                       :created_at
                                   )
                                RETURNING id;
                            """)

        with self.SessionLocal() as session:
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
            session.commit()
            record_id = result.scalar()
            return record_id

    def check_connection(self) -> bool:
        """Verifica se o pool de conexões consegue contactar o PostgreSQL (Healthcheck)."""
        try:
            with self.SessionLocal() as session:
                session.execute(text("SELECT 1;"))
                return True
        except Exception:
            return False