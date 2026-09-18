import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Optional
import httpx

from src.core.config import (
    DOE_BASE_URL,
    SEMAPHORE_LIMIT,
    HTTP_TIMEOUT,
    JITTER_MIN_MS,
    JITTER_MAX_MS,
)
from src.core.models import DownloadedDocument
from src.utils.helpers import apply_jitter, format_date_to_api

logger = logging.getLogger("DOE_BA_Engine")


class DOEBahiaClient:
    """
    Cliente assíncrono otimizado para o Diário Oficial do Estado da Bahia (DOE-BA).
    Projetado com respeito estrito aos limites do servidor legado Apache/2.2.22:
    - Semaphore concorrente estrito (padrão 8).
    - Jitter aleatório (200-500ms) entre requisições.
    - Exponential backoff em falhas de rede.
    """

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or DOE_BASE_URL
        self.semaphore = asyncio.Semaphore(SEMAPHORE_LIMIT)
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
            ),
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "*/*",
        }
        self.http_client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self.headers,
            timeout=HTTP_TIMEOUT,
            verify=False,
            follow_redirects=True,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self) -> None:
        """Encerra a sessão HTTP assíncrona."""
        if not self.http_client.is_closed:
            await self.http_client.aclose()

    async def get_summary_html(self, edicao_id: str) -> Optional[str]:
        """
        Recupera o fragmento HTML do sumário de uma edição diretamente.
        Este HTML já contém os nós de matérias e os metadados da edição.
        """
        url = f"/html/{edicao_id}.html"
        async with self.semaphore:
            await apply_jitter(JITTER_MIN_MS, JITTER_MAX_MS)
            try:
                response = await self.http_client.get(url)
                response.raise_for_status()
                return response.text
            except Exception as e:
                logger.error(f"Falha ao obter sumário para ID {edicao_id}: {e}")
                return None

    async def get_editions_by_date(self, date_str: str) -> List[str]:
        """
        Busca edições de uma data específica (DD/MM/AAAA) via API JSON.
        Retorna lista de IDs internos das edições encontradas.
        """
        api_date = format_date_to_api(date_str)
        url = f"/apifront/portal/edicoes/edicoes_from_data/{api_date}.json"

        logger.info(f"Buscando edições para a data: {date_str}")
        async with self.semaphore:
            await apply_jitter(JITTER_MIN_MS, JITTER_MAX_MS)
            try:
                response = await self.http_client.get(url)
                response.raise_for_status()
                data = response.json()
                return [str(item["id"]) for item in data.get("itens", []) if "id" in item]
            except Exception as e:
                logger.error(f"Erro ao buscar edições por data ({date_str}): {e}")
                return []

    async def get_editions_by_range(self, start_date: str, end_date: str) -> List[str]:
        """
        Busca edições em um intervalo de datas iterando dia a dia.
        Garante respeito ao servidor legado e deduplicação de IDs.
        """
        logger.info(f"Buscando edições no período: {start_date} até {end_date}")
        try:
            dt_start = datetime.strptime(start_date, "%d/%m/%Y")
            dt_end = datetime.strptime(end_date, "%d/%m/%Y")

            ids: List[str] = []
            current = dt_start
            while current <= dt_end:
                date_str = current.strftime("%d/%m/%Y")
                await apply_jitter(JITTER_MIN_MS, JITTER_MAX_MS)
                day_ids = await self.get_editions_by_date(date_str)
                if day_ids:
                    ids.extend(day_ids)
                current += timedelta(days=1)

            return sorted(list(set(ids)))
        except Exception as e:
            logger.error(f"Erro ao buscar edições por período ({start_date} - {end_date}): {e}")
            return []

    async def get_edition_metadata_html(self, edicao_id: str) -> Optional[str]:
        """
        Obtém o HTML da página da edição diretamente via HTTPX.
        Elimina a necessidade e a lentidão do Chromium/Playwright.
        """
        url = f"/ver-html/{edicao_id}/"
        async with self.semaphore:
            await apply_jitter(JITTER_MIN_MS, JITTER_MAX_MS)
            try:
                response = await self.http_client.get(url)
                if response.status_code == 200:
                    return response.text
                return None
            except Exception as e:
                logger.warning(f"Não foi possível obter HTML de metadados para ID {edicao_id}: {e}")
                return None

    async def fetch_content(self, identificador: str) -> DownloadedDocument:
        """
        Baixa o conteúdo de uma matéria (HTML ou PDF binário).
        Controlado via semáforo, jitter e retentativas com backoff exponencial.
        Retorna DownloadedDocument com suporte a desempacotamento (content, content_type).
        """
        url = f"/apifront/portal/edicoes/publicacoes_ver_conteudo/{identificador}"
        async with self.semaphore:
            for attempt in range(3):
                await apply_jitter(JITTER_MIN_MS, JITTER_MAX_MS)
                try:
                    response = await self.http_client.get(url)
                    response.raise_for_status()

                    raw_bytes = response.content
                    content_type = response.headers.get("Content-Type", "")
                    # Detecção robusta: checa MIME type ou magic bytes de PDF (%PDF)
                    is_pdf = "application/pdf" in content_type or raw_bytes.startswith(b"%PDF")

                    return DownloadedDocument(
                        content=raw_bytes,
                        content_type=content_type,
                        is_pdf=is_pdf,
                    )
                except Exception as e:
                    wait_time = 2 ** attempt
                    logger.warning(
                        f"Tentativa {attempt + 1}/3 falhou para ato {identificador}: {e}. "
                        f"Aguardando {wait_time}s..."
                    )
                    await asyncio.sleep(wait_time)

            logger.error(f"Esgotadas as 3 tentativas para baixar ato {identificador}.")
            return DownloadedDocument(content=b"", content_type="", is_pdf=False)
