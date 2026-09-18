from datetime import date
from unittest.mock import patch, MagicMock

from src.parsers.html_parser import parse_metadata, parse_summary_tree, extract_html_text
from src.parsers.pdf_parser import extract_pdf_text


def test_html_metadata_extraction():
    """Testa se a função pura parse_metadata extrai número e data de publicação."""
    html_mock = "<html><body><div class='edi-p-id-data'>Edição n° 1234 - 10/05/2026</div></body></html>"
    metadados = parse_metadata(html_mock)

    assert metadados.numero == 1234
    assert metadados.data_publicacao == date(2026, 5, 10)


def test_html_metadata_empty():
    """Testa comportamento seguro de parse_metadata com entrada vazia."""
    metadados = parse_metadata("")
    assert metadados.numero == 0


def test_html_summary_tree_parsing():
    """Testa se parse_summary_tree extrai nós com hierarquia administrativa."""
    html_mock = """
    <div id="tree">
        <ul>
            <span>Secretaria da Fazenda</span>
            <li>
                <span>Gabinete do Secretário</span>
                <a class="linkMateria" identificador="mat-101">Portaria SEFAZ 01</a>
            </li>
        </ul>
    </div>
    """
    atos = parse_summary_tree(html_mock)
    assert len(atos) == 1
    assert atos[0].identificador == "mat-101"
    assert atos[0].titulo == "Portaria SEFAZ 01"
    # Acesso via índice para retrocompatibilidade
    assert atos[0]["identificador"] == "mat-101"


def test_html_text_extraction():
    """Testa se a extração de texto do HTML remove tags e ruídos adequadamente."""
    html_mock = b"<html><body><p>   Texto com    multiplos espacos  \n</p><br/><div>Novo paragrafo</div></body></html>"
    text = extract_html_text(html_mock)

    assert "Texto com multiplos espacos Novo paragrafo" in text


def test_pdf_extraction_empty():
    """Testa se a extração de PDF lida corretamente com bytes vazios."""
    text = extract_pdf_text(b"")
    assert text == ""


def test_pdf_extraction_in_memory():
    """Testa se extract_pdf_text processa páginas via pdfplumber em memória sem I/O de disco."""
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "Texto extraido do PDF oficial\nPágina 1 de 5"

    mock_pdf = MagicMock()
    mock_pdf.pages = [mock_page]
    mock_pdf.__enter__.return_value = mock_pdf

    with patch("pdfplumber.open", return_value=mock_pdf) as mock_open:
        text = extract_pdf_text(b"%PDF-1.4 mock content")
        assert "Texto extraido do PDF oficial" in text
        # Verifica que o marcador de página foi removido pelo cleaner unificado
        assert "Página 1 de 5" not in text
        mock_open.assert_called_once()
