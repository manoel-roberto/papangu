import asyncio
import argparse
import logging
import sys
from typing import List

from src.core.client import DOEBahiaClient
from src.core.config import POSTGRES_DSN, load_watchlist
from src.core.pipeline import process_edition_pipeline
from src.persistence.pg_repository import PostgresRepository
from src.intelligence.engine import IntelligenceEngine
from src.intelligence.embeddings import OllamaEmbeddings
from src.utils.helpers import parse_input_type

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("DOE_BA_CLI")


async def run_pipeline(input_query: str) -> None:
    """
    Executa a extração, inteligência e persistência via CLI usando o pipeline unificado.
    Suporta consulta por ID de edição, data única (DD/MM/AAAA) ou intervalo (DD/MM/AAAA até DD/MM/AAAA).
    """
    client = DOEBahiaClient()
    db_repo = PostgresRepository(dsn=POSTGRES_DSN)
    engine = IntelligenceEngine(config=load_watchlist())
    embeddings_client = OllamaEmbeddings()

    await db_repo.connect()
    await db_repo.setup_schema()

    try:
        parsed = parse_input_type(input_query)
        ids_to_process: List[str] = []

        if parsed["type"] == "id":
            ids_to_process = [parsed["value"]]
        elif parsed["type"] == "date":
            ids_to_process = await client.get_editions_by_date(parsed["value"])
        elif parsed["type"] == "range":
            ids_to_process = await client.get_editions_by_range(parsed["start"], parsed["end"])

        if not ids_to_process:
            logger.warning(f"Nenhuma edição encontrada para a consulta: '{input_query}'")
            return

        logger.info(f"Total de {len(ids_to_process)} edição(ões) para processar via pipeline unificado.")

        for eid in ids_to_process:
            atos = await process_edition_pipeline(
                client=client,
                edicao_id=eid,
                engine=engine,
                db_repo=db_repo,
                embeddings_client=embeddings_client,
            )
            logger.info(f"Edição ID {eid}: {len(atos)} matérias processadas, salvas e vetorizadas.")

    except ValueError as e:
        logger.error(f"Erro de formato de entrada: {e}")
    finally:
        await client.close()
        await db_repo.close()
        await engine.close()
        await embeddings_client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="DOE-BA CLI Engine - Pipeline Unificado de Ingestão e RAG")
    parser.add_argument(
        "query",
        nargs="+",
        help="ID numérico, Data (DD/MM/AAAA) ou Intervalo (ex: 01/01/2026 até 05/01/2026)",
    )
    args = parser.parse_args()

    query_str = " ".join(args.query)
    asyncio.run(run_pipeline(query_str))


if __name__ == "__main__":
    main()
