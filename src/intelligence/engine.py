import re
import json
import hashlib
import logging
from typing import List, Optional, Any
import httpx

from src.core.models import (
    AtoOficial,
    MotorExtracao,
    EntidadesExtraidas,
    DadosEstruturadosLLM,
)
from src.core.config import (
    WatchlistConfig,
    OLLAMA_HOST,
    LLM_MODEL,
    HTTP_TIMEOUT,
)
from src.intelligence.cleaner import clean_text

logger = logging.getLogger("DOE_BA_Engine")


class IntelligenceEngine:
    """
    Funil de Inteligência em 3 Camadas para classificação e estruturação de atos oficiais:
    - Camada 1 (Lexical/Regex): Filtro instantâneo baseado na watchlist (palavras-chave e pessoas).
    - Camada 2 (NLP Estatístico): Extração de Entidades Nomeadas (NER) via Spacy pt_core_news_sm.
    - Camada 3 (Semântica/LLM): Extração e estruturação profunda via Ollama (qwen2.5:1.5b).
    """

    def __init__(
        self,
        config: Optional[WatchlistConfig] = None,
        ollama_url: Optional[str] = None,
        llm_model: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.config = config or WatchlistConfig(keywords=[], pessoas_monitoradas=[])
        self.ollama_url = ollama_url or OLLAMA_HOST
        self.llm_model = llm_model or LLM_MODEL
        self._external_client = http_client is not None
        self.http_client = http_client or httpx.AsyncClient(
            base_url=self.ollama_url,
            timeout=HTTP_TIMEOUT,
        )
        self._spacy_nlp: Optional[Any] = None
        self._load_spacy()

    def _load_spacy(self) -> None:
        """Carrega o modelo Spacy em português com fallback seguro."""
        try:
            import spacy
            self._spacy_nlp = spacy.load("pt_core_news_sm")
            logger.info("Modelo Spacy 'pt_core_news_sm' carregado com sucesso.")
        except Exception as e:
            logger.warning(
                f"Não foi possível carregar Spacy 'pt_core_news_sm': {e}. "
                "Camada 2 (NER) operará em modo degradado seguro."
            )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self) -> None:
        """Encerra a sessão HTTP persistente do Ollama caso gerenciada internamente."""
        if not self._external_client and not self.http_client.is_closed:
            await self.http_client.aclose()

    def match_watchlist(self, text: str) -> List[str]:
        """
        Camada 1 (Lexical): Avalia o texto contra os termos e pessoas da watchlist.
        Retorna a lista de termos que deram 'match'.
        """
        if not text:
            return []

        matches: List[str] = []

        # 1. Checa palavras-chave (com boundary de palavras)
        if self.config.keywords:
            for kw in self.config.keywords:
                pattern = re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE)
                if pattern.search(text):
                    matches.append(kw)

        # 2. Checa pessoas monitoradas (busca literal case-insensitive)
        if self.config.pessoas_monitoradas:
            for pessoa in self.config.pessoas_monitoradas:
                pattern = re.compile(re.escape(pessoa), re.IGNORECASE)
                if pattern.search(text):
                    matches.append(pessoa)

        return sorted(list(set(matches)))

    def extract_entities_ner(self, text: str) -> EntidadesExtraidas:
        """
        Camada 2 (NLP Estatístico): Extrai entidades nomeadas (Pessoas, Organizações, Valores).
        Retorna modelo canônico EntidadesExtraidas.
        """
        if not text or not self._spacy_nlp:
            return EntidadesExtraidas()

        doc = self._spacy_nlp(text)
        pessoas: List[str] = []
        organizacoes: List[str] = []
        valores: List[str] = []

        for ent in doc.ents:
            clean_name = ent.text.strip()
            if not clean_name:
                continue

            if ent.label_ == "PER":
                pessoas.append(clean_name)
            elif ent.label_ == "ORG":
                organizacoes.append(clean_name)
            elif ent.label_ in ["MONEY", "NUM"]:
                valores.append(clean_name)

        return EntidadesExtraidas(
            pessoas=sorted(list(set(pessoas))),
            organizacoes=sorted(list(set(organizacoes))),
            valores=sorted(list(set(valores))),
        )

    async def extract_structured_llm(
        self,
        text: str,
        max_chars: int = 2500,
    ) -> Optional[DadosEstruturadosLLM]:
        """
        Camada 3 (Semântica/LLM): Extrai informações estruturadas e gera resumo via Ollama.
        Reutiliza o pool de conexões HTTP e retorna DadosEstruturadosLLM validado.
        """
        if not text:
            return None

        prompt = (
            "Extraia as informações principais deste ato oficial publicado no Diário Oficial da Bahia.\n"
            "Responda APENAS com um JSON válido com esta estrutura exata:\n"
            '{\n  "pessoas_envolvidas": ["nome 1", "nome 2"],\n  "valor_contrato": "R$ 0,00",\n  "resumo": "Breve resumo..."\n}\n\n'
            f"Texto do Ato:\n{text[:max_chars]}"
        )

        payload = {
            "model": self.llm_model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }

        try:
            response = await self.http_client.post("/api/generate", json=payload)
            response.raise_for_status()
            data = response.json()
            raw_response = data.get("response", "{}")
            parsed_json = json.loads(raw_response)

            return DadosEstruturadosLLM(
                pessoas_envolvidas=parsed_json.get("pessoas_envolvidas", []) or [],
                valor_contrato=parsed_json.get("valor_contrato"),
                resumo=parsed_json.get("resumo"),
            )
        except Exception as e:
            logger.error(f"Falha na Camada 3 (Ollama Fallback): {e}")
            return None

    async def processar_ato(
        self,
        ato: AtoOficial,
        force_llm: bool = False,
    ) -> AtoOficial:
        """
        Orquestra o funil modular de inteligência:
        1. Limpeza e Hash SHA-256
        2. Camada 1: Regex Watchlist
        3. Camada 2: Spacy NER
        4. Camada 3: Ollama LLM (Acionado se force_llm=True ou quando NER necessita de estruturação)
        """
        # 1. Sanitização e Hash único
        texto_limpo = clean_text(ato.texto_integral)
        ato.texto_limpo = texto_limpo
        ato.hash_conteudo = hashlib.sha256(texto_limpo.encode("utf-8")).hexdigest()

        # 2. Camada 1: Filtro Lexical (Watchlist)
        matches = self.match_watchlist(texto_limpo)
        if not matches and not force_llm:
            ato.motor_extracao = MotorExtracao.NENHUM.value
            return ato

        ato.motor_extracao = MotorExtracao.REGEX.value

        # 3. Camada 2: Extração de Entidades (NER)
        entidades = self.extract_entities_ner(texto_limpo)
        ato.entidades = entidades
        if entidades.pessoas or entidades.organizacoes or entidades.valores:
            ato.motor_extracao = MotorExtracao.SPACY.value

        # 4. Camada 3: Estruturação Semântica (LLM Fallback)
        # Acionada quando forçado explicitamente ou quando a watchlist teve match mas o NER não achou pessoas
        deve_acionar_llm = force_llm or (matches and not entidades.pessoas)
        if deve_acionar_llm:
            dados_llm = await self.extract_structured_llm(texto_limpo)
            if dados_llm:
                # Fim do caminho morto: dados salvos no modelo canônico
                ato.dados_estruturados = dados_llm
                ato.motor_extracao = MotorExtracao.OLLAMA.value
                logger.info(f"Dados estruturados extraídos via Ollama para ato {ato.identificador}")

        return ato
