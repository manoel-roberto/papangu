import os
import yaml  # type: ignore[import-untyped]
import logging
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("DOE_BA_Engine")

# Banco de dados e Persistência
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql:///doe_ba")
POSTGRES_DSN = DATABASE_URL  # Alias para compatibilidade reversa

# Serviços de Inteligência (Ollama)
OLLAMA_HOST = os.getenv("OLLAMA_HOST", os.getenv("OLLAMA_URL", "http://localhost:11434"))
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:1.5b")

# Infraestrutura de Scraping e Resiliência (Servidor Apache 2.2.22)
DOE_BASE_URL = os.getenv("DOE_BASE_URL", "https://dool.egba.ba.gov.br")
SEMAPHORE_LIMIT = int(os.getenv("SEMAPHORE_LIMIT", "8"))
JITTER_MIN_MS = int(os.getenv("JITTER_MIN_MS", "200"))
JITTER_MAX_MS = int(os.getenv("JITTER_MAX_MS", "500"))
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "60.0"))

# API & Watchlist
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
WATCHLIST_PATH = os.getenv("WATCHLIST_PATH", "watchlist.yaml")


class WatchlistConfig(BaseModel):
    """Configurações dos termos e pessoas monitorados."""
    keywords: List[str] = Field(default_factory=list, description="Palavras-chave de interesse")
    pessoas_monitoradas: List[str] = Field(default_factory=list, description="Nomes de pessoas a monitorar")


def load_watchlist(path: Optional[str] = None) -> WatchlistConfig:
    """
    Carrega as configurações de filtros da watchlist com tolerância a falhas.
    Se o arquivo não existir ou estiver vazio, retorna configuração segura padrão.
    """
    target_path = Path(path or WATCHLIST_PATH)
    if not target_path.exists():
        logger.info(f"Arquivo de watchlist não encontrado em '{target_path}'. Inicializando lista vazia.")
        return WatchlistConfig(keywords=[], pessoas_monitoradas=[])

    try:
        with open(target_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if not data or not isinstance(data, dict):
                return WatchlistConfig(keywords=[], pessoas_monitoradas=[])
            return WatchlistConfig(
                keywords=data.get("keywords", []) or [],
                pessoas_monitoradas=data.get("pessoas_monitoradas", []) or []
            )
    except Exception as e:
        logger.error(f"Erro ao carregar watchlist de '{target_path}': {e}. Usando configuração vazia.")
        return WatchlistConfig(keywords=[], pessoas_monitoradas=[])
