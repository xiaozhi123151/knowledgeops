import hashlib
import re

import jieba
import numpy as np
from openai import AsyncOpenAI


def tokenize(text):
    words = re.findall(r"[a-z0-9_]+|[\u3400-\u9fff]+", text.lower())
    return [t for word in words for t in (jieba.lcut(word) if re.search(r'[\u3400-\u9fff]', word) else [word]) if t.strip()]


class HashEmbedding:
    """Test double: token hashing is NOT a semantic embedding model."""
    dimensions = 256
    name = 'offline-hash-v1'

    async def embed(self, texts):
        vectors = []
        for text in texts:
            v = np.zeros(self.dimensions, dtype=np.float32)
            for word in tokenize(text):
                h = int.from_bytes(hashlib.sha256(word.encode()).digest()[:8], 'big')
                v[h % self.dimensions] += 1
            norm = np.linalg.norm(v)
            vectors.append((v / norm if norm else v).tolist())
        return vectors

    async def close(self):
        pass


class APIEmbedding:
    def __init__(self, settings):
        self.name = settings.embedding_model
        self.dimensions = settings.embedding_dimensions
        self.client = AsyncOpenAI(api_key=settings.embedding_api_key.get_secret_value(),
                                  base_url=settings.embedding_base_url, timeout=30, max_retries=0)

    async def embed(self, texts):
        vectors = []
        for start in range(0, len(texts), 32):
            response = await self.client.embeddings.create(model=self.name, input=texts[start:start + 32])
            batch = sorted(response.data, key=lambda x: x.index)
            if len(batch) != len(texts[start:start + 32]):
                raise ValueError('EMBEDDING_COUNT_MISMATCH')
            for item in batch:
                if len(item.embedding) != self.dimensions or not np.isfinite(item.embedding).all():
                    raise ValueError('EMBEDDING_DIMENSION_OR_VALUE_MISMATCH')
                vectors.append(item.embedding)
        return vectors

    async def close(self):
        await self.client.close()
