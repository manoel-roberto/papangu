import io
import logging
from typing import Optional
import pdfplumber

from src.intelligence.cleaner import clean_text

logger = logging.getLogger("DOE_BA_Engine")


def extract_pdf_text(pdf_bytes: Optional[bytes]) -> str:
    """
    Extrai texto de um documento PDF binário diretamente na memória via io.BytesIO.
    Elimina I/O de disco, gravação de arquivos temporários e descritores órfãos.
    Retorna o texto normalizado através do sanitizador unificado.
    """
    if not pdf_bytes:
        return ""

    logger.debug("Extraindo texto de PDF em memória com pdfplumber")
    try:
        text_blocks = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_blocks.append(page_text)

        full_text = "\n".join(text_blocks)
        return clean_text(full_text)
    except Exception as e:
        logger.error(f"Erro ao extrair texto do PDF em memória: {e}")
        return ""
