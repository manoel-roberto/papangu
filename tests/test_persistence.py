import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.models import (
    AtoOficial,
    MetadadosEdicao,
    EntidadesExtraidas,
    DadosEstruturadosLLM,
    AtoChunk,
    SimilarChunk,
    SystemSettings,
)
from src.persistence.pg_repository import PostgresRepository


@pytest.fixture
def mock_repo():
    """Cria um PostgresRepository com pool e conexões mockadas para testes assíncronos sem DB real."""
    repo = PostgresRepository(dsn="postgresql:///mock_db")
    mock_pool = MagicMock()
    mock_conn = AsyncMock()

    # Context manager para pool.acquire()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value.__aexit__.return_value = None

    repo.pool = mock_pool
    return repo, mock_conn


@pytest.mark.asyncio
async def test_setup_schema_creates_tables_and_indexes(mock_repo):
    """Testa se setup_schema executa a criação de tabelas, pgvector e índices de performance."""
    repo, mock_conn = mock_repo
    mock_conn.fetchval.return_value = 1  # count de system_settings

    await repo.setup_schema()

    # Verifica se os comandos executados incluem criação de índices e tabelas
    executed_statements = [call.args[0] for call in mock_conn.execute.call_args_list]
    joined_sql = " ".join(executed_statements)

    assert "CREATE EXTENSION IF NOT EXISTS vector" in joined_sql
    assert "idx_atos_chunks_ato_id" in joined_sql
    assert "idx_atos_identificador" in joined_sql
    assert "idx_atos_data_pub" in joined_sql
    assert "entidades JSONB" in joined_sql
    assert "dados_estruturados JSONB" in joined_sql


@pytest.mark.asyncio
async def test_insert_ato_single_query_upsert(mock_repo):
    """Testa se insert_ato executa uma única query retornando o ID do ato com dados JSONB."""
    repo, mock_conn = mock_repo
    mock_conn.fetchval.return_value = 42  # ID retornado pelo RETURNING id

    ato = AtoOficial(
        identificador="ato-teste-101",
        secretaria="Saúde",
        orgao="Gabinete",
        titulo="Portaria Teste",
        texto_integral="Texto do ato",
        texto_limpo="Texto limpo",
        metadados=MetadadosEdicao(numero=100, data_publicacao=date(2026, 9, 18)),
        entidades=EntidadesExtraidas(pessoas=["Dr. Silva"]),
        dados_estruturados=DadosEstruturadosLLM(resumo="Resumo gerado"),
    )

    ato_id = await repo.insert_ato(ato)

    assert ato_id == 42
    assert mock_conn.fetchval.call_count == 1

    # Verifica os argumentos passados para a query
    call_args = mock_conn.fetchval.call_args[0]
    query = call_args[0]
    assert "ON CONFLICT (identificador) DO UPDATE" in query
    assert "RETURNING id" in query
    # Verifica serialização JSONB
    assert '{"pessoas":["Dr. Silva"],"organizacoes":[],"valores":[]}' in call_args[10]
    assert "Resumo gerado" in call_args[11]


@pytest.mark.asyncio
async def test_get_chunks_without_vectors_returns_typed_models(mock_repo):
    """Testa se get_chunks_without_vectors retorna instâncias de AtoChunk tipadas."""
    repo, mock_conn = mock_repo
    mock_conn.fetch.return_value = [
        {
            "id": 1,
            "ato_id": 10,
            "texto_chunk": "Texto do primeiro chunk",
            "criado_em": None,
            "data_publicacao": date(2026, 9, 18),
            "identificador": "ato-10",
            "titulo": "Portaria 10",
        }
    ]

    chunks = await repo.get_chunks_without_vectors(limit=10)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert isinstance(chunk, AtoChunk)
    assert chunk.id == 1
    assert chunk.ato_id == 10
    assert chunk.texto_chunk == "Texto do primeiro chunk"
    assert chunk.identificador == "ato-10"
    # Compatibilidade de acesso por dicionário
    assert chunk["texto_chunk"] == "Texto do primeiro chunk"


@pytest.mark.asyncio
async def test_search_similar_chunks_returns_typed_models(mock_repo):
    """Testa se search_similar_chunks mapeia os registros para instâncias SimilarChunk."""
    repo, mock_conn = mock_repo
    mock_conn.fetch.return_value = [
        {
            "id": 50,
            "texto_chunk": "Trecho relevante sobre vacinação",
            "similarity": 0.88,
            "identificador": "ato-vacina-1",
            "titulo": "Campanha de Vacinação",
            "secretaria": "SESAB",
            "orgao": "Vigilância em Saúde",
            "data_publicacao": date(2026, 9, 18),
        }
    ]

    results = await repo.search_similar_chunks(query_vector=[0.1] * 768, limit=5)

    assert len(results) == 1
    res = results[0]
    assert isinstance(res, SimilarChunk)
    assert res.chunk_id == 50
    assert res.similaridade == 0.88
    assert res.ato_secretaria == "SESAB"
    assert res["ato_identificador"] == "ato-vacina-1"


@pytest.mark.asyncio
async def test_get_and_update_settings(mock_repo):
    """Testa recuperação e atualização tipada das configurações operacionais."""
    repo, mock_conn = mock_repo
    mock_conn.fetchrow.return_value = {
        "polling_interval_minutes": 30,
        "monitoramento_ativo": False,
    }

    settings = await repo.get_settings()
    assert isinstance(settings, SystemSettings)
    assert settings.polling_interval_minutes == 30
    assert settings.monitoramento_ativo is False

    # Atualização
    mock_conn.execute.return_value = "UPDATE 1"
    updated = await repo.update_settings(polling=15, ativo=True)
    assert updated is True
    assert mock_conn.execute.call_count == 1
