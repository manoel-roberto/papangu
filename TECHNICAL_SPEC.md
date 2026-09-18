# Technical Specification 2.0: DOE-BA Intelligence Engine

## 1. Visão de Arquitetura (Macro)

O **DOE-BA Intelligence Engine** adota o padrão **Local-First**, priorizando soberania de dados, latência previsível e custo operacional zero pós-implantação. O sistema opera um pipeline unificado e linear de **ETL + RAG (Retrieval-Augmented Generation)** distribuído via Docker Compose.

### Fluxo Linear de Dados (`src/core/pipeline.py`)
1. **Descoberta:** Consulta direta a endpoints estruturados da EGBA via `DOEBahiaClient` em HTTPX, identificando IDs de edições e publicações sem intermediação de navegadores pesados.
2. **Download Resiliente:** Coleta do payload bruto como `DownloadedDocument` (binário/texto em memória) utilizando pool de conexões HTTP reaproveitado.
3. **Extração Pura em Memória:**
   - **HTML:** Parse direto via `BeautifulSoup` / `lxml`.
   - **PDF:** Extração via `pdfplumber` operando sobre **`io.BytesIO`**, erradicando I/O em disco e arquivos temporários.
4. **Contrato Canônico:** Instanciação do modelo `AtoOficial` com validação de esquema em Pydantic.
5. **Higienização:** Normalização de texto via `clean_text` e geração de hash SHA-256 para deduplicação.
6. **Funil de Inteligência:** Classificação em cascata (Regex $\to$ Spacy NER $\to$ Ollama Fallback).
7. **Single-Query UPSERT:** Inserção ou atualização do ato em query única atômica, persistindo entidades e análises semânticas em colunas nativas **JSONB** e recuperando o ID gerado instantaneamente via `RETURNING id`.
8. **Chunking e Vetorização Imediata:** Divisão do texto higienizado em blocos contextuais e geração imediata de embeddings (`nomic-embed-text`), gravando na tabela `atos_chunks` no mesmo ciclo, sem filas ou atrasos de polling.
9. **Consumo Semântico:** API FastAPI para buscas por similaridade de cosseno via `pgvector` e Operations Console em Streamlit.

---

## 2. Core Scraper Engine: Resiliência, Rede e I/O

O servidor do Diário Oficial da Bahia opera sob **Apache/2.2.22**, exigindo conformidade estrita com padrões defensivos de rede para evitar negação de serviço e bloqueios por rate limiting.

### Estratégias de Robustez e Rede
- **Pool de Conexões Persistente (Connection Pooling):** O `DOEBahiaClient` centraliza um `httpx.AsyncClient` persistente com Keep-Alive, eliminando o custo de múltiplos handshakes TLS/TCP.
- **`asyncio.Semaphore(8)`:** Limitação estrita da concorrência global a no máximo 8 requisições simultâneas.
- **Jitter Aleatório:** Introdução de atraso estocástico entre 200ms e 500ms antes de cada requisição externa.
- **Exponential Backoff:** Em caso de erros 5xx ou timeouts, o sistema aguarda intervalos crescentes (2s, 4s, 8s) por até 3 tentativas.
- **Eliminação de Navegador Headless:** A comunicação é feita 100% via requisições HTTP assíncronas diretas aos endpoints de dados da EGBA (`/apifront/portal/...` e `/html/...`), resultando em ganho superior a 10x em velocidade e redução drástica no uso de memória RAM.

### Arquitetura de I/O em Memória
- O módulo `src/parsers/pdf_parser.py` processa arquivos PDF exclusivamente via buffer em memória:
  ```python
  with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
      for page in pdf.pages:
          ...
  ```
- **Benefícios:** Zero contenção de I/O de disco em operações com alto volume de matérias, eliminação do risco de descritores de arquivos órfãos e ausência de resíduos no sistema de arquivos.

---

## 3. O Funil de Inteligência (3 Camadas)

O processamento semântico (`src/intelligence/engine.py`) otimiza recursos computacionais aplicando um funil progressivo de análise:

