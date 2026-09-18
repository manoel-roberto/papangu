from datetime import datetime
import re
import logging
from typing import List, Union
from bs4 import BeautifulSoup

from src.core.models import MetadadosEdicao, AtoSumarioRef
from src.intelligence.cleaner import clean_text

logger = logging.getLogger("DOE_BA_Engine")


def parse_metadata(html_content: str) -> MetadadosEdicao:
    """
    Extrai o número da edição e a data de publicação a partir da tag div.edi-p-id-data.
    """
    if not html_content:
        return MetadadosEdicao(numero=0, data_publicacao=datetime.today().date())

    soup = BeautifulSoup(html_content, "lxml")
    div = soup.select_one("div.edi-p-id-data")

    texto_metadados = clean_text(div.text) if div else ""
    logger.debug(f"Texto base de metadados extraído: {texto_metadados}")

    numero_match = re.search(r"Edição\s*n?[º°]?\s*(\d+)", texto_metadados, re.IGNORECASE)
    data_match = re.search(r"(\d{2}/\d{2}/\d{4})", texto_metadados)

    numero = int(numero_match.group(1)) if numero_match else 0

    data_publicacao = datetime.today().date()
    if data_match:
        try:
            data_publicacao = datetime.strptime(data_match.group(1), "%d/%m/%Y").date()
        except ValueError:
            pass

    return MetadadosEdicao(numero=numero, data_publicacao=data_publicacao)


def parse_summary_tree(html_content: str) -> List[AtoSumarioRef]:
    """
    Varre a árvore de sumário (#tree) em busca de links com a classe .linkMateria.
    Retorna uma lista de referências canônicas tipadas (AtoSumarioRef) com identificador, título e hierarquia.
    """
    if not html_content:
        return []

    soup = BeautifulSoup(html_content, "lxml")
    tree = soup.select_one("#tree")

    if not tree:
        logger.warning("Elemento #tree não encontrado no HTML do sumário.")
        return []

    atos: List[AtoSumarioRef] = []
    links_materia = tree.select("a.linkMateria")

    for link in links_materia:
        identificador = link.get("identificador")
        titulo = clean_text(link.text)

        # Reconstrói a hierarquia administrativa (Secretaria / Órgão) subindo na árvore DOM
        hierarquia: List[str] = []
        parent = link.parent
        while parent and parent.name != "div" and parent.get("id") != "tree":
            folder_text = ""
            prev = parent.find_previous_sibling()
            if prev:
                folder_text = clean_text(prev.text)

            if folder_text and folder_text not in hierarquia:
                hierarquia.append(folder_text)

            parent = parent.parent

        if identificador:
            atos.append(
                AtoSumarioRef(
                    identificador=str(identificador),
                    titulo=titulo,
                    hierarquia=hierarquia[::-1],  # Inverte para manter ordem topo -> base
                )
            )

    logger.info(f"Total de {len(atos)} matérias identificadas no sumário.")
    return atos


def extract_html_text(html_content: Union[bytes, str]) -> str:
    """
    Extrai texto legível de um fragmento HTML e aplica sanitização unificada.
    """
    if not html_content:
        return ""

    soup = BeautifulSoup(html_content, "lxml")
    return clean_text(soup.get_text(separator=" "))
