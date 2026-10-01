"""
Serviço de Abstração de Modelos de Linguagem (LLM Service).
Suporta Google Gemini, Ollama (local) e OpenAI de forma resiliente e tipada.
"""
import os
import re
from typing import Optional


class LLMService:
    """Encapsula a comunicação com diferentes provedores de LLM."""

    def __init__(
            self,
            provider: Optional[str] = None,
            model_name: Optional[str] = None,
            api_key: Optional[str] = None,
    ):
        self.provider = (provider or os.getenv("LLM_PROVIDER", "gemini")).lower()
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY")

        if self.provider == "gemini":
            self.model_name = model_name or os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
            self._init_gemini()
        elif self.provider == "ollama":
            self.model_name = model_name or os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")
            self.base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            self._init_ollama()
        elif self.provider == "openai":
            self.model_name = model_name or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            self._init_openai()
        else:
            raise ValueError(f"Provedor LLM não suportado: {self.provider}")

    def _init_gemini(self) -> None:
        """Inicializa o cliente Google GenAI."""
        from google import genai

        if not self.api_key:
            raise ValueError("GEMINI_API_KEY não foi configurada nas variáveis de ambiente.")
        self.client = genai.Client(api_key=self.api_key)

    def _init_ollama(self) -> None:
        """Inicializa o cliente Ollama."""
        import ollama

        self.client = ollama.Client(host=self.base_url)

    def _init_openai(self) -> None:
        """Inicializa o cliente OpenAI."""
        from openai import OpenAI

        if not self.api_key:
            raise ValueError("OPENAI_API_KEY não foi configurada nas variáveis de ambiente.")
        self.client = OpenAI(api_key=self.api_key)

    def generate(
            self,
            prompt: Optional[str] = None,
            source_code: Optional[str] = None,
            metadata: Optional[dict] = None,
            analysis: Optional[dict] = None,
            schema_context: Optional[str] = None,
            **kwargs
    ) -> str:
        """Gera código modernizado a partir de prompt direto ou parâmetros de AST/análise."""
        # Se não recebeu um prompt textual pronto, compõe o prompt com base nos parâmetros
        if not prompt:
            prompt_parts = [
                "Você é um engenheiro de software sênior/Staff especialista em migração de bancos relacionais para Python 3.14.",
                "Converta a seguinte rotina PL/pgSQL para Python 3.14 moderno utilizando SQLAlchemy (Session) e padrões assíncronos/síncronos estritos com tipagem completa (Decimal para tipos monetários, sem loops N+1).\n",
                f"--- CÓDIGO FONTE PL/PGSQL ---\n{source_code or kwargs.get('sql', '')}\n"
            ]
            if metadata:
                prompt_parts.append(f"Metadados extraídos: {metadata}")
            if analysis:
                prompt_parts.append(f"Análise semântica e riscos: {analysis}")
            if schema_context:
                prompt_parts.append(f"Esquema DDL: {schema_context}")

            prompt_parts.append("\nRetorne EXCLUSIVAMENTE o bloco de código Python moderno e tipado.")
            final_prompt = "\n".join(prompt_parts)
        else:
            final_prompt = prompt

        if self.provider == "gemini":
            raw_text = self._call_gemini(final_prompt)
        elif self.provider == "ollama":
            raw_text = self._call_ollama(final_prompt)
        elif self.provider == "openai":
            raw_text = self._call_openai(final_prompt)
        else:
            raise ValueError(f"Provedor desconhecido: {self.provider}")

        return self._extract_python_code(raw_text)

    def _call_gemini(self, prompt: str) -> str:
        """Invoca a API do Google Gemini com tratamento robusto do retorno."""
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
        )

        # 1. Se response for uma lista de respostas
        if isinstance(response, list):
            collected = []
            for item in response:
                if hasattr(item, "text") and isinstance(item.text, str):
                    collected.append(item.text)
                else:
                    collected.append(str(item))
            return "".join(collected).strip()

        # 2. Se response.text for uma string direta
        if hasattr(response, "text") and isinstance(response.text, str):
            return response.text.strip()

        # 3. Se response.text for uma lista de chunks/strings
        if hasattr(response, "text") and isinstance(response.text, list):
            return "".join(str(part) for part in response.text).strip()

        # 4. Extração via estrutura interna de candidates e parts
        if hasattr(response, "candidates") and response.candidates:
            first_candidate = response.candidates[0]
            if hasattr(first_candidate, "content") and hasattr(first_candidate.content, "parts"):
                chunks = []
                for part in first_candidate.content.parts:
                    if hasattr(part, "text") and part.text:
                        chunks.append(part.text)
                return "".join(chunks).strip()

        return str(response).strip()

    def _call_ollama(self, prompt: str) -> str:
        """Invoca o modelo local via Ollama."""
        response = self.client.generate(
            model=self.model_name,
            prompt=prompt,
        )
        return str(response.get("response", "")).strip()

    def _call_openai(self, prompt: str) -> str:
        """Invoca a API OpenAI."""
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        return str(response.choices[0].message.content or "").strip()

    @staticmethod
    def _extract_python_code(text: str) -> str:
        """Remove delimitadores markdown como ```python e ``` da resposta."""
        if not text:
            return ""

        # Padrão para blocos de código markdown com python
        pattern = r"```(?:python)?\s*(.*?)\s*```"
        matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)
        if matches:
            return matches[0].strip()

        return text.strip()