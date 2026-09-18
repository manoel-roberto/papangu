import asyncio
import logging
from datetime import datetime

from src.core.client import DOEBahiaClient
from src.core.config import POSTGRES_DSN, load_watchlist
from src.core.models import AtoOficial
from src.core.pipeline import process_edition_pipeline
from src.persistence.pg_repository import PostgresRepository
from src.intelligence.engine import IntelligenceEngine
from src.intelligence.embeddings import OllamaEmbeddings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("DOE_Worker")


async def notify_match(ato: AtoOficial) -> None:
    """
    Dispara notificações quando uma matéria dá match com a inteligência/watchlist.
    Emite logs estruturados e está preparado para webhooks (Telegram/Slack).
    """
    emoji = "🚨" if ato.motor_extracao == "REGEX" else "🧠"
    resumo_texto = ato.texto_limpo[:200] if ato.texto_limpo else ""
    message = (
        f"\n{emoji} MATCH DETECTADO: {ato.titulo}\n"
        f"ID: {ato.identificador}\n"
        f"Motor: {ato.motor_extracao}\n"
        f"Link: https://dool.egba.ba.gov.br/apifront/portal/edicoes/publicacoes_ver_conteudo/{ato.identificador}\n"
        f"Snippet: {resumo_texto}..."
    )
    logger.critical(message)


async def drain_pending_vectors(
    db_repo: PostgresRepository,
    embeddings_client: OllamaEmbeddings,
    batch_size: int = 100,
) -> None:
    """
    Sweeper de segurança: processa eventuais chunks que ficaram sem vetor
    (ex: indisponibilidade transitória do Ollama durante a ingestão).
    """
    while True:
        pendentes = await db_repo.get_chunks_without_vectors(limit=batch_size)
        if not pendentes:
            break

        logger.info(f"Vetorizando lote remanescente de {len(pendentes)} chunks...")
        for chunk in pendentes:
            if chunk.id and chunk.texto_chunk:
                vetor = await embeddings_client.get_embedding(chunk.texto_chunk)
                if vetor:
                    await db_repo.save_chunk_vector(chunk.id, vetor)

        logger.info(f"Lote de {len(pendentes)} chunks vetorizado com sucesso.")


async def worker_loop() -> None:
    """
    Loop principal do Worker do DOE-BA:
    Orquestrador enxuto e linear que gerencia o agendamento/polling e delega
    a extração, enriquecimento e vetorização ao pipeline unificado.
    """
    logger.info("Iniciando Worker do DOE-BA Intelligence Engine...")

    watchlist_cfg = load_watchlist()
    db_repo = PostgresRepository(dsn=POSTGRES_DSN)
    client = DOEBahiaClient()
    engine = IntelligenceEngine(config=watchlist_cfg)
    embeddings_client = OllamaEmbeddings()

    await db_repo.connect()
    await db_repo.setup_schema()

    try:
        while True:
            logger.info("Iniciando ciclo de processamento do Worker...")

            # 1. Sweeper de chunks sem vetor
            await drain_pending_vectors(db_repo, embeddings_client)

            # 2. Leitura de configurações dinâmicas
            settings = await db_repo.get_settings()
            polling_minutes = settings.polling_interval_minutes

            if settings.monitoramento_ativo:
                # 3. Busca de novas edições do dia
                hoje = datetime.now().strftime("%d/%m/%Y")
                edicoes = await client.get_editions_by_date(hoje)

                if edicoes:
                    logger.info(f"Edições encontradas para hoje ({hoje}): {edicoes}")
                    for ed_id in edicoes:
                        await process_edition_pipeline(
                            client=client,
                            edicao_id=ed_id,
                            engine=engine,
                            db_repo=db_repo,
                            embeddings_client=embeddings_client,
                            notify_callback=notify_match,
                        )
                else:
                    logger.info(f"Nenhuma edição publicada encontrada para hoje ({hoje}).")
            else:
                logger.info("Monitoramento pausado via configurações do sistema.")

            logger.info(f"Ciclo concluído. Próxima verificação em {polling_minutes} minutos...")
            await asyncio.sleep(polling_minutes * 60)

    except asyncio.CancelledError:
        logger.info("Worker recebendo sinal de encerramento...")
    finally:
        await db_repo.close()
        await client.close()
        await engine.close()
        await embeddings_client.close()
        logger.info("Recursos do Worker liberados com sucesso.")


if __name__ == "__main__":
    asyncio.run(worker_loop())
