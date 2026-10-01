"""
Ponto de Entrada da API FastAPI (Modernizador PL/pgSQL -> Python 3.14).
Fornece endpoints de modernização, auditoria e verificação de saúde da aplicação.
"""
import json
import os
import uuid
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from src.graph.workflow import modernization_graph

# --------------------------------------------------------------------------
# Configuração de Conexão com o Banco de Dados
# --------------------------------------------------------------------------
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgrespassword@postgres:5432/mirante_modernizer",
)
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Dependency injector para obtenção e liberação de sessões do SQLAlchemy."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


app = FastAPI(
    title="Mirante SQL Modernizer API",
    description="Pipeline com LangGraph para modernização de rotinas legadas PL/pgSQL para Python 3.14.",
    version="1.0.0",
)


# --------------------------------------------------------------------------
# Esquemas Pydantic v2
# --------------------------------------------------------------------------

class ModernizeRequest(BaseModel):
    source_code: str = Field(..., description="Código SQL da Function ou Procedure PL/pgSQL.")
    schema_context: Optional[str] = Field(None, description="DDL ou esquema relacional complementar.")


class ModernizeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Union[int, UUID, str] = Field(..., description="Identificador único do registro de modernização.")
    procedure_name: Optional[str] = Field(None, description="Nome da rotina identificado pela análise.")
    source_code: str = Field(..., description="Código PL/pgSQL original submetido.")
    generated_code: Optional[str] = Field(None, description="Código Python 3.14 gerado e validado.")
    report: Dict[str, Any] = Field(default_factory=dict, description="Relatório detalhado de AST e riscos.")
    status: str = Field(..., description="Status final do processamento (sucesso ou falha).")


class HealthResponse(BaseModel):
    status: str
    database: str
    graph: str


# --------------------------------------------------------------------------
# Endpoints da Aplicação
# --------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse, tags=["Monitoramento"])
def health_check(db: Session = Depends(get_db)):
    """Verifica a integridade da API, conexão com PostgreSQL e estado do grafo."""
    db_status = "connected"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_status = "disconnected"

    return {
        "status": "ok" if db_status == "connected" else "degraded",
        "database": db_status,
        "graph": "ready" if modernization_graph is not None else "unavailable",
    }


@app.post(
    "/modernize",
    response_model=ModernizeResponse,
    status_code=status.HTTP_200_OK,
    tags=["Modernização"],
)
def modernize_sql(payload: ModernizeRequest, db: Session = Depends(get_db)):
    """Executa a pipeline de 4 nós do LangGraph e persiste o histórico de auditoria."""
    initial_state = {
        "source_code": payload.source_code,
        "schema_context": payload.schema_context,
    }

    try:
        # Execução síncrona dos nós do LangGraph
        result_state = modernization_graph.invoke(initial_state)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro durante o processamento do grafo: {str(exc)}",
        )

    # Identificador resiliente para a resposta
    history_id = result_state.get("id") or str(uuid.uuid4())
    status_result = result_state.get("status", "sucesso")
    generated_code = result_state.get("generated_code")
    report_data = result_state.get("report", {})
    proc_name = (
            result_state.get("metadata", {}).get("procedure_name")
            or report_data.get("metadata", {}).get("procedure_name")
    )

    # Persistência na tabela modernization_history
    try:
        insert_query = text("""
                            INSERT INTO modernization_history (source_code, generated_code, report, status)
                            VALUES (:source_code, :generated_code, CAST(:report AS jsonb), :status)
                                RETURNING id;
                            """)
        persisted_row = db.execute(
            insert_query,
            {
                "source_code": payload.source_code,
                "generated_code": generated_code,
                "report": json.dumps(report_data),
                "status": status_result,
            },
        ).fetchone()
        db.commit()
        if persisted_row:
            history_id = persisted_row[0]
    except Exception:
        db.rollback()

    return ModernizeResponse(
        id=history_id,
        procedure_name=proc_name,
        source_code=payload.source_code,
        generated_code=generated_code,
        report=report_data,
        status=status_result,
    )


@app.get(
    "/history",
    response_model=List[Dict[str, Any]],
    tags=["Auditoria"],
)
def list_history(limit: int = 50, db: Session = Depends(get_db)):
    """Retorna os registros históricos da tabela modernization_history."""
    query = text("""
                 SELECT id, source_code, generated_code, report, status, created_at
                 FROM modernization_history
                 ORDER BY created_at DESC
                     LIMIT :limit;
                 """)
    rows = db.execute(query, {"limit": limit}).fetchall()
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