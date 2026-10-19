from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Chunk(StrictModel):
    chunk_id: str
    doc_id: str
    text: str
    page: int | None = None
    section: str = ""
    start: int
    end: int
    source: str
    title: str


class Hit(StrictModel):
    chunk: Chunk
    dense_score: float | None = None
    dense_rank: int | None = None
    bm25_score: float | None = None
    bm25_rank: int | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None


class Query(StrictModel):
    query: str = Field(min_length=1, max_length=4000)
    mode: Literal["dense", "bm25", "hybrid"] = "hybrid"
    rerank: bool = True
    top_k: int = Field(5, ge=1, le=50)
    candidates: int = Field(50, ge=1, le=100)
    doc_ids: list[str] = Field(default_factory=list, max_length=100)


class SearchResult(StrictModel):
    hits: list[Hit]
    mode: Literal["offline", "live"]
    elapsed_ms: float
    index_version: int
    warnings: list[str] = Field(default_factory=list)


class Citation(StrictModel):
    citation_id: str
    chunk_id: str
    doc_id: str
    quote: str = Field(min_length=1)
    page: int | None = None
    section: str = ""
    source: str


class Finding(StrictModel):
    text: str = Field(min_length=1, max_length=8000)
    citation_ids: list[str] = Field(min_length=1, max_length=50)


class Report(StrictModel):
    title: str = Field(min_length=1, max_length=300)
    conclusion: str = Field(min_length=1, max_length=8000)
    findings: list[Finding] = Field(max_length=30)
    disagreements: list[Finding] = Field(default_factory=list, max_length=20)
    limitations: list[str] = Field(default_factory=list, max_length=20)
    citations: list[Citation] = Field(default_factory=list, max_length=50)
    insufficient_evidence: bool = False


class Limits(StrictModel):
    max_steps: int | None = Field(None, ge=1)
    max_llm_calls: int | None = Field(None, ge=1)
    max_tool_calls: int | None = Field(None, ge=1)
    token_budget: int | None = Field(None, ge=1)
    task_timeout: float | None = Field(None, gt=0)


class Research(StrictModel):
    question: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(None, pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    limits: Limits = Field(default_factory=Limits)


class URLImport(StrictModel):
    url: str = Field(min_length=8, max_length=2048)
