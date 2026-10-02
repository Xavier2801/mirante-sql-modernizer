"""
Suite de Testes da Camada HTTP FastAPI.
Valida os endpoints /health e /modernize de forma rápida e desacoplada de I/O de rede.
"""
from unittest.mock import patch
from fastapi.testclient import TestClient
from src.api.app import app
from src.repository.history_repository import HistoryRepository

client = TestClient(app)


def test_get_health():
    """Valida o endpoint /health com checagem de banco mockada."""
    with patch.object(HistoryRepository, "check_connection", return_value=True):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["graph"] == "ready"
        assert data["database"] == "connected"


def test_post_modernize_validacao_fluxo():
    """Valida o endpoint /modernize isolando LLM e persistência PostgreSQL."""
    payload = {
        "source_code": """
                       CREATE OR REPLACE FUNCTION fn_teste_api(p_id BIGINT)
        RETURNS VOID
        LANGUAGE plpgsql
        AS $$
                       BEGIN
                       NULL;
                       END;
        $$;
                       """,
        "schema_context": None,
    }

    mock_python_code = '''"""
Módulo gerado para fn_teste_api.
"""
from sqlalchemy.orm import Session

def fn_teste_api(session: Session, p_id: int) -> None:
    pass
'''

    with (
        patch("src.generator.llm_service.LLMService.generate", return_value=mock_python_code),
        patch.object(HistoryRepository, "save_execution", return_value=1),
    ):
        response = client.post("/modernize", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("sucesso", "parcial")
    assert data["procedure_name"] == "fn_teste_api"
    assert data["id"] == 1
    assert "report" in data
    assert "validation" in data["report"]