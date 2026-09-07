"""V2.0 Embedding 后端（Protocol + Mock）

切真实时只需新增 `OpenAIEmbeddingBackend` / `LocalViTEmbeddingBackend`，
环境变量切换：settings.EMBEDDING_BACKEND = openai | local | mock
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol


class EmbeddingBackend(Protocol):
    """Embedding 后端接口"""
    async def embed_image(self, urls: list[str]) -> list[list[float]]: ...
    async def embed_text(self, text: str) -> list[float]: ...
    @property
    def dim(self) -> int: ...
    @property
    def name(self) -> str: ...


# ============ Mock 后端（PRD §19 默认）============
class MockEmbeddingBackend:
    """确定性 mock embedding

    - 图像：SHA-1(URL) → 取前 16 字节 → 归一化向量
    - 文本：bag-of-words over 16 个固定 token 槽 → TF-IDF 风格 0/1 向量

    同一输入永远返回同一向量（与 MockOrderSource 一致的可重现性原则）。
    """
    name = "mock"
    dim = 16

    _TEXT_TOKENS = [
        "premium", "wireless", "smart", "eco", "portable", "compact", "professional",
        "outdoor", "indoor", "kids", "adults", "multi", "auto", "ultra", "mini", "pro",
    ]

    async def embed_image(self, urls: list[str]) -> list[list[float]]:
        return [self._hash_to_vec(url) for url in urls]

    async def embed_text(self, text: str) -> list[float]:
        text_lower = text.lower()
        vec = [0.0] * self.dim
        for i, token in enumerate(self._TEXT_TOKENS):
            if token in text_lower:
                vec[i] = 1.0
        # 加一点 hash 噪声（确定性）让仅靠 token 不重叠的文本也略有差异
        h = int(hashlib.md5(text.encode()).hexdigest()[:8], 16)
        for i in range(self.dim):
            vec[i] += (h % (i + 7)) / 100.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def _hash_to_vec(self, url: str) -> list[float]:
        h = hashlib.sha1(url.encode()).digest()
        vec = [b / 255.0 - 0.5 for b in h[:self.dim]]  # 中心化
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def get_backend() -> EmbeddingBackend:
    """根据 settings.EMBEDDING_BACKEND 返回实现

    默认 mock；新增真实后端时在此注册。
    """
    from app.core.config import settings
    backend = getattr(settings, "EMBEDDING_BACKEND", "mock")
    if backend == "mock":
        return MockEmbeddingBackend()
    raise NotImplementedError(f"EMBEDDING_BACKEND={backend} 暂未实现，目前仅 mock")