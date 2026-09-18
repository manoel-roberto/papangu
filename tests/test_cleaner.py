from src.intelligence.cleaner import clean_text


def test_clean_text_removes_doe_headers():
    """Testa remoção de cabeçalhos institucionais do Diário Oficial."""
    text = (
        "Diário Oficial do Estado da Bahia - 18/09/2026\n"
        "PORTARIA Nº 500/2026. O Secretário de Administração resolve designar..."
    )
    cleaned = clean_text(text)
    assert "Diário Oficial do Estado da Bahia" not in cleaned
    assert "PORTARIA Nº 500/2026" in cleaned


def test_clean_text_removes_pagination():
    """Testa remoção de paginação 'Página X de Y' e números isolados."""
    text = (
        "Texto inicial do ato administrativo.\n"
        "Página 3 de 12\n"
        "Continuação do ato administrativo na próxima página.\n"
        " 12 \n"
        "Finalização do ato."
    )
    cleaned = clean_text(text)
    assert "Página 3 de 12" not in cleaned
    assert " 12 " not in cleaned
    assert "Texto inicial do ato administrativo." in cleaned
    assert "Finalização do ato." in cleaned


def test_clean_text_normalizes_whitespace():
    """Testa normalização de múltiplos espaços, quebras de linha e tabulações."""
    text = "   Parágrafo     com \t muitos \n\n\n espaços    desnecessários.   "
    cleaned = clean_text(text)
    assert cleaned == "Parágrafo com muitos espaços desnecessários."


def test_clean_text_handles_null_bytes_and_none():
    """Testa segurança contra bytes nulos e valores None/vazios."""
    assert clean_text(None) == ""
    assert clean_text("") == ""
    assert clean_text("Texto com byte nulo: \x00 limpo.") == "Texto com byte nulo: limpo."
