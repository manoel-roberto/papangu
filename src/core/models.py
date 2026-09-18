from datetime import date, datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class MotorExtracao(str, Enum):
    """Identifica o motor ou camada responsável pelo processamento do ato."""
    REGEX = "REGEX"
    SPACY = "SPACY"
    OLLAMA = "OLLAMA"
    NENHUM = "NENHUM"


class MetadadosEdicao(BaseModel):
    """Metadados extraídos de uma edição do Diário Oficial."""
    numero: int = Field(description="Número da edição do Diário Oficial")
    data_publicacao: date = Field(description="Data de publicação da edição")
    caderno: Optional[str] = Field(default=None, description="Identificação do caderno")
    url_origem: Optional[str] = Field(default=None, description="URL de origem da edição")


class EntidadesExtraidas(BaseModel):
    """Entidades identificadas via processamento de linguagem natural (Spacy NER)."""
    pessoas: List[str] = Field(default_factory=list, description="Nomes de pessoas identificadas")
    organizacoes: List[str] = Field(default_factory=list, description="Órgãos e organizações")
    valores: List[str] = Field(default_factory=list, description="Valores monetários ou numéricos relevantes")


class DadosEstruturadosLLM(BaseModel):
    """Dados semânticos estruturados extraídos via LLM local (Ollama)."""
    pessoas_envolvidas: List[str] = Field(default_factory=list, description="Pessoas diretamente envolvidas no ato")
    valor_contrato: Optional[str] = Field(default=None, description="Valor do contrato ou licitação, se houver")
    resumo: Optional[str] = Field(default=None, description="Resumo executivo do ato gerado pela LLM")


class DownloadedDocument(BaseModel):
    """
    Representa o documento bruto baixado da API/portal do DOE.
    Suporta desempacotamento como tupla `(content, content_type)` para compatibilidade reversa.
    """
    content: bytes = Field(default=b"", description="Conteúdo binário do documento")
    content_type: str = Field(default="text/html", description="MIME type retornado pelo servidor")
    is_pdf: bool = Field(default=False, description="Flag indicando se o arquivo é um PDF")

    def __bool__(self) -> bool:
        return bool(self.content)

    def __iter__(self):
        """Permite desempacotamento: content, content_type = downloaded_doc"""
        return iter((self.content, self.content_type))


class AtoSumarioRef(BaseModel):
    """Referência a um ato obtida da árvore de sumário HTML."""
    identificador: str = Field(description="Identificador único da publicação na API/portal")
    titulo: str = Field(description="Título da matéria")
    hierarquia: List[str] = Field(default_factory=list, description="Hierarquia administrativa (Secretaria / Órgão)")

    def __getitem__(self, item: str):
        """Permite acesso indexado para compatibilidade: ato_ref['identificador']"""
        return getattr(self, item)


class AtoOficial(BaseModel):
    """
    Modelo canônico de um Ato Oficial no DOE-BA.
    Single Source of Truth para todo o fluxo de ingestão, inteligência e persistência.
    """
    identificador: str = Field(description="ID único da matéria no DOE-BA")
    secretaria: str = Field(default="Desconhecida", description="Secretaria de origem")
    orgao: str = Field(default="Desconhecido", description="Órgão de origem")
    titulo: str = Field(description="Título do ato publicado")
    texto_integral: str = Field(description="Texto bruto extraído da publicação")
    texto_limpo: Optional[str] = Field(default=None, description="Texto normalizado e sem ruídos")
    pagina: Optional[int] = Field(default=None, description="Página onde o ato se encontra")
    hash_conteudo: Optional[str] = Field(default=None, description="Hash SHA-256 do texto limpo para deduplicação")
    motor_extracao: Optional[str] = Field(default=MotorExtracao.NENHUM.value, description="Motor que realizou a extração/match")
    metadados: MetadadosEdicao = Field(description="Metadados da edição vinculada")
    entidades: Optional[EntidadesExtraidas] = Field(default=None, description="Entidades extraídas via NER")
    dados_estruturados: Optional[DadosEstruturadosLLM] = Field(default=None, description="Dados estruturados extraídos via LLM")


class AtoChunk(BaseModel):
    """Fragmento textual de um ato processado para indexação e busca vetorial RAG."""
    id: Optional[int] = Field(default=None, description="ID do chunk no banco")
    ato_id: Optional[int] = Field(default=None, description="ID do ato no banco")
    texto_chunk: str = Field(description="Texto do fragmento")
    embedding: Optional[List[float]] = Field(default=None, description="Vetor de embedding (768 dimensões)")
    criado_em: Optional[datetime] = Field(default=None, description="Data/hora de criação")
    # Metadados contextuais carregados em queries com JOIN
    data_publicacao: Optional[str] = Field(default=None, description="Data de publicação do ato vinculado")
    identificador: Optional[str] = Field(default=None, description="Identificador do ato vinculado")
    titulo: Optional[str] = Field(default=None, description="Título do ato vinculado")

    def __getitem__(self, item: str):
        return getattr(self, item)

    def get(self, item: str, default=None):
        return getattr(self, item, default)


class SimilarChunk(BaseModel):
    """Resultado individual de busca semântica por similaridade de cosseno."""
    chunk_id: int
    texto_chunk: str
    similaridade: float
    ato_identificador: str
    ato_titulo: str
    ato_secretaria: str
    ato_orgao: str
    data_publicacao: str

    def __getitem__(self, item: str):
        return getattr(self, item)

    def get(self, item: str, default=None):
        return getattr(self, item, default)


class SearchResult(BaseModel):
    """Resultado consolidado da consulta semântica."""
    query: str
    results: List[SimilarChunk] = Field(default_factory=list)


class WatchlistMatchItem(BaseModel):
    """Item correspondente a um termo monitorado na watchlist."""
    id: int
    identificador: str
    titulo: str
    secretaria: str
    data_publicacao: str

    def __getitem__(self, item: str):
        return getattr(self, item)


class WatchlistAlert(BaseModel):
    """Agrupamento de alertas por termo da watchlist."""
    termo: str
    matches: List[WatchlistMatchItem] = Field(default_factory=list)


class SystemSettings(BaseModel):
    """Configurações dinâmicas de operação do sistema."""
    polling_interval_minutes: int = Field(default=60, ge=1, le=1440)
    monitoramento_ativo: bool = Field(default=True)

    def __getitem__(self, item: str):
        return getattr(self, item)

    def get(self, item: str, default=None):
        return getattr(self, item, default)
