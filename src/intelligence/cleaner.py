import re
from typing import Optional


def clean_text(text: Optional[str]) -> str:
    """
    Higieniza e normaliza textos extraídos de documentos do Diário Oficial (HTML e PDF).

    Ações de limpeza:
    - Normaliza quebras de linha e caracteres nulos.
    - Remove cabeçalhos repetitivos do DOE-BA (ex: 'Diário Oficial do Estado da Bahia...').
    - Remove marcadores de rodapé e paginação (ex: 'Página 1 de 10', números de página isolados).
    - Colapsa múltiplos espaços em branco, tabulações e quebras excessivas em um único espaço.
    """
    if not text:
        return ""

    # Remove caracteres nulos residuais de decodificação binária de PDF
    sanitized = text.replace("\x00", "")

    # Normaliza quebras de linha de diferentes SOs
    sanitized = sanitized.replace("\r\n", "\n").replace("\r", "\n")

    # Remove cabeçalhos de página típicos do DOE-BA
    sanitized = re.sub(
        r"Di[áa]rio\s+Oficial.*?Estado\s+da\s+Bahia[^\n]*\n?",
        "",
        sanitized,
        flags=re.IGNORECASE,
    )

    # Remove padrões explícitos de paginação ('Página X de Y')
    sanitized = re.sub(
        r"P[áa]gina\s+\d+\s+de\s+\d+",
        "",
        sanitized,
        flags=re.IGNORECASE,
    )

    # Remove linhas contendo apenas numeração de página isolada (ex: " 12 ", "- 3 -")
    sanitized = re.sub(
        r"^\s*-?\s*\d+\s*-?\s*$",
        "",
        sanitized,
        flags=re.MULTILINE,
    )

    # Consolida todos os espaços e quebras consecutivas em um único espaço
    sanitized = re.sub(r"\s+", " ", sanitized)

    return sanitized.strip()
