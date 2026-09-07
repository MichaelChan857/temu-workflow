"""V2.0 相似商品聚类去重（PRD FR-021 / V2_PLAN §2.4）

仅用于"阻断重复发布"，不参与评分（同聚类一刀切会误伤差异化选品）。

阈值默认 0.95：mock SHA-1 强一致 + 仅同图同标题同来源才触发。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CandidateStatus, ListingDraft
from app.services.embedding_backends import get_backend


# ============ 数学 ============
def cosine(a: list[float], b: list[float]) -> float:
    """余弦相似度；返回 [-1, 1]"""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1e-9
    nb = math.sqrt(sum(y * y for y in b)) or 1e-9
    return dot / (na * nb)


def _vec_avg(vecs: list[list[float]]) -> list[float]:
    """多向量平均（用于多图 embedding 聚合）"""
    if not vecs:
        return []
    dim = len(vecs[0])
    out = [0.0] * dim
    for v in vecs:
        for i, x in enumerate(v):
            out[i] += x
    n = len(vecs)
    return [x / n for x in out]


# ============ 结果 ============
@dataclass
class DuplicateHit:
    listing_id: UUID
    title: str
    image_similarity: float
    text_similarity: float
    similarity: float  # 加权综合分（图像 0.6 + 文本 0.4）

    def to_dict(self) -> dict:
        return {
            "listing_id": str(self.listing_id),
            "title": self.title,
            "image_similarity": round(self.image_similarity, 3),
            "text_similarity": round(self.text_similarity, 3),
            "similarity": round(self.similarity, 3),
        }


# ============ 主入口 ============
async def find_duplicates(
    db: AsyncSession,
    shop_id: UUID,
    exclude_listing_id: UUID,
    image_urls: list[str],
    title: str,
    threshold: float = 0.95,
) -> list[dict]:
    """在同 shop 的 [READY_TO_PUBLISH, PUBLISHING, PUBLISHED] 状态 listing 中找重复

    Returns: 按综合相似度降序的 hit 列表（最多 3 个）
    """
    backend = get_backend()

    # 1. 算当前 listing 的 embedding
    img_vec = _vec_avg(await backend.embed_image(image_urls)) if image_urls else []
    txt_vec = await backend.embed_text(title)

    # 2. 拉候选
    rows = (await db.execute(
        select(ListingDraft.id, ListingDraft.title, ListingDraft.image_urls)
        .where(ListingDraft.shop_id == shop_id)
        .where(ListingDraft.id != exclude_listing_id)
        .where(ListingDraft.status.in_([
            CandidateStatus.READY_TO_PUBLISH,
            CandidateStatus.PUBLISHING,
            CandidateStatus.PUBLISHED,
        ]))
    )).all()

    if not rows:
        return []

    # 3. 比对
    hits: list[DuplicateHit] = []
    for r in rows:
        cand_imgs = r.image_urls or []
        cand_img_vec = _vec_avg(await backend.embed_image(cand_imgs)) if cand_imgs else []
        cand_txt_vec = await backend.embed_text(r.title or "")

        img_sim = cosine(img_vec, cand_img_vec) if img_vec and cand_img_vec else 0.0
        txt_sim = cosine(txt_vec, cand_txt_vec) if txt_vec and cand_txt_vec else 0.0
        combined = 0.6 * img_sim + 0.4 * txt_sim

        if combined >= threshold:
            hits.append(DuplicateHit(
                listing_id=r.id,
                title=r.title or "",
                image_similarity=img_sim,
                text_similarity=txt_sim,
                similarity=combined,
            ))

    hits.sort(key=lambda h: h.similarity, reverse=True)
    return [h.to_dict() for h in hits[:3]]