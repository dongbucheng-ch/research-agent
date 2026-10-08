"""推送目标泛化与素材引擎筛选映射(纯函数,不联网)。"""

import pytest
from pydantic import ValidationError

from app.api.routes.items import _engine_channels
from app.schemas.content import PushTriggerIn
from app.services.push import _target_fields


def test_engine_channels_follow_registry() -> None:
    assert _engine_channels("rss") == ["rss", "feed"]
    assert "arxiv" in _engine_channels("news")
    assert "github" in _engine_channels("github")
    assert _engine_channels("unknown") == []


def test_push_trigger_accepts_legacy_digest_id() -> None:
    payload = PushTriggerIn(digest_id=12, channel_id=3)
    assert payload.target_kind == "digest"
    assert payload.target_id == 12


def test_push_trigger_accepts_article_target() -> None:
    payload = PushTriggerIn(target_kind="article", target_id=7, channel_id=3)
    assert payload.target_kind == "article"
    assert payload.target_id == 7


def test_push_trigger_requires_target() -> None:
    with pytest.raises(ValidationError):
        PushTriggerIn(channel_id=3)


def test_target_fields_for_article_uses_topic_as_lead() -> None:
    class FakeArticle:
        title = "生物科技进展"
        topic = "生物科技"
        content_md = "# 正文"
        keywords = ["biotech"]

    assert _target_fields("article", FakeArticle()) == {
        "title": "生物科技进展",
        "lead": "生物科技",
        "content_md": "# 正文",
        "highlights": ["biotech"],
    }


def test_target_fields_for_digest_uses_lead_and_highlights() -> None:
    class FakeDigest:
        title = "研讯日报"
        lead = "今日导语"
        content_md = "# 正文"
        highlights = ["h1", "h2"]

    assert _target_fields("digest", FakeDigest()) == {
        "title": "研讯日报",
        "lead": "今日导语",
        "content_md": "# 正文",
        "highlights": ["h1", "h2"],
    }
