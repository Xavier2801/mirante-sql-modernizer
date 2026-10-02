import os
import time
from dotenv import load_dotenv
from langfuse import Langfuse
from src.graph.workflow import modernization_graph

load_dotenv()

pk = os.getenv("LANGFUSE_PUBLIC_KEY")
sk = os.getenv("LANGFUSE_SECRET_KEY")
host = os.getenv("LANGFUSE_HOST", "http://localhost:3000")

print(f"Conectando ao Langfuse em {host}...")
langfuse = Langfuse(public_key=pk, secret_key=sk, host=host)

trace = langfuse.trace(
    name="pipeline_modernization_test",
    metadata={"pipeline": "LangGraph", "target": "Python 3.14"}
)

sql_exemplo = """
CREATE OR REPLACE FUNCTION fn_teste()
RETURNS void AS $$
BEGIN
    NULL;
END;
$$ LANGUAGE plpgsql;
"""

span = trace.span(name="langgraph_execution", input={"source_code": sql_exemplo})

try:
    resultado = modernization_graph.invoke({"source_code": sql_exemplo})
    span.end(output=resultado)
    print("Grafo executado com sucesso!")
except Exception as e:
    span.end(level="ERROR", status_message=str(e))
    print(f"Erro na execução: {e}")

langfuse.flush()
time.sleep(2)
print("Trace enviado com sucesso! Recarregue a aba Traces no navegador.")
