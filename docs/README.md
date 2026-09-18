# 📚 Livro Mestre: Plataforma DOE-BA Intelligence
> **Bem-vindo à Jornada do Engenheiro de Inteligência Governamental.**

Olá, aluno! Este é o seu guia definitivo para entender como transformamos dados brutos do Diário Oficial do Estado da Bahia em um sistema de inteligência semântica de ponta. 

Aqui, você não aprenderá apenas a "fazer código", mas a entender a **filosofia** e a **engenharia de alta performance** por trás de cada decisão arquitetural.

---

## 🗺️ Mapa da Jornada (Capítulos Didáticos)

0. **[Mapa do Repositório](MAPA_DO_REPOSITORIO.md)**
   * Onde está cada arquivo? Um atlas completo das camadas de código, do pipeline unificado aos modelos canônicos.
1. **[Capítulo 01: Fundamentos de Web Scraping](01-fundamentos-web-scraping.md)**
   * Do "Olá Mundo" do HTTP ao Connection Pooling com `httpx.AsyncClient`, resiliência contra Apache 2.2 e extração de PDFs 100% em memória RAM via `io.BytesIO`.
2. **[Capítulo 02: Inteligência Artificial Local](02-inteligencia-artificial-local.md)**
   * A estratégia do Funil de Inteligência (Regex $\to$ Spacy NER $\to$ Ollama Fallback) e o armazenamento de metadados analíticos em colunas nativas **JSONB** no PostgreSQL.
3. **[Capítulo 03: Arquitetura RAG e Vetores](03-arquitetura-rag-e-vetores.md)**
   * A matemática dos Embeddings (`nomic-embed-text`), chunking com overlap de 10% e o fim do atraso de polling com a **vetorização imediata** no pipeline.
4. **[Capítulo 04: Infraestrutura e Operações](04-infraestrutura-e-operacoes.md)**
   * Orquestração com Docker Compose, separação limpa entre o despachante Worker e o Pipeline canônico, e a topologia de rede isolada.

---

## 🛠️ Ferramentas do Ofício: O Antigravity Kit

Para navegar neste projeto, você tem o **Antigravity Kit** ao seu lado. Pense nele como o seu assistente sênior de laboratório:

- **`/status`**: Use este comando para diagnosticar o sistema. Ele dirá se o Banco de Dados, o Ollama e os Workers estão operando em harmonia.
- **`/plan`**: Antes de qualquer mudança drástica, use este comando. Ele ajuda você a projetar a solução antes de encostar no código, evitando "bugs de design".
- **Novas Skills**: Quer ensinar um novo truque ao sistema? Adicione novos arquivos em `.agent/skills/`. Documente o "porquê" e o "como" para que o sistema evolua com você.

---

> [!TIP]
> **Dica do Professor:** Comece pelo Capítulo 01. A base de um bom sistema de IA é a qualidade, a rapidez e a integridade do dado que você coleta!

---
*Professor Sênior & Especialista em IA*
