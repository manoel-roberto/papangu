import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from src.core.client import DOEBahiaClient

@pytest.mark.asyncio
async def test_fetch_content_success():
    """Testa se o client baixa conteúdo corretamente lidando com rate limit e httpx"""
    client = DOEBahiaClient()
    
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = b"PDF_BYTES"
        mock_get.return_value.headers = {"Content-Type": "application/pdf"}
        
        # Mudar a política do Jitter para não travar os testes unitários
        with patch("src.core.client.apply_jitter", new_callable=AsyncMock):
            content, ctype = await client.fetch_content("mock_123")
        
        assert content == b"PDF_BYTES"
        assert ctype == "application/pdf"
        
    await client.close()

@pytest.mark.asyncio
async def test_fetch_content_retry_on_500():
    """Testa se o Exponential Backoff funciona para erros 500 do servidor"""
    client = DOEBahiaClient()
    
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        # Retorna 500 na primeira vez, e 200 na segunda
        mock_response_500 = MagicMock()
        mock_response_500.status_code = 500
        mock_response_500.raise_for_status.side_effect = Exception("HTTP 500")
        
        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200
        mock_response_200.content = b"HTML_BYTES"
        mock_response_200.headers = {"Content-Type": "text/html"}
        
        mock_get.side_effect = [mock_response_500, mock_response_200]
        
        with patch("src.core.client.apply_jitter", new_callable=AsyncMock), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            content, ctype = await client.fetch_content("mock_456")
            
        assert content == b"HTML_BYTES"
        assert ctype == "text/html"
        assert mock_get.call_count == 2
        
    await client.close()

@pytest.mark.asyncio
async def test_get_editions_by_range():
    """Testa se a busca por intervalo itera dia a dia corretamente"""
    client = DOEBahiaClient()
    
    with patch.object(client, "get_editions_by_date", new_callable=AsyncMock) as mock_get_date, \
         patch("src.core.client.apply_jitter", new_callable=AsyncMock):
        
        mock_get_date.side_effect = [["id_1"], ["id_2"], []]
        
        edicoes = await client.get_editions_by_range("01/05/2026", "03/05/2026")
        
        assert edicoes == ["id_1", "id_2"]
        assert mock_get_date.call_count == 3
        mock_get_date.assert_any_call("01/05/2026")
        mock_get_date.assert_any_call("02/05/2026")
        mock_get_date.assert_any_call("03/05/2026")
        
    await client.close()
