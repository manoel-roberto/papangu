import logging
from typing import Callable, Awaitable, List, Optional

from src.core.client import DOEBahiaClient
from src.core.models import (
    AtoOficial,
    AtoSumarioRef,
    MetadadosEdicao,
    MotorExtracao,
)
from src.parsers.html_parser import parse_metadata, parse_summary_tree, extract_html_text
from src.parsers.pdf_parser import extract_pdf_text
from src.intelligence.engine import IntelligenceEngine
from src.intelligence.chunker import chunk_text
from src.intelligence.embeddings import OllamaEmbeddings
from src.persistence.pg_repository import PostgresRepository

logger = logging.getLogger("DOE_BA_Engine")

NotifyCallbackType = Callable[[AtoOficial], Awaitable[None]]


async def process_ato_pipeline(
    client: DOEBahiaClient,
    ato_ref: AtoSumarioRef,
    metadados: MetadadosEdicao,
    engine: IntelligenceEngine,
    db_repo: PostgresRepository,
    embeddings_client: Optional[OllamaEmbeddings] = None,
    skip_if_exists: bool = True,
    notify_callback: Optional[NotifyCallbackType] = None,
) -> Optional[AtoOficial]:
    """
    Executa o pipeline linear e unificado para um único ato oficial:
    Extração -> Sanitização -> Classificação (Funil) -> Salvamento no BD -> Chunking -> Vetorização Imediata.

    Garante que todo ato, independentemente de vir do Worker, CLI ou API (Backfill),
    seja processado e vetorizado imediatamente sob as mesmas regras canônicas.
    """
    identificador = ato_ref.identificador

    # 1. Checagem de existência prévia para evitar download redundante
    if skip_if_exists:
        exists = await db_repo.get_ato_id_by_identificador(identificador)
        if exists:
            logger.debug(f"Ato {identificador} já existe no banco. Ignorando download.")
            return None

    # 2. Download resiliente do conteúdo bruto (HTML ou PDF)
    doc = await client.fetch_content(identificador)
    if not doc or not doc.content:
        logger.warning(f"Não foi possível obter conteúdo para o ato {identificador}.")
        return None

    # 3. Extração pura de texto (em memória, sem gravação em disco)
    try:
        if doc.is_pdf:
            texto_integral = extract_pdf_text(doc.content)
        else:
            texto_integral = extract_html_text(doc.content)
    except Exception as e:
        logger.error(f"Erro ao extrair texto do ato {identificador}: {e}")
        return None

    if not texto_integral or not texto_integral.strip():
        logger.warning(f"Texto vazio extraído do ato {identificador}.")
        return None

    # 4. Instanciação do modelo canônico Pydantic
    secretaria = ato_ref.hierarquia[0] if ato_ref.hierarquia else "Desconhecida"
    orgao = ato_ref.hierarquia[-1] if ato_ref.hierarquia else "Desconhecido"

    novo_ato = AtoOficial(
        identificador=identificador,
        secretaria=secretaria,
        orgao=orgao,
        titulo=ato_ref.titulo,
        texto_integral=texto_integral,
        metadados=metadados,
    )

    # 5. Funil Modular de Inteligência (Regex -> Spacy -> Ollama)
    ato_processado = await engine.processar_ato(novo_ato)

    # 6. Persistência atômica com Single-Query UPSERT e JSONB
    ato_id = await db_repo.insert_ato(ato_processado)
    if not ato_id:
        logger.error(f"Falha ao persistir ato {identificador} no banco de dados.")
        return None

    # 7. Disparo de Notificação se houve match de inteligência
    if notify_callback and ato_processado.motor_extracao != MotorExtracao.NENHUM.value:
        try:
            await notify_callback(ato_processado)
        except Exception as e:
            logger.error(f"Erro ao disparar callback de notificação para ato {identificador}: {e}")

    # 8. Chunking e Vetorização Imediata (Elimina o atraso do polling)
    if ato_processado.texto_limpo:
        chunks = chunk_text(ato_processado.texto_limpo)
        for c_text in chunks:
            vetor: Optional[List[float]] = None
            if embeddings_client:
                try:
                    vetor = await embeddings_client.get_embedding(c_text)
                except Exception as e:
                    logger.error(f"Erro ao gerar embedding para chunk do ato {identificador}: {e}")

            await db_repo.insert_chunk(ato_id, c_text, embedding=vetor)

        logger.info(
            f"Ato {identificador} finalizado: {len(chunks)} chunks gerados e vetorizados imediatamente."
        )

    return ato_processado


async def process_edition_pipeline(
    client: DOEBahiaClient,
    edicao_id: str,
    engine: IntelligenceEngine,
    db_repo: PostgresRepository,
    embeddings_client: Optional[OllamaEmbeddings] = None,
    skip_if_exists: bool = True,
    notify_callback: Optional[NotifyCallbackType] = None,
) -> List[AtoOficial]:
    """
    Orquestra a ingestão completa de uma edição do Diário Oficial:
    Obtém sumário -> Parseia metadados e árvore -> Processa matérias via process_ato_pipeline.
    """
    logger.info(f"Iniciando pipeline de processamento para a edição ID {edicao_id}")

    summary_html = await client.get_summary_html(edicao_id)
    if not summary_html:
        logger.error(f"Não foi possível recuperar o sumário da edição {edicao_id}.")
        return []

    metadados = parse_metadata(summary_html)
    atos_refs = parse_summary_tree(summary_html)

    if not atos_refs:
        logger.warning(f"Nenhuma matéria encontrada no sumário da edição {edicao_id}.")
        return []

    logger.info(
        f"Edição {metadados.numero} ({metadados.data_publicacao}): {len(atos_refs)} matérias identificadas."
    )

    processados: List[AtoOficial] = []
    for ref in atos_refs:
        ato = await process_ato_pipeline(
            client=client,
            ato_ref=ref,
            metadados=metadados,
            engine=engine,
            db_repo=db_repo,
            embeddings_client=embeddings_client,
            skip_if_exists=skip_if_exists,
            notify_callback=notify_callback,
        )
        if ato:
            processados.append(ato)

    logger.info(
        f"Edição ID {edicao_id} concluída. Total de matérias novas processadas: {len(processados)}/{len(atos_refs)}"
    )
    return processados
