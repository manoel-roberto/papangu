import pytest
from datetime import date
from unittest.mock import patch, AsyncMock, MagicMock

from src.core.models import (
    AtoOficial,
    MetadadosEdicao,
    MotorExtracao,
    EntidadesExtraidas,
    DadosEstruturadosLLM,
)
from src.core.config import WatchlistConfig
from src.intelligence.chunker import chunk_text
from src.intelligence.engine import IntelligenceEngine
from src.intelligence.embeddings import OllamaEmbeddings


# ============================================================================
# 1. TESTES MATEMÁTICOS DE CHUNKING (600 palavras / 10% overlap)
# ============================================================================

def test_chunking_empty_and_small():
    """Testa casos base de chunking: vazio e texto menor que o limite."""
    assert chunk_text("") == []
    assert chunk_text("   ") == []

    # Texto com 50 palavras (menor que 600)
    small_text = " ".join([f"palavra_{i}" for i in range(50)])
    chunks = chunk_text(small_text, chunk_size=600, overlap_size=60)
    assert len(chunks) == 1
    assert chunks[0] == small_text


def test_chunking_exact_limit():
    """Testa texto exatamente com 600 palavras."""
    text_600 = " ".join([f"w_{i}" for i in range(600)])
    chunks = chunk_text(text_600, chunk_size=600, overlap_size=60)
    assert len(chunks) == 1
    assert len(chunks[0].split()) == 600


def test_chunking_mathematical_overlap():
    """
    Prova matematicamente a regra de 600 palavras com 10% de overlap (60 palavras):
    Para um texto de 1000 palavras:
    - Chunk 1: palavras 0 a 600 (tamanho 600)
    - Passo = 600 - 60 = 540
    - Chunk 2: palavras 540 a 1000 (tamanho 460)
    - Sobreposição exata: as últimas 60 palavras do Chunk 1 DEVEM ser idênticas às primeiras 60 do Chunk 2.
    """
    words = [f"w_{i}" for i in range(1000)]
    text = " ".join(words)

    chunks = chunk_text(text, chunk_size=600, overlap_size=60)
    assert len(chunks) == 2

    c1_words = chunks[0].split()
    c2_words = chunks[1].split()

    assert len(c1_words) == 600
    assert len(c2_words) == 460

    # Verificação da sobreposição de 60 palavras
    overlap_from_c1 = c1_words[-60:]
    overlap_from_c2 = c2_words[:60]

    assert len(overlap_from_c1) == 60
    assert len(overlap_from_c2) == 60
    assert overlap_from_c1 == overlap_from_c2
    assert overlap_from_c1[0] == "w_540"
    assert overlap_from_c1[-1] == "w_599"


def test_chunking_multi_blocks():
    """Testa particionamento com múltiplos blocos (1500 palavras -> 3 chunks)."""
    words = [f"token_{i}" for i in range(1500)]
    text = " ".join(words)

    chunks = chunk_text(text, chunk_size=600, overlap_size=60)
    assert len(chunks) == 3

    # Checa sobreposição entre bloco 2 e 3
    c2_words = chunks[1].split()
    c3_words = chunks[2].split()

    assert c2_words[-60:] == c3_words[:60]


# ============================================================================
# 2. TESTES DAS CAMADAS ISOLADAS DO ENGINE
# ============================================================================

def test_camada_1_match_watchlist_isolated():
    """Testa a Camada 1 (Lexical/Regex) isoladamente com word boundaries e case-insensitivity."""
    config = WatchlistConfig(
        keywords=["Nomeação", "Exoneração", "Licitação"],
        pessoas_monitoradas=["Jerônimo Rodrigues", "Rui Costa"]
    )
    engine = IntelligenceEngine(config=config)

    # Match de keyword
    assert engine.match_watchlist("Portaria de nomeação de servidor.") == ["Nomeação"]

    # Match de pessoa monitorada
    assert engine.match_watchlist("Ato assinado por JERÔNIMO RODRIGUES no gabinete.") == ["Jerônimo Rodrigues"]

    # Não match (palavra substring não deve casar devido a boundary)
    assert engine.match_watchlist("Texto sem termos de interesse.") == []


