# 🛡️ DOE-BA Intelligence Engine

O **DOE-BA Intelligence Engine** é uma plataforma avançada de inteligência governamental e monitoramento do Diário Oficial do Estado da Bahia. O sistema automatiza a extração, sanitização, análise semântica e busca vetorial RAG de atos oficiais, permitindo vigilância proativa sobre termos sensíveis e pessoas monitoradas.

---

## 🚀 Filosofia Local-First & Privacidade

Diferente de soluções baseadas em nuvem comercial, este projeto adota uma arquitetura **100% Local**:
- **Privacidade & Compliance LGPD:** Todo o processamento analítico ocorre internamente na infraestrutura local, impedindo que dados de servidores ou atos administrativos trafeguem para APIs públicas de terceiros.
- **Custo Zero:** Utiliza modelos de IA locais (via Ollama) para classificação e geração de embeddings, eliminando custos recorrentes por tokens.
- **Soberania Operacional:** O sistema funciona de forma autônoma, sem dependência de chaves de API externas ou conexões com a nuvem.

---

## 🏗️ Destaques da Nova Arquitetura

O sistema opera sobre um pipeline linear e no estado da arte:

1. **Pipeline Unificado (`src/core/pipeline.py`):** Centraliza o fluxo completo em um ponto único:
   $$\text{Extração} \longrightarrow \text{Limpeza} \longrightarrow \text{Inteligência} \longrightarrow \text{Single-Query UPSERT} \longrightarrow \text{Chunking} \longrightarrow \text{Vetorização Imediata}$$
   Os componentes `worker.py`, `cli.py` e a API (`/ingest/backfill`) apenas consomem este pipeline.
2. **Vetorização Imediata (Zero Polling Lag):** Os blocos textuais (chunks) são fatiados e vetorizados imediatamente após a persistência do ato. Não há intervalo de espera ou dependência de loops lentos de polling.
3. **Single Source of Truth (`src/core/models.py`):** Todos os contratos de dados (`DownloadedDocument`, `AtoOficial`, `AtoChunk`, `EntidadesExtraidas`, `DadosEstruturadosLLM`) são rigorosamente tipados e validados com Pydantic v2.
4. **Extração 100% em Memória (Zero Disk I/O):** No módulo `src/parsers/pdf_parser.py`, o processamento de PDFs utiliza streams binárias com `io.BytesIO` e `pdfplumber` 100% na memória RAM, garantindo alta vazão e zero operações desnecessárias em disco.
5. **JSONB Nativo & Atomicidade:** As entidades extraídas pelo Spacy (NER) e os dados estruturados pelo Ollama são gravados diretamente em colunas **JSONB nativas** do PostgreSQL, garantindo integridade ACID e permitindo consultas relacionais e semânticas combinadas.
6. **Single-Query UPSERT & Connection Pooling:** Inserção e atualização atômica via `ON CONFLICT (identificador) DO UPDATE ... RETURNING id` e reaproveitamento de sockets TCP via `httpx.AsyncClient` persistente com semáforo de concorrência e jitter.

---

## 🛠️ Stack Tecnológica

- **Core & Pipeline:** Python 3.10+, Pydantic v2, Asyncio.
- **Rede & Ingestão:** HTTPX Assíncrono com Connection Pooling, BeautifulSoup4, LXML, pdfplumber (`io.BytesIO`).
- **Funil de Inteligência:** Spacy (`pt_core_news_sm`), Ollama (`qwen2.5:1.5b`).
- **Vetorização & RAG:** Ollama (`nomic-embed-text` - 768 dimensões), Chunker contextual com 10% de overlap.
- **Banco de Dados:** PostgreSQL 16 + pgvector + JSONB nativo (Asyncpg).
- **APIs & Interface:** FastAPI, Uvicorn, Streamlit Operations Console.

---

## 🚦 Configuração Rápida (Developer Onboarding)

O projeto está 100% conteinerizado via Docker Compose:

1. **Clone & Configuração:**
   ```bash
   git clone <url-do-repositorio>
   cd Papangu
   cp .env.example .env
   ```
2. **Subir a Infraestrutura:**
   ```bash
   docker compose up -d --build
   ```
3. **Baixar os Modelos de IA no Ollama (Apenas na primeira execução):**
   ```bash
   docker exec -it doe_ollama ollama pull qwen2.5:1.5b
   docker exec -it doe_ollama ollama pull nomic-embed-text
   ```
4. **Acessar as Aplicações:**
   - **Console de Operações (Streamlit):** [http://localhost:8501](http://localhost:8501)
   - **Documentação da API (FastAPI Swagger):** [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 💻 Execução via CLI

Você pode executar o pipeline unificado diretamente via terminal para testes ou ingestões históricas:

```bash
# Processar uma edição por ID específico
python -m src.cli 12345

# Processar todas as edições de uma data (DD/MM/AAAA)
python -m src.cli 09/05/2026

# Processar um intervalo de datas
python -m src.cli "01/05/2026 até 05/05/2026"
```

---

## 📖 Documentação & Livro Mestre

Para uma compreensão aprofundada da plataforma, consulte nosso **[Livro Mestre da Plataforma](docs/README.md)** estruturado em capítulos didáticos:

- [**🗺️ Mapa do Repositório: O Atlas do Código**](docs/MAPA_DO_REPOSITORIO.md)
- [**Capítulo 01: Fundamentos de Web Scraping & In-Memory Streaming**](docs/01-fundamentos-web-scraping.md)
- [**Capítulo 02: Inteligência Artificial Local & Colunas JSONB**](docs/02-inteligencia-artificial-local.md)
- [**Capítulo 03: Arquitetura RAG, Vetorização Imediata e pgvector**](docs/03-arquitetura-rag-e-vetores.md)
- [**Capítulo 04: Infraestrutura, Docker e o Loop do Worker**](docs/04-infraestrutura-e-operacoes.md)

Para engenheiros de software, auditores e documentação formal:
- [**TECHNICAL MASTER: Arquitetura Consolidada**](docs/TECHNICAL_MASTER.md)
- [**Manifesto Técnico de Arquitetura**](ARCHITECTURE.md)
- [**Especificação Técnica 2.0**](TECHNICAL_SPEC.md)
- [**Guia de Instalação e Ambiente Híbrido**](INSTALL.md)
- [**Exemplo de Configuração da Watchlist**](watchlist.example.yaml)

---
*Desenvolvido para o laboratório de inteligência governamental do Diário Oficial do Estado da Bahia.*
