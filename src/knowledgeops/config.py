from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KO_", env_file=".env", extra="ignore")
    mode: Literal["offline", "live"] = "offline"
    data_dir: Path = Path("data")
    api_key: SecretStr = SecretStr("offline-local-only")
    llm_provider: Literal["auto", "mock", "openai", "deepseek"] = "auto"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = ""
    deepseek_api_key: SecretStr = Field(default=SecretStr(""),
        validation_alias=AliasChoices("DEEPSEEK_API_KEY", "KO_DEEPSEEK_API_KEY"))
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    deepseek_temperature: float = Field(0.0, ge=0, le=2)
    llm_timeout: float | None = Field(None, gt=0, le=180)
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_api_key: SecretStr = SecretStr("")
    embedding_model: str = ""
    embedding_provider: Literal['auto', 'mock', 'api', 'local'] = 'auto'
    embedding_device: Literal['cpu', 'cuda'] = 'cpu'
    embedding_precision: Literal['float32', 'float16'] = 'float32'
    embedding_batch_size: int = Field(8, ge=1, le=128)
    embedding_revision: str | None = None
    embedding_model_path: Path | None = None
    embedding_normalize: bool = True
    embedding_max_length: int = Field(512, ge=32, le=8192)
    models_local_only: bool = False
    model_threads: int = Field(8, ge=1, le=64)
    model_load_timeout: float = Field(600, gt=0)
    reranker_provider: Literal['auto', 'mock', 'cross_encoder'] = 'auto'
    reranker_revision: str | None = None
    reranker_model_path: Path | None = None
    reranker_max_length: int = Field(512, ge=32, le=8192)
    qdrant_backend: Literal['auto', 'local', 'server'] = 'auto'
    qdrant_collection: str = Field('knowledgeops_v1', pattern=r'^[a-zA-Z0-9_-]{1,80}$')
    embedding_dimensions: int = Field(1536, ge=8, le=65536)
    reranker_model: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    reranker_device: Literal["cpu", "cuda"] = "cpu"
    reranker_precision: Literal['float32', 'float16'] = 'float32'
    reranker_batch_size: int = Field(8, ge=1, le=64)
    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: SecretStr = SecretStr("")
    redis_url: str = "redis://redis:6379/0"
    chunk_size: int = Field(800, ge=100, le=4000)
    chunk_overlap: int = Field(120, ge=0)
    max_upload_bytes: int = Field(20 * 1024 * 1024, ge=1024)
    max_pdf_pages: int = Field(300, ge=1)
    max_steps: int = Field(12, ge=1, le=100)
    max_llm_calls: int = Field(8, ge=1, le=50)
    max_tool_calls: int = Field(12, ge=1, le=100)
    max_search_calls: int = Field(4, ge=1, le=100)
    token_budget: int = Field(20000, ge=1000)
    output_tokens: int = Field(2000, ge=100)
    task_timeout: float = Field(180, gt=0)
    tool_timeout: float = Field(30, gt=0)
    max_retries: int = Field(2, ge=0, le=2)
    lease_seconds: float = Field(30, ge=1)
    poll_seconds: float = Field(0.3, gt=0)
    langfuse_public_key: str = ""
    langfuse_secret_key: SecretStr = SecretStr("")
    langfuse_base_url: str = "https://cloud.langfuse.com"

    @model_validator(mode="after")
    def validate_settings(self):
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        provider = self.resolved_llm_provider
        if provider == 'deepseek':
            if not self.deepseek_api_key.get_secret_value():
                raise ValueError('DEEPSEEK_API_KEY is required for the deepseek provider')
            if self.deepseek_base_url.rstrip('/') != 'https://api.deepseek.com':
                raise ValueError('DeepSeek provider requires the official HTTPS endpoint')
            if not self.deepseek_model:
                raise ValueError('KO_DEEPSEEK_MODEL is required')
        if provider == 'openai' and (not self.llm_api_key.get_secret_value() or not self.llm_model):
            raise ValueError('KO_LLM_API_KEY and KO_LLM_MODEL are required for the openai provider')
        if self.mode == "live":
            if provider == 'mock':
                raise ValueError('Mock LLM is not permitted in full live mode')
            if self.resolved_embedding_provider == 'mock' or self.resolved_reranker_provider == 'mock':
                raise ValueError('Mock retrieval is not permitted in full live mode')
            if self.resolved_qdrant_backend != 'server':
                raise ValueError('Full live mode requires Qdrant Server')
            if self.resolved_embedding_provider == 'api' and (not self.embedding_api_key.get_secret_value() or not self.embedding_model):
                raise ValueError("KO_EMBEDDING_API_KEY and KO_EMBEDDING_MODEL are required in live mode")
            if self.api_key.get_secret_value() in ("", "offline-local-only"):
                raise ValueError("Set a private KO_API_KEY in live mode")
        if self.resolved_embedding_provider == 'local' and not self.embedding_model:
            raise ValueError('KO_EMBEDDING_MODEL is required for local embeddings')
        return self

    @property
    def resolved_embedding_provider(self):
        return ('api' if self.mode == 'live' else 'mock') if self.embedding_provider == 'auto' else self.embedding_provider

    @property
    def resolved_reranker_provider(self):
        return ('cross_encoder' if self.mode == 'live' else 'mock') if self.reranker_provider == 'auto' else self.reranker_provider

    @property
    def resolved_qdrant_backend(self):
        return ('server' if self.mode == 'live' else 'local') if self.qdrant_backend == 'auto' else self.qdrant_backend

    @property
    def resolved_llm_provider(self):
        if self.llm_provider != 'auto':
            return self.llm_provider
        return 'openai' if self.mode == 'live' else 'mock'