| Camada | Tecnologia | Escopo de Análise | Custo Computacional |
| :--- | :--- | :--- | :--- |
| **Layer 1 (Lexical/Regex)** | Regex compilado | Match contra palavras-chave e pessoas da `watchlist.yaml`. | Mínimo (~0.1ms) |
| **Layer 2 (NLP Estatístico)** | Spacy (`pt_core_news_sm`) | Reconhecimento de Entidades Nomeadas: Pessoas, Órgãos e Valores. | Baixo (~5-15ms) |
| **Layer 3 (LLM Fallback)** | Ollama (`qwen2.5:1.5b`) | Extração estruturada em JSON e resumo executivo quando há alta complexidade. | Médio/Alto (~200-800ms) |

### Destino dos Dados de Inteligência
- Os metadados extraídos pelo Spacy são validados no modelo `EntidadesExtraidas`.
- As estruturas produzidas pelo Ollama são validadas em `DadosEstruturadosLLM`.
- **Persistência Direta em JSONB:** Ambos os modelos são salvos diretamente nas colunas `entidades` e `dados_estruturados` da tabela `atos_oficiais`, garantindo total consistência transacional e dispensando qualquer formato de armazenamento intermediário desconectado do banco.

---

## 4. Engenharia de Dados e Busca Semântica (RAG)

### Estratégia de Chunking
O módulo `src/intelligence/chunker.py` implementa particionamento com preservação semântica:
- **Tamanho do Bloco:** 600 palavras (compatível com a janela de atenção do modelo `nomic-embed-text`).
- **Overlap:** 10% (60 palavras), garantindo que termos e contextos fronteiriços não sofram quebra semântica.

### Persistência e Indexação Vetorial (`pgvector`)
- **Dimensões:** 768 dimensões geradas pelo modelo `nomic-embed-text` do Ollama.
- **Operador de Distância:** Similaridade de Cosseno via operador `<=>`:
  ```sql
  SELECT id, texto_chunk, 1 - (embedding <=> $1::vector) AS similarity
  FROM atos_chunks
  WHERE embedding IS NOT NULL
  ORDER BY embedding <=> $1::vector
  LIMIT 5;
  ```
- **Vetorização Síncrona no Pipeline:** Diferente de arquiteturas antigas que dependiam de polling secundário para encontrar chunks sem vetor, o `process_ato_pipeline` fatia o texto e gera os vetores imediatamente após o UPSERT do ato. O método `drain_pending_vectors` atua unicamente como salvaguarda para eventuais indisponibilidades de rede com o Ollama.

---

## 5. Especificação dos Modelos de Dados Pydantic

O arquivo `src/core/models.py` atua como o **Single Source of Truth** do sistema:

- **`DownloadedDocument`:** Encapsula bytes brutos baixados (`bytes`), `content_type` e flag `is_pdf`, permitindo desempacotamento de tupla `(content, content_type)`.
- **`AtoSumarioRef`:** Referência de matéria extraída do sumário (`identificador`, `titulo`, `hierarquia`).
- **`AtoOficial`:** Modelo canônico com dados cadastrais, texto bruto, texto limpo, metadados da edição, hash SHA-256, motor de extração, `entidades` e `dados_estruturados`.
- **`AtoChunk`:** Representação de fragmento textual indexado com vetor de 768 dimensões.
- **`SimilarChunk` / `SearchResult`:** Modelos de resposta para consultas semânticas na API.
- **`SystemSettings`:** Configurações dinâmicas de polling e monitoramento.

---

## 6. Infraestrutura Conteinerizada

Gerenciada via Docker Compose em rede privada virtual:
1. **`db`:** PostgreSQL 16 com extensão `pgvector`.
2. **`ollama`:** Runtime de inferência e geração de embeddings com suporte a aceleração local.
3. **`api`:** Backend assíncrono FastAPI.
4. **`worker`:** Daemon consumidor do `process_edition_pipeline`.
5. **`ui`:** Console de Operações Streamlit.

---
