"""Pipeline data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID


@dataclass
class GenerationConfig:
    temperature: float = 0.2
    max_tokens: int = 2000
    stream: bool = False


@dataclass
class RetrievalRequest:
    query: str
    tenant_id: UUID
    kb_ids: list[UUID]
    top_k: int = 8
    strategy: str = "hybrid"  # vector | keyword | hybrid
    min_score: float = 0.0  # normalised 0-1
    filters: dict = field(default_factory=dict)
    enable_rerank: bool | None = None
    enable_query_rewrite: bool | None = None
    max_context_tokens: int = 4000
    generation_config: GenerationConfig | None = None
    history_messages: list[dict] | None = None
    skip_intent_classification: bool = False  # retrieval API sets True


@dataclass
class IntentResult:
    intent: str  # knowledge_query | chitchat | conversation_context | general_knowledge | clarification | out_of_scope
    confidence: float  # 0-1
    needs_retrieval: bool
    rewritten_query: str | None = None
    reasoning: str = ""


@dataclass
class ChunkResult:
    chunk_id: str
    document_id: str
    document_version_id: str
    kb_id: str
    kb_name: str
    document_title: str
    chunk_no: int
    content: str
    metadata: dict
    parent_chunk_id: str | None = None
    vector_score: float = 0.0  # normalised 0-1
    keyword_score: float = 0.0  # normalised 0-1
    rerank_score: float | None = None
    final_score: float = 0.0  # normalised 0-1
    retrieval_method: str = "vector"


@dataclass
class RetrievalResult:
    hits: list[ChunkResult]
    latency_ms: int
    strategy: str
    query_rewrite: dict
    rerank_applied: bool
    context_packing_stats: dict | None = None


@dataclass
class GenerationResult(RetrievalResult):
    answer: str = ""
    citations: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    confidence: float | None = None
    rejected: bool = False
    intent: IntentResult | None = None