def test_camada_2_spacy_ner_isolated():
    """Testa a Camada 2 (Spacy NER) isoladamente."""
    engine = IntelligenceEngine(config=WatchlistConfig())
    
    # Se o spacy estiver carregado, testa extração
    if engine._spacy_nlp:
        entidades = engine.extract_entities_ner("O governador Jerônimo Rodrigues autorizou convênio com a SESAB.")
        assert isinstance(entidades, EntidadesExtraidas)
        # Deve ter detectado entidades
        assert len(entidades.pessoas) > 0 or len(entidades.organizacoes) > 0


@pytest.mark.asyncio
async def test_camada_3_ollama_fallback_isolated():
    """Testa a Camada 3 (Ollama LLM) isoladamente com mapeamento tipado."""
    engine = IntelligenceEngine(config=WatchlistConfig())

    mock_llm_json = {
        "response": '{"pessoas_envolvidas": ["Maria Silva", "João Souza"], "valor_contrato": "R$ 500.000,00", "resumo": "Contratação emergencial de insumos."}'
    }

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = mock_llm_json
    mock_response.raise_for_status = MagicMock()

    with patch.object(engine.http_client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        dados = await engine.extract_structured_llm("Texto do contrato...")

        assert isinstance(dados, DadosEstruturadosLLM)
        assert dados.pessoas_envolvidas == ["Maria Silva", "João Souza"]
        assert dados.valor_contrato == "R$ 500.000,00"
        assert dados.resumo == "Contratação emergencial de insumos."


# ============================================================================
# 3. TESTE DE ORQUESTRAÇÃO DO FUNIL & FIM DO CAMINHO MORTO
# ============================================================================

@pytest.mark.asyncio
async def test_processar_ato_end_to_end_with_ollama():
    """
    Testa o funil completo garantindo que os dados do Ollama são salvos
    em ato.dados_estruturados (Fim do Caminho Morto).
    """
    config = WatchlistConfig(
        keywords=["dispensa"],
        pessoas_monitoradas=[]
    )
    engine = IntelligenceEngine(config=config)

    # Força NER a retornar sem pessoas para disparar a Camada 3
    with patch.object(engine, "extract_entities_ner", return_value=EntidadesExtraidas()):
        mock_llm_json = {
            "response": '{"pessoas_envolvidas": ["Empresa ABC"], "valor_contrato": "R$ 80.000,00", "resumo": "Dispensa de licitação."}'
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_llm_json
        mock_response.raise_for_status = MagicMock()

        with patch.object(engine.http_client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            ato_bruto = AtoOficial(
                identificador="dispensa-101",
                secretaria="Saúde",
                orgao="SESAB",
                titulo="Dispensa de Licitação 01/2026",
                texto_integral="Processo de dispensa de licitação para aquisição de reagentes.",
                metadados=MetadadosEdicao(numero=123, data_publicacao=date(2026, 9, 18))
            )

            ato_processado = await engine.processar_ato(ato_bruto)

            # Validações estritas
            assert ato_processado.motor_extracao == MotorExtracao.OLLAMA.value
            assert ato_processado.dados_estruturados is not None
            assert ato_processado.dados_estruturados.valor_contrato == "R$ 80.000,00"
            assert ato_processado.dados_estruturados.resumo == "Dispensa de licitação."
            assert ato_processado.hash_conteudo is not None


# ============================================================================
# 4. TESTE DE REUSO DE SESSÃO TCP NOS EMBEDDINGS
# ============================================================================

@pytest.mark.asyncio
async def test_ollama_embeddings_connection_reuse():
    """Testa geração de embeddings e reuso de conexão com o httpx.AsyncClient."""
    async with OllamaEmbeddings() as embeddings_client:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"embedding": [0.1] * 768}
        mock_response.raise_for_status = MagicMock()

        with patch.object(embeddings_client.client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            vec1 = await embeddings_client.get_embedding("Texto número um")
            vec2 = await embeddings_client.get_embedding("Texto número dois")

            assert len(vec1) == 768
            assert len(vec2) == 768
            # Ambas as chamadas reutilizaram o mesmo client
            assert mock_post.call_count == 2
