"""Settings는 API 키 없이도 import/인스턴스화되어야 한다."""

import pytest

from core.config import Settings


def test_settings_allows_empty_anthropic_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    loaded = Settings(_env_file=None)
    assert loaded.anthropic_api_key == ""
    assert loaded.claude_model_default
