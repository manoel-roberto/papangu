# TECHNICAL MASTER: Arquitetura DOE-BA Intelligence Engine
> Documento consolidado para engenheiros de software, especialistas em IA e auditores técnicos.

---

## 1. Pipeline de Ingestão e Resiliência (Web Scraping)

O motor de coleta reside em `src/core/client.py` e interage com o servidor **Apache/2.2.22** da EGBA utilizando uma pilha 100% assíncrona baseada em `HTTPX`.

### Estratégias de Robustez e Conexão:
- **Pool de Conexões Persistente (Connection Pooling):** O `DOEBahiaClient` instancia um único `httpx.AsyncClient` persistente durante todo o ciclo de vida, mantendo conexões TCP ativas com Keep-Alive e reduzindo o consumo de descritores de socket.
- **`asyncio.Semaphore(8)`:** Limita rigorosamente a concorrência global a 8 requisições simultâneas, prevenindo bloqueios por esgotamento de conexões no servidor legado.
- **Jitter Aleatório (200-500ms):** Intervalo dinâmico entre requisições para mitigar padrões artificiais e evitar sobrecarga de borda.
- **Requisições Diretas aos Endpoints Estruturados:** O sistema consome diretamente os endpoints de metadados, sumários e publicações da EGBA (`/apifront/portal/...` e `/html/...`), dispensando completamente o uso de navegadores headless pesados.
- **Extração 100% em Memória (Zero Disk I/O):**
  - Implementado em `src/parsers/pdf_parser.py`, o processamento de PDFs utiliza **`io.BytesIO(pdf_bytes)`** diretamente com o `pdfplumber`.
  - **Benefício:** O processamento ocorre 100% em memória RAM sem escrita intermediária em disco, prevenindo contenção de I/O em grandes lotes de ingestão e eliminando o risco de descritores de arquivos órfãos.
- **Contratos Canônicos (Pydantic):** A integridade dos dados trafegados é garantida por `DownloadedDocument` e `AtoOficial` em `src/core/models.py`.

---

## 2. O Funil de Inteligência (Intelligence Layer)

A lógica de processamento semântico está centralizada em `src/intelligence/engine.py`.

### Arquitetura de Camadas em Cascata:
1. **Camada 1 (Regex):** Filtragem léxica instantânea contra termos e pessoas monitoradas (`watchlist.yaml`). Descarta atos sem correlação antes de acionar etapas custosas.
2. **Camada 2 (NLP Estatístico - Spacy):** Utiliza o modelo `pt_core_news_sm` para Reconhecimento de Entidades Nomeadas (Pessoas, Organizações e Valores Monetários).
3. **Camada 3 (Semântica/LLM Fallback - Ollama):** Chamada assíncrona ao modelo `qwen2.5:1.5b` com enforcement de resposta em formato JSON para estruturação semântica e geração de resumos executivos quando a extração estatística demanda complemento.

> [!IMPORTANT]
> **Persistência em JSONB Nativo:** Todas as informações geradas pelo Spacy e Ollama são atribuídas aos campos `entidades` e `dados_estruturados` do modelo `AtoOficial` e persistidas em colunas **JSONB nativas** no PostgreSQL, garantindo integridade ACID e capacidade de consulta relacional.

---

## 3. Vetorização e Busca Semântica (RAG Imediato)

### O Coração do Pipeline (`src/core/pipeline.py`):
O processamento de matérias (`process_ato_pipeline`) opera de forma linear:
$$\text{Extração} \longrightarrow \text{Limpeza} \longrightarrow \text{Inteligência} \longrightarrow \text{Single-Query UPSERT} \longrightarrow \text{Chunking} \longrightarrow \text{Vetorização Imediata}$$

- **Fim do Polling Lag:** Os blocos de texto são fatiados e imediatamente vetorizados com o modelo `nomic-embed-text` logo após a persistência do ato, eliminando qualquer intervalo de espera entre a ingestão e a disponibilidade na busca semântica.

### Particionamento (Chunking):
Implementado em `src/intelligence/chunker.py`:
- **Janela de Contexto:** 600 palavras por bloco.
- **Sobreposição (Overlap):** 10% (60 palavras), garantindo preservação de contexto em fronteiras de corte textual.

### Persistência Vetorial (`src/persistence/pg_repository.py`):
- **Single-Query UPSERT:** Gravação do ato através da cláusula `ON CONFLICT (identificador) DO UPDATE ... RETURNING id`, garantindo atomicidade e retorno instantâneo da chave primária para a indexação dos chunks.
- **Operador de Similaridade:** Cálculo de similaridade de cosseno diretamente no PostgreSQL através do operador `<=>` do **pgvector** sobre vetores de 768 dimensões.

---

## 4. Orquestração e Infraestrutura

### Consumidores do Pipeline Unificado:
1. **`src/worker.py`:** Serviço daemon para monitoramento contínuo da edição do dia. Mantém a rotina `drain_pending_vectors` como rede de segurança defensiva para reprocessar chunks que eventualmente falharam por indisponibilidade transitória do Ollama.
2. **`src/cli.py`:** Utilitário para ingestão e reprocessamento ad-hoc sob demanda por ID, data ou intervalo de datas.
3. **`src/api/routes.py`:** Endpoint assíncrono `/ingest/backfill` executando o mesmo pipeline em background.

### Estrutura de Diretórios de Dados:
A pasta `data/` abriga exclusivamente dados permanentes:
- `data/logs/`: Diagnóstico técnico e auditoria operacional.
- `data/backups/`: Snapshots do banco de dados relacional e vetorial.
*(Nota: O antigo diretório `data/temp/` foi erradicado, pois o manuseio de PDFs ocorre 100% na memória RAM).*

---

## 5. Guia de Estudo Técnico

- **Concorrência Assíncrona:** [Asyncio Semaphores e HTTP Connection Pools em Python](https://docs.python.org/3/library/asyncio-sync.html#semaphore)
- **Busca Vetorial Nativa:** [Documentação pgvector e Operador de Cosseno](https://github.com/pgvector/pgvector)
- **Modelagem e Contratos:** [Pydantic v2: Single Source of Truth](https://docs.pydantic.dev/)
- **Armazenamento de Metadados:** [PostgreSQL JSONB Types and Indexing](https://www.postgresql.org/docs/current/datatype-json.html)

---
*Este documento é a verdade técnica definitiva e auditada da Plataforma DOE-BA.*
