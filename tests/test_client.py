import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from src.core.client import DOEBahiaClient
from src.core.models import DownloadedDocument


@pytest.mark.asyncio
async def test_fetch_content_success():
    """Testa se o client baixa conteúdo corretamente e retorna DownloadedDocument tipado."""
    async with DOEBahiaClient() as client:
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b"PDF_BYTES"
            mock_response.headers = {"Content-Type": "application/pdf"}
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            with patch("src.core.client.apply_jitter", new_callable=AsyncMock):
                doc = await client.fetch_content("mock_123")

            assert isinstance(doc, DownloadedDocument)
            assert doc.is_pdf is True
            assert doc.content == b"PDF_BYTES"

            # Compatibilidade retroativa de desempacotamento
            content, ctype = doc
            assert content == b"PDF_BYTES"
            assert ctype == "application/pdf"


@pytest.mark.asyncio
async def test_fetch_content_retry_on_500():
    """Testa se o Exponential Backoff funciona para erros do servidor."""
    async with DOEBahiaClient() as client:
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_response_500 = MagicMock()
            mock_response_500.status_code = 500
            mock_response_500.raise_for_status.side_effect = Exception("HTTP 500")

            mock_response_200 = MagicMock()
            mock_response_200.status_code = 200
            mock_response_200.content = b"HTML_BYTES"
            mock_response_200.headers = {"Content-Type": "text/html"}
            mock_response_200.raise_for_status = MagicMock()

            mock_get.side_effect = [mock_response_500, mock_response_200]

            with patch("src.core.client.apply_jitter", new_callable=AsyncMock), \
                 patch("asyncio.sleep", new_callable=AsyncMock):
                doc = await client.fetch_content("mock_456")

            assert doc.is_pdf is False
            assert doc.content == b"HTML_BYTES"
            assert doc.content_type == "text/html"
            assert mock_get.call_count == 2


@pytest.mark.asyncio
async def test_get_editions_by_range():
    """Testa se a busca por intervalo itera dia a dia corretamente."""
    async with DOEBahiaClient() as client:
        with patch.object(client, "get_editions_by_date", new_callable=AsyncMock) as mock_get_date, \
             patch("src.core.client.apply_jitter", new_callable=AsyncMock):

            mock_get_date.side_effect = [["id_1"], ["id_2"], []]

            edicoes = await client.get_editions_by_range("01/05/2026", "03/05/2026")

            assert edicoes == ["id_1", "id_2"]
            assert mock_get_date.call_count == 3
            mock_get_date.assert_any_call("01/05/2026")
            mock_get_date.assert_any_call("02/05/2026")
            mock_get_date.assert_any_call("03/05/2026")
