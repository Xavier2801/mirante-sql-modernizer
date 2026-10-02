"""
Ponto de Entrada da API FastAPI (Modernizador PL/pgSQL -> Python 3.14).
Fornece endpoints de modernização, auditoria e observabilidade com Langfuse.
"""
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from langfuse import Langfuse
from pydantic import BaseModel, ConfigDict, Field

from src.graph.workflow import modernization_graph
from src.repository.history_repository import HistoryRepository
from src.validator.pipeline_evaluator import PipelineEvaluator

load_dotenv()

pipeline_evaluator = PipelineEvaluator()
OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "output"

app = FastAPI(
    title="Mirante SQL Modernizer API",
    description="Pipeline híbrido com LangGraph para modernização de rotinas legadas PL/pgSQL para Python 3.14.",
    version="1.0.0",
)

history_repo = HistoryRepository()

# Cliente de Observabilidade Langfuse
pk = os.getenv("LANGFUSE_PUBLIC_KEY")
sk = os.getenv("LANGFUSE_SECRET_KEY")
host = os.getenv("LANGFUSE_HOST", "http://localhost:3000")
langfuse_client = Langfuse(public_key=pk, secret_key=sk, host=host) if (pk and sk) else None


# --------------------------------------------------------------------------
# Modelos Pydantic v2
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
    status: str = Field(..., description="Status final do processamento (sucesso, falha ou parcial).")


class HealthResponse(BaseModel):
    status: str
    database: str
    graph: str


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse, tags=["Monitoramento"])
def health_check():
    db_ok = history_repo.check_connection()
    db_status = "connected" if db_ok else "disconnected"

    return {
        "status": "ok" if db_ok else "degraded",
        "database": db_status,
        "graph": "ready" if modernization_graph is not None else "unavailable",
    }


@app.post(
    "/modernize",
    response_model=ModernizeResponse,
    status_code=status.HTTP_200_OK,
    tags=["Modernização"],
)
def modernize_sql(payload: ModernizeRequest):
    """Executa o pipeline do LangGraph com rastreamento no Langfuse e persistência auditável."""
    initial_state = {
        "source_code": payload.source_code,
        "schema_context": payload.schema_context,
    }

    # Inicia o trace de observabilidade
    trace = None
    span = None
    if langfuse_client:
        trace = langfuse_client.trace(
            name="modernize_procedure",
            metadata={"target": "Python 3.14", "pipeline": "LangGraph"}
        )
        span = trace.span(name="langgraph_execution", input=initial_state)

    try:
        result_state = modernization_graph.invoke(initial_state)
        if span:
            span.end(output=result_state)
    except Exception as exc:
        if span:
            span.end(level="ERROR", status_message=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro durante o processamento do grafo: {str(exc)}",
        )
    finally:
        if langfuse_client:
            langfuse_client.flush()

    status_result = result_state.get("status", "falha")
    generated_code = result_state.get("generated_code")
    report_data = result_state.get("report", {})
    proc_name = (
            result_state.get("metadata", {}).get("procedure_name")
            or report_data.get("procedure_name")
    )

    try:
        history_id = history_repo.save_execution(
            source_code=payload.source_code,
            generated_code=generated_code,
            report=report_data,
            status=status_result,
        )
    except Exception:
        history_id = str(uuid.uuid4())

    return ModernizeResponse(
        id=history_id,
        procedure_name=proc_name,
        source_code=payload.source_code,
        generated_code=generated_code,
        report=report_data,
        status=status_result,
    )


@app.get("/history", response_model=List[Dict[str, Any]], tags=["Auditoria"])
def list_history(limit: int = 50):
    return history_repo.list_recent(limit=limit)


@app.get("/evaluate", tags=["Avaliação de Qualidade"])
def evaluate_pipeline_benchmark():
    return pipeline_evaluator.evaluate_output_directory(OUTPUT_DIR)