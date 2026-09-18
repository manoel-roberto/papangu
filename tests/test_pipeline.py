import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.models import (
    AtoOficial,
    AtoSumarioRef,
    MetadadosEdicao,
    MotorExtracao,
    DownloadedDocument,
)
from src.core.pipeline import process_ato_pipeline, process_edition_pipeline


@pytest.mark.asyncio
async def test_process_ato_pipeline_linear_execution():
    """
    Testa a execução linear completa do pipeline unificado:
    Extração -> Sanitização -> Classificação -> Inserção BD -> Chunking -> Vetorização Imediata.
    """
    mock_client = AsyncMock()
    mock_engine = AsyncMock()
    mock_db = AsyncMock()
    mock_embeddings = AsyncMock()
    mock_notify = AsyncMock()

    # 1. Simula ato inexistente no banco
    mock_db.get_ato_id_by_identificador.return_value = None

    # 2. Simula download de documento HTML
    mock_client.fetch_content.return_value = DownloadedDocument(
        content=b"<html><body><p>Texto oficial da portaria de designacao.</p></body></html>",
        content_type="text/html",
        is_pdf=False,
    )

    # 3. Simula retorno da inteligência (match via REGEX)
    ato_retorno_engine = AtoOficial(
        identificador="ato-2026-001",
        secretaria="Secretaria de Saude",
        orgao="Gabinete",
        titulo="Portaria 001/2026",
        texto_integral="Texto oficial da portaria de designacao.",
        texto_limpo="Texto oficial da portaria de designacao.",
        motor_extracao=MotorExtracao.REGEX.value,
        metadados=MetadadosEdicao(numero=500, data_publicacao=date(2026, 9, 18)),
    )
    mock_engine.processar_ato.return_value = ato_retorno_engine

    # 4. Simula inserção única no banco retornando ID
    mock_db.insert_ato.return_value = 100

    # 5. Simula vetorização imediata do chunk
    mock_embeddings.get_embedding.return_value = [0.1] * 768

    # Executa o pipeline
    ato_ref = AtoSumarioRef(
        identificador="ato-2026-001",
        titulo="Portaria 001/2026",
        hierarquia=["Secretaria de Saude", "Gabinete"],
    )
    metadados = MetadadosEdicao(numero=500, data_publicacao=date(2026, 9, 18))

    resultado = await process_ato_pipeline(
        client=mock_client,
        ato_ref=ato_ref,
        metadados=metadados,
        engine=mock_engine,
        db_repo=mock_db,
        embeddings_client=mock_embeddings,
        skip_if_exists=True,
        notify_callback=mock_notify,
    )

    assert resultado is not None
    assert resultado.identificador == "ato-2026-001"

    # Verificações de chamada estrita
    mock_client.fetch_content.assert_called_once_with("ato-2026-001")
    mock_engine.processar_ato.assert_called_once()
    mock_db.insert_ato.assert_called_once()
    mock_notify.assert_called_once_with(ato_retorno_engine)
    mock_embeddings.get_embedding.assert_called_once()
    mock_db.insert_chunk.assert_called_once()


@pytest.mark.asyncio
async def test_process_ato_pipeline_skips_existing():
    """Testa se o pipeline ignora atos já existentes quando skip_if_exists=True."""
    mock_client = AsyncMock()
    mock_engine = AsyncMock()
    mock_db = AsyncMock()

    # Ato já existe no banco
    mock_db.get_ato_id_by_identificador.return_value = 42

    ato_ref = AtoSumarioRef(
        identificador="ato-existente",
        titulo="Titulo",
        hierarquia=[],
    )
    metadados = MetadadosEdicao(numero=1, data_publicacao=date(2026, 9, 18))

    resultado = await process_ato_pipeline(
        client=mock_client,
        ato_ref=ato_ref,
        metadados=metadados,
        engine=mock_engine,
        db_repo=mock_db,
        skip_if_exists=True,
    )

    assert resultado is None
    # Não deve tentar baixar se já existe
    mock_client.fetch_content.assert_not_called()


@pytest.mark.asyncio
async def test_process_edition_pipeline():
    """Testa a orquestração completa de uma edição através do sumário."""
    mock_client = AsyncMock()
    mock_engine = AsyncMock()
    mock_db = AsyncMock()

    # HTML de sumário mockado com 1 matéria
    mock_summary_html = """
    <html>
        <body>
            <div class="edi-p-id-data">Edição nº 2000 - 18/09/2026</div>
            <div id="tree">
                <a class="linkMateria" identificador="mat-01">Portaria 01</a>
            </div>
        </body>
    </html>
    """
    mock_client.get_summary_html.return_value = mock_summary_html

    with patch("src.core.pipeline.process_ato_pipeline", new_callable=AsyncMock) as mock_process_ato:
        mock_process_ato.return_value = MagicMock(spec=AtoOficial)

        resultados = await process_edition_pipeline(
            client=mock_client,
            edicao_id="12345",
            engine=mock_engine,
            db_repo=mock_db,
        )

        assert len(resultados) == 1
        mock_client.get_summary_html.assert_called_once_with("12345")
        mock_process_ato.assert_called_once()
