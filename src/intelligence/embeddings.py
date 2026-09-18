import asyncio
import logging
import time
from typing import List, Optional
import httpx

from src.core.config import OLLAMA_HOST, EMBEDDING_MODEL, HTTP_TIMEOUT

logger = logging.getLogger("DOE_BA_Engine")

# Limite seguro de caracteres para o nomic-embed-text (~2048 tokens context)
_MAX_CHARS = 3500


class OllamaEmbeddings:
    """
    Cliente assíncrono para geração de embeddings vetoriais via Ollama local.
    Reutiliza a conexão TCP/HTTP persistentemente através do httpx.AsyncClient.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        default_model: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.base_url = base_url or OLLAMA_HOST
        self.default_model = default_model or EMBEDDING_MODEL
        self._external_client = http_client is not None
        self.client = http_client or httpx.AsyncClient(
            base_url=self.base_url,
            timeout=HTTP_TIMEOUT,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self) -> None:
        """Encerra o pool de conexões HTTP caso gerenciado internamente."""
        if not self._external_client and not self.client.is_closed:
            await self.client.aclose()

    async def get_embedding(
        self,
        text: str,
        model: Optional[str] = None,
    ) -> List[float]:
        """
        Gera o vetor de embedding (768 dimensões) para um fragmento de texto.
        Trunca automaticamente no limite seguro e aplica até 3 retentativas com backoff.
        """
        if not text or not text.strip():
            return []

        target_model = model or self.default_model

        # Trunca para limite seguro do modelo
        if len(text) > _MAX_CHARS:
            logger.warning(f"Texto truncado: {len(text)} -> {_MAX_CHARS} chars para embedding.")
            text = text[:_MAX_CHARS]

        payload = {
            "model": target_model,
            "prompt": text,
            "options": {"num_ctx": 8192},
        }

        for attempt in range(3):
            start_time = time.perf_counter()
            try:
                response = await self.client.post("/api/embeddings", json=payload)
                response.raise_for_status()
                data = response.json()
                embedding = data.get("embedding", [])
                latency = (time.perf_counter() - start_time) * 1000
                logger.debug(
                    f"Embedding ({len(embedding)} dims) gerado em {latency:.2f}ms "
                    f"para {len(text)} chars (tentativa {attempt + 1})."
                )
                return embedding
            except httpx.HTTPStatusError as e:
                wait_time = 2 ** attempt
                logger.warning(
                    f"Ollama retornou HTTP {e.response.status_code} na tentativa {attempt + 1}. "
                    f"Aguardando {wait_time}s..."
                )
                await asyncio.sleep(wait_time)
            except Exception as e:
                logger.error(f"Erro ao conectar com Ollama para embedding: {e}")
                wait_time = 2 ** attempt
                await asyncio.sleep(wait_time)

        logger.error("Falha ao gerar embedding após 3 tentativas.")
        return []
