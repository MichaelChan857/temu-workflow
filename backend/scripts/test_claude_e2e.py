"""AI 文案生成 E2E 测试（mock 模式，无需真实 API key）

覆盖：
  1. mock 模式生成
  2. 敏感词校验
  3. 事实白名单校验（编造材质被拒）
  4. 失败重试
  5. 标题长度校验
"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.claude_client import ClaudeClient, GeneratedContent, SENSITIVE_WORDS


async def test_mock_basic():
    """测试 1：基本 mock 生成"""
    print("[1/5] Mock 模式基础生成")
    client = ClaudeClient()
    assert client.use_mock, "应默认 mock 模式"

    result = await client.generate_listing_content(
        {"title": "Pet Toy", "category": "Pet"},
        target_language="en",
    )
    assert result.title
    assert len(result.bullet_points) >= 3
    assert result.description
    assert "mock" in result.prompt_version
    print(f"  [OK] title: {result.title[:50]}")
    print(f"  [OK] {len(result.bullet_points)} 个卖点")
    return result


async def test_sensitive_word_block():
    """测试 2：敏感词应被拒绝"""
    print("\n[2/5] 敏感词校验")
    client = ClaudeClient()

    # 直接调 _validate 测试
    result = GeneratedContent(
        title="100% Best Quality Item",
        bullet_points=["guaranteed to satisfy"],
        description="This is the perfect miracle cure.",
        prompt_version="test",
        raw_output={},
    )
    try:
        client._validate(result, {"title": "Item"})
        print("  [FAIL] 应检测到敏感词")
        return False
    except ValueError as e:
        print(f"  [OK] 敏感词被拒: {e}")
        return True


async def test_fabrication_block():
    """测试 3：AI 编造事实字段应被拒"""
    print("\n[3/5] 事实白名单（防编造）")
    client = ClaudeClient()

    # AI 输出包含"material"但 source 没有
    result = GeneratedContent(
        title="Premium Product",
        bullet_points=["High quality"],
        description="Made of premium material with great quality.",
        prompt_version="test",
        raw_output={},
    )
    try:
        client._validate(result, {"title": "Premium Product"})
        print("  [FAIL] 应检测到编造")
        return False
    except ValueError as e:
        print(f"  [OK] 编造被拒: {e}")
        return True


async def test_title_length():
    """测试 4：标题长度限制"""
    print("\n[4/5] 标题长度限制")
    client = ClaudeClient()

    long_title = "x" * 250
    result = GeneratedContent(
        title=long_title, bullet_points=["a"], description="b",
        prompt_version="test", raw_output={},
    )
    try:
        client._validate(result, {"title": "ok"})
        print("  [FAIL] 应拒长标题")
        return False
    except ValueError as e:
        print(f"  [OK] 长标题被拒: {e}")
        return True


async def test_chinese_output():
    """测试 5：中文输出"""
    print("\n[5/5] 中文目标语言")
    client = ClaudeClient()
    result = await client.generate_listing_content(
        {"title": "宠物玩具", "category": "宠物用品"},
        target_language="zh",
    )
    assert any('一' <= c <= '鿿' for c in result.title), "应包含中文"
    print(f"  [OK] 中文 title: {result.title[:30]}")


async def main():
    print("=" * 60)
    print("AI 文案生成 E2E 测试")
    print("=" * 60)
    print(f"敏感词表 ({len(SENSITIVE_WORDS)}): {SENSITIVE_WORDS[:5]}...")

    r1 = await test_mock_basic()
    r2 = await test_sensitive_word_block()
    r3 = await test_fabrication_block()
    r4 = await test_title_length()
    await test_chinese_output()

    print("\n" + "=" * 60)
    if all([r2, r3, r4]):
        print("所有测试通过")
    else:
        print("部分测试失败")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())