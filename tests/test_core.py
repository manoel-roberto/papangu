from datetime import date
from src.core.models import (
    MetadadosEdicao,
    AtoOficial,
    MotorExtracao,
    DownloadedDocument,
    AtoSumarioRef,
    EntidadesExtraidas,
    DadosEstruturadosLLM,
    AtoChunk,
    SimilarChunk,
    SearchResult,
    WatchlistAlert,
    WatchlistMatchItem,
    SystemSettings,
)
from src.core.config import (
    load_watchlist,
    WatchlistConfig,
    SEMAPHORE_LIMIT,
    JITTER_MIN_MS,
    JITTER_MAX_MS,
)


def test_downloaded_document_unpacking():
    """Testa se DownloadedDocument suporta desempacotamento e acesso por atributos."""
    doc = DownloadedDocument(
        content=b"<html>Teste</html>",
        content_type="text/html",
        is_pdf=False,
    )
    assert bool(doc) is True
    assert doc.is_pdf is False

    # Desempacotamento estilo tupla (compatibilidade com código existente)
    content, ctype = doc
    assert content == b"<html>Teste</html>"
    assert ctype == "text/html"


def test_downloaded_document_empty():
    """Testa comportamento de documento vazio."""
    doc = DownloadedDocument()
    assert bool(doc) is False
    content, ctype = doc
    assert content == b""
    assert ctype == "text/html"


def test_ato_sumario_ref_dict_access():
    """Testa se AtoSumarioRef suporta acesso indexado como dicionário."""
    ref = AtoSumarioRef(
        identificador="12345",
        titulo="Nomeação de Diretor",
        hierarquia=["Secretaria de Saúde", "SESAB"],
    )
    assert ref["identificador"] == "12345"
    assert ref["titulo"] == "Nomeação de Diretor"
    assert ref["hierarquia"] == ["Secretaria de Saúde", "SESAB"]


def test_ato_oficial_canonical_model():
    """Testa a integridade do modelo canônico AtoOficial com todos os sub-modelos."""
    metadados = MetadadosEdicao(numero=2000, data_publicacao=date(2026, 9, 18))
    entidades = EntidadesExtraidas(
        pessoas=["Fulano de Tal"],
        organizacoes=["SESAB"],
        valores=["R$ 150.000,00"],
    )
    dados_llm = DadosEstruturadosLLM(
        pessoas_envolvidas=["Fulano de Tal"],
        valor_contrato="R$ 150.000,00",
        resumo="Contratação de serviços de saúde.",
    )

    ato = AtoOficial(
        identificador="ato-999",
        secretaria="Saúde",
        orgao="Gabinete",
        titulo="Portaria 123",
        texto_integral="Texto do ato...",
        texto_limpo="Texto do ato normalizado",
        motor_extracao=MotorExtracao.SPACY.value,
        metadados=metadados,
        entidades=entidades,
        dados_estruturados=dados_llm,
    )

    assert ato.identificador == "ato-999"
    assert ato.metadados.numero == 2000
    assert ato.entidades.pessoas == ["Fulano de Tal"]
    assert ato.dados_estruturados.valor_contrato == "R$ 150.000,00"


def test_config_defaults_and_watchlist():
    """Testa os padrões de configuração e carregamento resiliente da watchlist."""
    assert SEMAPHORE_LIMIT == 8
    assert JITTER_MIN_MS == 200
    assert JITTER_MAX_MS == 500

    # Carregar arquivo inexistente deve retornar lista vazia sem explodir
    wl = load_watchlist("caminho_inexistente_123.yaml")
    assert isinstance(wl, WatchlistConfig)
    assert wl.keywords == []
    assert wl.pessoas_monitoradas == []
