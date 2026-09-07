"""Claude API 客户端 — 文案生成

W4-D1：
- mock 模式（开发/测试用，不消耗 token）
- 真实模式（生产环境调 Anthropic API）
- 结构化输出（JSON）+ 失败重试（最多 3 次）
- 事实白名单校验（禁止凭空编造规格/材质/认证）

PRD FR-050 ~ 052 / FR-055 / FR-051
"""
import json
import os
import re
from typing import Optional
from dataclasses import dataclass
import httpx

from app.core.config import settings


# 提示词版本（W4 默认；后续版本化）
PROMPT_VERSION = "v1.0"

# 系统提示词（PRD §8.4：AI 不得伪造事实字段）
SYSTEM_PROMPT = """你是 Temu 跨境电商的商品文案助手。你的任务是基于【已确认的商品信息】生成目标语言的标题、卖点和描述。

【严格规则】
1. 只能基于"已确认商品信息"中的内容生成文案，不得凭空编造任何事实字段，包括但不限于：
   - 材质（material / composition）
   - 规格（size / weight / capacity）
   - 功效（function / efficacy）
   - 认证（certification / authorization）
   - 品牌授权（brand license）
   - 产地（origin / made in）
2. 若信息中未提供某字段，标 "待补充"，不得猜测。
3. 标题长度控制在目标站点限制内（默认 100 字符内）。
4. 不使用敏感词、夸大宣传、绝对化用语。
5. 输出必须为 JSON 格式，包含 title, bullet_points (3-5 条), description (3-5 句话)。

【输出格式】
{
  "title": "...",
  "bullet_points": ["...", "...", "..."],
  "description": "..."
}
"""


# 敏感词（PRD FR-055）
SENSITIVE_WORDS = [
    "best", "guaranteed", "100%", "cure", "miracle", "perfect",
    "最强", "保证", "100%", "治愈", "神奇", "完美", "绝对",
]


@dataclass
class GeneratedContent:
    title: str
    bullet_points: list[str]
    description: str
    prompt_version: str
    raw_output: dict
    llm_tokens_in: int = 0
    llm_tokens_out: int = 0


class ClaudeClient:
    """Claude API 客户端 — 含 mock 模式"""

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-sonnet-4-5-20250929"):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.model = model
        self.base_url = "https://api.anthropic.com/v1"
        self.use_mock = not self.api_key or settings.DEBUG  # debug 模式默认 mock

    async def generate_listing_content(
        self,
        source_info: dict,
        target_language: str = "en",
        max_retries: int = 3,
    ) -> GeneratedContent:
        """生成上品资料

        Args:
            source_info: 已确认的商品信息
                {title, description, category, brand, attributes, ...}
            target_language: 目标语言
            max_retries: 失败重试次数

        Returns:
            GeneratedContent

        Raises:
            RuntimeError: 多次重试仍失败
            ValueError: 输出格式错误或违反白名单
        """
        if self.use_mock:
            return self._mock_generate(source_info, target_language)

        # 真实 API（带重试）
        user_prompt = self._build_user_prompt(source_info, target_language)
        last_error = None
        for attempt in range(max_retries):
            try:
                result = await self._call_api(user_prompt)
                self._validate(result, source_info)
                return result
            except (ValueError, json.JSONDecodeError) as e:
                last_error = e
                continue
            except httpx.HTTPError as e:
                last_error = e
                if attempt < max_retries - 1:
                    continue
                raise RuntimeError(f"Claude API failed after {max_retries} retries: {e}")
        raise RuntimeError(f"Failed to generate valid content after {max_retries} retries: {last_error}")

    def _build_user_prompt(self, info: dict, lang: str) -> str:
        return f"""目标语言：{lang}

【已确认的商品信息】
{json.dumps(info, ensure_ascii=False, indent=2)}

请基于以上信息生成上品文案。"""

    async def _call_api(self, user_prompt: str) -> GeneratedContent:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.base_url}/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": 1024,
                    "system": SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": user_prompt}],
                },
            )
            resp.raise_for_status()
            data = resp.json()

        # 解析 Claude 响应
        content_text = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                content_text += block["text"]

        # 提取 JSON
        json_match = re.search(r"\{.*\}", content_text, re.DOTALL)
        if not json_match:
            raise ValueError(f"no JSON in response: {content_text[:200]}")

        parsed = json.loads(json_match.group())

        return GeneratedContent(
            title=parsed.get("title", ""),
            bullet_points=parsed.get("bullet_points", []),
            description=parsed.get("description", ""),
            prompt_version=PROMPT_VERSION,
            raw_output=parsed,
            llm_tokens_in=data.get("usage", {}).get("input_tokens", 0),
            llm_tokens_out=data.get("usage", {}).get("output_tokens", 0),
        )

    def _validate(self, result: GeneratedContent, source: dict):
        """校验 AI 输出（PRD §8.4 / FR-051）"""
        # 1. 必填字段
        if not result.title or not result.bullet_points or not result.description:
            raise ValueError("missing required fields in AI output")

        # 2. 事实白名单（不得编造 source 没有的"规格类"关键词）
        suspicious = ["material", "weight", "size", "capacity", "voltage", "wattage", "材质", "规格", "功率"]
        source_text = json.dumps(source, ensure_ascii=False).lower()
        for word in suspicious:
            # 如果 AI 输出包含该词但 source 没有 → 可能是编造
            if word in result.title.lower() or word in result.description.lower():
                if word not in source_text:
                    raise ValueError(f"AI output contains '{word}' but source doesn't — possible fabrication")

        # 3. 敏感词
        full_text = result.title + " " + " ".join(result.bullet_points) + " " + result.description
        for sw in SENSITIVE_WORDS:
            if sw in full_text.lower():
                raise ValueError(f"sensitive word detected: '{sw}'")

        # 4. 标题长度
        if len(result.title) > 200:
            raise ValueError(f"title too long: {len(result.title)} chars")

    def _mock_generate(self, source: dict, lang: str) -> GeneratedContent:
        """Mock 模式 — 开发/测试用"""
        title = source.get("title", "Unknown Product")
        if lang == "zh":
            title_zh = f"{title} - 优质商品"
            bullets = ["高品质材料", "精美工艺", "实用设计", "性价比高"]
            desc = f"这是一款{title}。设计精美，实用性强，适合日常使用。"
        else:
            title_zh = f"{title} - Premium Quality"
            bullets = [
                "High quality construction",
                "Elegant design",
                "Practical and versatile",
                "Great value for money",
            ]
            desc = f"This is a {title}. Features elegant design and practical functionality for daily use."

        return GeneratedContent(
            title=title_zh[:100],
            bullet_points=bullets,
            description=desc,
            prompt_version=PROMPT_VERSION + "-mock",
            raw_output={"title": title_zh, "bullet_points": bullets, "description": desc, "mock": True},
            llm_tokens_in=0,
            llm_tokens_out=0,
        )


# 单例
claude_client = ClaudeClient()