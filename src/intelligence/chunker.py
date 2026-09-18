import re
from typing import List


def chunk_text(text: str, chunk_size: int = 600, overlap_size: int = 60) -> List[str]:
    """
    Divide o texto normalizado em fragmentos (chunks) usando particionamento baseado em palavras,
    garantindo sobreposição (overlap) para preservação de contexto semântico no RAG.

    Parâmetros:
    - text: Texto normalizado a ser particionado.
    - chunk_size: Quantidade máxima de palavras por chunk (padrão: 600 palavras, ~800 tokens).
    - overlap_size: Quantidade de palavras sobrepostas entre blocos adjacentes (padrão: 60 palavras, 10%).

    Garantias:
    - Textos vazios retornam lista vazia.
    - Textos menores ou iguais a chunk_size geram exatamente 1 chunk sem truncamento.
    - A sobreposição entre chunks consecutivos i e i+1 contém exatamente as últimas overlap_size
      palavras do chunk i.
    """
    if not text or not text.strip():
        return []

    words = re.findall(r"\S+", text)
    total_words = len(words)

    if total_words == 0:
        return []

    if total_words <= chunk_size:
        return [" ".join(words)]

    # Garante que o passo de avanço seja sempre positivo
    step = max(1, chunk_size - overlap_size)
    chunks: List[str] = []

    i = 0
    while i < total_words:
        end_idx = min(i + chunk_size, total_words)
        chunk = " ".join(words[i:end_idx])
        chunks.append(chunk)

        # Se alcançou o final do texto, encerra
        if end_idx >= total_words:
            break

        i += step

    return chunks
