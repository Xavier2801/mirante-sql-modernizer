"""
Serviço de Abstração de Modelos de Linguagem (LLM Service).
Suporta Google Gemini, Ollama (local) e OpenAI com telemetria nativa de tokens e custos.
"""
import os
import re
from typing import Optional, Dict, Any


class LLMService:
    """Encapsula a comunicação com LLMs, rastreando tokens e custo estimado."""

    # Preços de referência por 1M tokens (USD)
    PRICING = {
        "gemini-3.8-flash": {"input_per_million": 0.075, "output_per_million": 0.30},
        "gemini-1.5-flash": {"input_per_million": 0.075, "output_per_million": 0.30},
        "gpt-4o-mini": {"input_per_million": 0.15, "output_per_million": 0.60},
        "ollama": {"input_per_million": 0.0, "output_per_million": 0.0},
    }

    def __init__(
            self,
            provider: Optional[str] = None,
            model_name: Optional[str] = None,
            api_key: Optional[str] = None,
    ):
        self.provider = (provider or os.getenv("LLM_PROVIDER", "gemini")).lower()
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY")

        self.last_telemetry: Dict[str, Any] = {
            "provider": self.provider,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "estimated_cost_brl": 0.0,
        }

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
        from google import genai
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY não configurada.")
        self.client = genai.Client(api_key=self.api_key)

    def _init_ollama(self) -> None:
        import ollama
        self.client = ollama.Client(host=self.base_url)

    def _init_openai(self) -> None:
        from openai import OpenAI
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY não configurada.")
        self.client = OpenAI(api_key=self.api_key)

    def generate(
            self,
            prompt: Optional[str] = None,
            source_code: Optional[str] = None,
            metadata: Optional[dict] = None,
            analysis: Optional[dict] = None,
            schema_context: Optional[str] = None,
            **kwargs,
    ) -> str:
        """Gera código modernizado aceitando tanto prompt único quanto parâmetros nomeados."""
        if not prompt:
            prompt_parts = [
                "Você é um engenheiro de software Staff especialista em banco de dados e modernização para Python 3.14.",
                "Converta a rotina PL/pgSQL abaixo para código idiomático e performático utilizando SQLAlchemy 2.0.",
                "REGRAS INEGOCIÁVEIS:",
                "- Use estritamente decimal.Decimal para valores monetários/saldos (nunca float).",
                "- Elimine loops cursados e evite antipadrões N+1 usando agregações ou subconsultas.",
                "- Implemente locking pessimista com with_for_update() ou SELECT FOR UPDATE quando houver concorrência bancária.",
                "- Tipagem estática completa com PEP 484/604.\n",
                f"--- CÓDIGO FONTE PL/PGSQL ---\n{source_code or kwargs.get('sql', '')}\n",
            ]
            if metadata:
                prompt_parts.append(f"Metadados sintáticos: {metadata}")
            if analysis:
                prompt_parts.append(f"Diagnóstico de riscos: {analysis}")
            if schema_context:
                prompt_parts.append(f"Contexto DDL: {schema_context}")

            prompt_parts.append("\nRetorne EXCLUSIVAMENTE o bloco de código Python moderno.")
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
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
        )

        # Rastreamento de tokens nativo do Gemini
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0

        if hasattr(response, "usage_metadata") and response.usage_metadata:
            meta = response.usage_metadata
            prompt_tokens = getattr(meta, "prompt_token_count", 0) or 0
            completion_tokens = getattr(meta, "candidates_token_count", 0) or 0
            total_tokens = getattr(meta, "total_token_count", 0) or (prompt_tokens + completion_tokens)

        self._record_telemetry(prompt_tokens, completion_tokens, total_tokens)

        # Extração de texto resiliente
        if hasattr(response, "text") and isinstance(response.text, str):
            return response.text.strip()
        if hasattr(response, "candidates") and response.candidates:
            parts = response.candidates[0].content.parts
            return "".join([p.text for p in parts if hasattr(p, "text")]).strip()
        return str(response).strip()

    def _call_ollama(self, prompt: str) -> str:
        response = self.client.generate(model=self.model_name, prompt=prompt)
        p_tokens = response.get("prompt_eval_count", 0)
        c_tokens = response.get("eval_count", 0)
        self._record_telemetry(p_tokens, c_tokens, p_tokens + c_tokens)
        return str(response.get("response", "")).strip()

    def _call_openai(self, prompt: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        usage = response.usage
        p_tokens = usage.prompt_tokens if usage else 0
        c_tokens = usage.completion_tokens if usage else 0
        self._record_telemetry(p_tokens, c_tokens, p_tokens + c_tokens)
        return str(response.choices[0].message.content or "").strip()

    def _record_telemetry(self, prompt_tokens: int, completion_tokens: int, total_tokens: int) -> None:
        """Calcula o custo financeiro aproximado com base na precificação do modelo."""
        pricing = self.PRICING.get(self.model_name, self.PRICING.get("gemini-3.8-flash"))
        cost_usd = (
                (prompt_tokens / 1_000_000) * pricing["input_per_million"]
                + (completion_tokens / 1_000_000) * pricing["output_per_million"]
        )
        usd_to_brl_rate = 5.60

        self.last_telemetry = {
            "provider": self.provider,
            "model": self.model_name,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "estimated_cost_usd": round(cost_usd, 6),
            "estimated_cost_brl": round(cost_usd * usd_to_brl_rate, 6),
        }

    @staticmethod
    def _extract_python_code(text: str) -> str:
        if not text:
            return ""
        pattern = r"```(?:python)?\s*(.*?)\s*```"
        matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)
        return matches[0].strip() if matches else text.strip()