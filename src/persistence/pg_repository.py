import logging
from typing import List, Optional, Any
import asyncpg  # type: ignore[import-untyped]

from src.core.config import POSTGRES_DSN
from src.core.models import (
    AtoOficial,
    AtoChunk,
    SimilarChunk,
    SystemSettings,
)

logger = logging.getLogger("DOE_BA_Engine")


class PostgresRepository:
    """
    Repositório de persistência assíncrono sobre PostgreSQL + pgvector.
    Responsável pela indexação de matérias, deduplicação por identificador/hash,
    armazenamento de chunks e busca semântica vetorial por cosseno.
    """

    def __init__(self, dsn: Optional[str] = None):
        self.dsn = dsn or POSTGRES_DSN
        self.pool: Optional[asyncpg.Pool] = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def connect(self) -> None:
        """Inicializa o pool de conexões do PostgreSQL."""
        if not self.pool:
            self.pool = await asyncpg.create_pool(self.dsn)
            logger.info("Pool de conexões com PostgreSQL estabelecido com sucesso.")

    async def close(self) -> None:
        """Encerra com segurança todas as conexões ativas no pool."""
        if self.pool:
            await self.pool.close()
            self.pool = None
            logger.info("Conexão com PostgreSQL encerrada.")

    async def setup_schema(self) -> None:
        """
        Criação e migração das tabelas do sistema, extensão pgvector e índices de performance.
        Garante idempotência para inicializações contínuas em ambiente conteinerizado.
        """
        if not self.pool:
            raise RuntimeError("Tentativa de executar setup_schema sem pool conectado.")

        ddl_statements = [
            # Extensão vetorial
            "CREATE EXTENSION IF NOT EXISTS vector;",
            # Tabela principal de Atos Oficiais com colunas JSONB para entidades e dados do LLM
            """
            CREATE TABLE IF NOT EXISTS atos_oficiais (
                id SERIAL PRIMARY KEY,
                identificador VARCHAR(255) UNIQUE NOT NULL,
                hash_conteudo VARCHAR(64),
                secretaria TEXT,
                orgao TEXT,
                titulo TEXT,
                texto_limpo TEXT,
                pagina INT,
                motor_extracao VARCHAR(50),
                data_publicacao DATE,
                entidades JSONB,
                dados_estruturados JSONB,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
            # Chunks vetoriais (dimensão 768 alinhada ao nomic-embed-text)
            """
            CREATE TABLE IF NOT EXISTS atos_chunks (
                id SERIAL PRIMARY KEY,
                ato_id INT REFERENCES atos_oficiais(id) ON DELETE CASCADE,
                texto_chunk TEXT NOT NULL,
                embedding vector(768),
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
            # Configurações dinâmicas de polling e monitoramento
            """
            CREATE TABLE IF NOT EXISTS system_settings (
                id SERIAL PRIMARY KEY,
                polling_interval_minutes INT DEFAULT 60,
                monitoramento_ativo BOOLEAN DEFAULT TRUE,
                atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
            # Índices de performance cruciais
            "CREATE INDEX IF NOT EXISTS idx_atos_chunks_ato_id ON atos_chunks(ato_id);",
            "CREATE INDEX IF NOT EXISTS idx_atos_identificador ON atos_oficiais(identificador);",
            "CREATE INDEX IF NOT EXISTS idx_atos_data_pub ON atos_oficiais(data_publicacao);",
        ]

        async with self.pool.acquire() as conn:
            for statement in ddl_statements:
                await conn.execute(statement)

            # Migrações seguras (caso as colunas ainda não existam em bancos preexistentes)
            await conn.execute("ALTER TABLE atos_oficiais ADD COLUMN IF NOT EXISTS entidades JSONB;")
            await conn.execute("ALTER TABLE atos_oficiais ADD COLUMN IF NOT EXISTS dados_estruturados JSONB;")
            await conn.execute("ALTER TABLE atos_oficiais ALTER COLUMN secretaria TYPE TEXT;")
            await conn.execute("ALTER TABLE atos_oficiais ALTER COLUMN orgao TYPE TEXT;")

            # Inicializa configurações padrão se vazias
            count = await conn.fetchval("SELECT COUNT(*) FROM system_settings")
            if count == 0:
                await conn.execute(
                    "INSERT INTO system_settings (polling_interval_minutes, monitoramento_ativo) VALUES (60, TRUE)"
                )

            logger.info("Esquema do PostgreSQL, extensão pgvector e índices verificados/atualizados.")

    async def insert_ato(self, ato: AtoOficial) -> Optional[int]:
        """
        Insere ou atualiza o ato oficial em uma única query otimizada (UPSERT),
        retornando o ID gerado ou existente em 100% dos casos.
        Persiste entidades e dados_estruturados em formato nativo JSONB.
        """
        if not self.pool:
            logger.error("Tentativa de insert_ato sem pool conectado.")
            return None

        entidades_json = ato.entidades.model_dump_json() if ato.entidades else None
        dados_llm_json = ato.dados_estruturados.model_dump_json() if ato.dados_estruturados else None

        query = """
            INSERT INTO atos_oficiais (
                identificador, hash_conteudo, secretaria, orgao,
                titulo, texto_limpo, pagina, motor_extracao,
                data_publicacao, entidades, dados_estruturados
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11::jsonb
            )
            ON CONFLICT (identificador) DO UPDATE SET
                hash_conteudo = EXCLUDED.hash_conteudo,
                secretaria = EXCLUDED.secretaria,
                orgao = EXCLUDED.orgao,
                titulo = EXCLUDED.titulo,
                texto_limpo = EXCLUDED.texto_limpo,
                pagina = EXCLUDED.pagina,
                motor_extracao = EXCLUDED.motor_extracao,
                entidades = COALESCE(EXCLUDED.entidades, atos_oficiais.entidades),
                dados_estruturados = COALESCE(EXCLUDED.dados_estruturados, atos_oficiais.dados_estruturados)
            RETURNING id;
        """

        async with self.pool.acquire() as conn:
            try:
                ato_id = await conn.fetchval(
                    query,
                    ato.identificador,
                    ato.hash_conteudo,
                    ato.secretaria,
                    ato.orgao,
                    ato.titulo,
                    ato.texto_limpo,
                    ato.pagina,
                    ato.motor_extracao,
                    ato.metadados.data_publicacao,
                    entidades_json,
                    dados_llm_json,
                )
                logger.debug(f"Ato {ato.identificador} gravado/atualizado com ID {ato_id}.")
                return ato_id
            except Exception as e:
                logger.error(f"Erro ao inserir/atualizar ato {ato.identificador} no PostgreSQL: {e}")
                return None

    async def insert_ato_if_not_exists(self, ato: AtoOficial) -> Optional[int]:
        """Alias de compatibilidade reversa para insert_ato."""
        return await self.insert_ato(ato)

    async def get_ato_id_by_identificador(self, identificador: str) -> Optional[int]:
        """Consulta rápida para recuperar o ID de um ato a partir do identificador da matéria."""
        if not self.pool:
            return None
        query = "SELECT id FROM atos_oficiais WHERE identificador = $1;"
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, identificador)

    async def insert_chunk(
        self,
        ato_id: int,
        texto_chunk: str,
        embedding: Optional[List[float]] = None,
    ) -> Optional[int]:
        """Insere um fragmento (chunk) textual, podendo conter vetor de embedding ou não."""
        if not self.pool:
            return None

        embedding_str = str(embedding) if embedding else None
        query = """
            INSERT INTO atos_chunks (ato_id, texto_chunk, embedding)
            VALUES ($1, $2, $3::vector)
            RETURNING id;
        """
        async with self.pool.acquire() as conn:
            try:
                return await conn.fetchval(query, ato_id, texto_chunk, embedding_str)
            except Exception as e:
                logger.error(f"Erro ao inserir chunk para o ato {ato_id}: {e}")
                return None

    async def get_chunks_without_vectors(self, limit: int = 100) -> List[AtoChunk]:
        """
        Busca lotes de chunks que ainda não foram vetorizados.
        Retorna instâncias tipadas de AtoChunk contendo metadados do ato vinculado.
        """
        if not self.pool:
            return []

        query = """
            SELECT c.id, c.ato_id, c.texto_chunk, c.criado_em,
                   a.data_publicacao, a.identificador, a.titulo
            FROM atos_chunks c
            JOIN atos_oficiais a ON c.ato_id = a.id
            WHERE c.embedding IS NULL
            ORDER BY c.criado_em ASC
            LIMIT $1;
        """
        async with self.pool.acquire() as conn:
            records = await conn.fetch(query, limit)
            return [
                AtoChunk(
                    id=r["id"],
                    ato_id=r["ato_id"],
                    texto_chunk=r["texto_chunk"],
                    criado_em=r["criado_em"],
                    data_publicacao=str(r["data_publicacao"]) if r["data_publicacao"] else "Data Desconhecida",
                    identificador=r["identificador"],
                    titulo=r["titulo"],
                )
                for r in records
            ]

    async def save_chunk_vector(self, chunk_id: int, embedding: List[float]) -> bool:
        """Grava o embedding calculado para um chunk específico."""
        if not self.pool:
            return False

        query = """
            UPDATE atos_chunks
            SET embedding = $1::vector
            WHERE id = $2;
        """
        async with self.pool.acquire() as conn:
            try:
                embedding_str = str(embedding)
                await conn.execute(query, embedding_str, chunk_id)
                return True
            except Exception as e:
                logger.error(f"Erro ao salvar vetor para o chunk {chunk_id}: {e}")
                return False

    async def search_similar_chunks(
        self,
        query_vector: List[float],
        limit: int = 5,
    ) -> List[SimilarChunk]:
        """
        Busca semântica usando operador de Distância de Cosseno (<=>) do pgvector.
        Converte distância em score de similaridade (1 - distância) e retorna modelos SimilarChunk.
        """
        if not self.pool:
            return []

        query = """
            SELECT c.id, c.texto_chunk, 1 - (c.embedding <=> $1::vector) AS similarity,
                   a.identificador, a.titulo, a.secretaria, a.orgao, a.data_publicacao
            FROM atos_chunks c
            JOIN atos_oficiais a ON c.ato_id = a.id
            WHERE c.embedding IS NOT NULL
            ORDER BY c.embedding <=> $1::vector
            LIMIT $2;
        """
        async with self.pool.acquire() as conn:
            try:
                embedding_str = str(query_vector)
                records = await conn.fetch(query, embedding_str, limit)
                return [
                    SimilarChunk(
                        chunk_id=r["id"],
                        texto_chunk=r["texto_chunk"],
                        similaridade=float(r["similarity"] or 0.0),
                        ato_identificador=r["identificador"],
                        ato_titulo=r["titulo"],
                        ato_secretaria=r["secretaria"] or "Desconhecida",
                        ato_orgao=r["orgao"] or "Desconhecido",
                        data_publicacao=str(r["data_publicacao"]),
                    )
                    for r in records
                ]
            except Exception as e:
                logger.error(f"Erro na busca semântica vetorial: {e}")
                return []

    async def get_settings(self) -> SystemSettings:
        """Recupera as configurações operacionais dinâmicas do sistema."""
        if not self.pool:
            return SystemSettings(polling_interval_minutes=60, monitoramento_ativo=True)

        query = "SELECT polling_interval_minutes, monitoramento_ativo FROM system_settings LIMIT 1;"
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query)
            if row:
                return SystemSettings(
                    polling_interval_minutes=row["polling_interval_minutes"],
                    monitoramento_ativo=row["monitoramento_ativo"],
                )
            return SystemSettings(polling_interval_minutes=60, monitoramento_ativo=True)

    async def update_settings(self, polling: int, ativo: bool) -> bool:
        """Atualiza o intervalo de polling e o status de monitoramento."""
        if not self.pool:
            return False

        query = """
            UPDATE system_settings
            SET polling_interval_minutes = $1, monitoramento_ativo = $2, atualizado_em = CURRENT_TIMESTAMP
            WHERE id = (SELECT id FROM system_settings LIMIT 1);
        """
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(query, polling, ativo)
                return True
            except Exception as e:
                logger.error(f"Erro ao atualizar configurações no PostgreSQL: {e}")
                return False

    async def get_inventory_stats(self) -> List[dict]:
        """Retorna sumário estatístico de ingestão e chunks agregado por data de publicação."""
        if not self.pool:
            return []

        query = """
            SELECT
                data_publicacao,
                COUNT(id) as total_atos,
                SUM((SELECT COUNT(*) FROM atos_chunks WHERE ato_id = atos_oficiais.id)) as total_chunks,
                MAX(criado_em) as ultima_ingestao
            FROM atos_oficiais
            GROUP BY data_publicacao
            ORDER BY data_publicacao DESC;
        """
        async with self.pool.acquire() as conn:
            try:
                records = await conn.fetch(query)
                return [dict(r) for r in records]
            except Exception as e:
                logger.error(f"Erro ao buscar inventário de publicações: {e}")
                return []
