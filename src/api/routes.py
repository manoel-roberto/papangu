import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field

from src.api.dependencies import get_db, get_embeddings_client
from src.core.config import load_watchlist
from src.core.models import (
    SearchResult,
    SystemSettings,
    WatchlistAlert,
    WatchlistMatchItem,
)
from src.core.client import DOEBahiaClient
from src.core.pipeline import process_edition_pipeline
from src.persistence.pg_repository import PostgresRepository
from src.intelligence.engine import IntelligenceEngine
from src.intelligence.embeddings import OllamaEmbeddings

logger = logging.getLogger("DOE_BA_API")
router = APIRouter()


class DatabaseStats(BaseModel):
    total_atos_oficiais: int
    total_chunks_gerados: int
    total_chunks_com_embedding: int
    pendentes_vetorizacao: int


class SystemStatusResponse(BaseModel):
    estatisticas: DatabaseStats
    inventario: List[dict] = Field(default_factory=list)


class SettingsUpdateRequest(BaseModel):
    polling_interval_minutes: int = Field(ge=1, le=1440)
    monitoramento_ativo: bool


class MessageResponse(BaseModel):
    message: str


class AlertsResponse(BaseModel):
    alerts: List[WatchlistAlert] = Field(default_factory=list)


@router.get("/search", response_model=SearchResult)
async def search(
    query: str,
    limit: int = 5,
    db: PostgresRepository = Depends(get_db),
    embeddings_client: OllamaEmbeddings = Depends(get_embeddings_client),
) -> SearchResult:
    """Realiza busca semântica por atos oficiais usando texto em linguagem natural."""
    if not query or not query.strip():
        raise HTTPException(status_code=400, detail="Query não pode estar vazia.")

    query_vector = await embeddings_client.get_embedding(query)
    if not query_vector:
        raise HTTPException(status_code=500, detail="Erro ao gerar embedding da query.")

    results = await db.search_similar_chunks(query_vector, limit=limit)
    return SearchResult(query=query, results=results)


@router.get("/status", response_model=SystemStatusResponse)
async def status(db: PostgresRepository = Depends(get_db)) -> SystemStatusResponse:
    """Retorna estatísticas globais do banco de dados e inventário de ingestão."""
    if not db.pool:
        raise HTTPException(status_code=500, detail="Banco de dados desconectado.")

    async with db.pool.acquire() as conn:
        total_atos = await conn.fetchval("SELECT COUNT(*) FROM atos_oficiais") or 0
        total_chunks = await conn.fetchval("SELECT COUNT(*) FROM atos_chunks") or 0
        total_vectored = (
            await conn.fetchval("SELECT COUNT(*) FROM atos_chunks WHERE embedding IS NOT NULL") or 0
        )

    inventory = await db.get_inventory_stats()

    return SystemStatusResponse(
        estatisticas=DatabaseStats(
            total_atos_oficiais=total_atos,
            total_chunks_gerados=total_chunks,
            total_chunks_com_embedding=total_vectored,
            pendentes_vetorizacao=max(0, total_chunks - total_vectored),
        ),
        inventario=inventory,
    )


@router.get("/settings", response_model=SystemSettings)
async def get_settings(db: PostgresRepository = Depends(get_db)) -> SystemSettings:
    """Recupera as configurações dinâmicas de operação do sistema."""
    return await db.get_settings()


@router.put("/settings", response_model=MessageResponse)
async def update_settings(
    update: SettingsUpdateRequest,
    db: PostgresRepository = Depends(get_db),
) -> MessageResponse:
    """Atualiza as configurações operacionais dinâmicas."""
    success = await db.update_settings(update.polling_interval_minutes, update.monitoramento_ativo)
    if not success:
        raise HTTPException(status_code=500, detail="Erro ao atualizar configurações.")
    return MessageResponse(message="Configurações atualizadas com sucesso.")


@router.post("/ingest/backfill", response_model=MessageResponse)
async def backfill(
    start_date: str,
    end_date: str,
    background_tasks: BackgroundTasks,
    db: PostgresRepository = Depends(get_db),
    embeddings_client: OllamaEmbeddings = Depends(get_embeddings_client),
) -> MessageResponse:
    """Dispara a ingestão histórica para um período específico utilizando o pipeline unificado."""
    background_tasks.add_task(run_backfill_ingestion, start_date, end_date, db, embeddings_client)
    return MessageResponse(
        message=f"Backfill iniciado para o período {start_date} a {end_date}. Acompanhe via logs."
    )


async def run_backfill_ingestion(
    start_date: str,
    end_date: str,
    db: PostgresRepository,
    embeddings: OllamaEmbeddings,
) -> None:
    """
    Rotina em background que consome o pipeline unificado para processamento histórico.
    Elimina qualquer duplicação de lógica entre Backfill, Worker e CLI.
    """
    logger.info(f"Iniciando rotina de backfill histórico: {start_date} -> {end_date}")

    client = DOEBahiaClient()
    engine = IntelligenceEngine(config=load_watchlist())

    try:
        edicoes_ids = await client.get_editions_by_range(start_date, end_date)
        logger.info(f"Backfill: {len(edicoes_ids)} edições encontradas no período.")

        for ed_id in edicoes_ids:
            await process_edition_pipeline(
                client=client,
                edicao_id=ed_id,
                engine=engine,
                db_repo=db,
                embeddings_client=embeddings,
            )

        logger.info(f"Backfill histórico concluído com sucesso: {start_date} -> {end_date}")
    except Exception as e:
        logger.error(f"Falha durante execução do backfill: {e}")
    finally:
        await client.close()
        await engine.close()


@router.get("/watchlist/alerts", response_model=AlertsResponse)
async def watchlist_alerts(db: PostgresRepository = Depends(get_db)) -> AlertsResponse:
    """
    Retorna matérias que deram match com os termos da watchlist configurada.
    """
    if not db.pool:
        raise HTTPException(status_code=500, detail="Banco de dados desconectado.")

    config = load_watchlist()
    termos = sorted(list(set(config.keywords + config.pessoas_monitoradas)))
    if not termos:
        return AlertsResponse(alerts=[])

    alerts: List[WatchlistAlert] = []
    async with db.pool.acquire() as conn:
        for termo in termos:
            query = """
                SELECT id, identificador, titulo, secretaria, data_publicacao
                FROM atos_oficiais
                WHERE texto_limpo ILIKE $1
                ORDER BY data_publicacao DESC
                LIMIT 10;
            """
            records = await conn.fetch(query, f"%{termo}%")
            if records:
                matches = [
                    WatchlistMatchItem(
                        id=r["id"],
                        identificador=r["identificador"],
                        titulo=r["titulo"],
                        secretaria=r["secretaria"] or "Desconhecida",
                        data_publicacao=str(r["data_publicacao"]),
                    )
                    for r in records
                ]
                alerts.append(WatchlistAlert(termo=termo, matches=matches))

    return AlertsResponse(alerts=alerts)
