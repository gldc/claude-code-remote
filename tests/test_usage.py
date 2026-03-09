import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from claude_code_remote.usage import UsageClient, get_oauth_token
from claude_code_remote.models import UsageData


@pytest.fixture
def usage_client(tmp_path):
    return UsageClient(tmp_path / "history.jsonl")


def test_get_oauth_token_file(tmp_path, monkeypatch):
    creds = tmp_path / "creds.json"
    creds.write_text('{"access_token": "test-token"}')
    monkeypatch.setattr("claude_code_remote.usage.CREDENTIALS_FILE", creds)
    monkeypatch.setattr("claude_code_remote.usage._read_keychain", lambda: None)
    assert get_oauth_token() == "test-token"


def test_parse_usage(usage_client):
    data = {
        "five_hour": {"percent_remaining": 97, "resets_in_seconds": 10500},
        "seven_day": {
            "percent_remaining": 88,
            "reserve_percent": 7,
            "resets_in_seconds": 460500,
        },
        "seven_day_sonnet": {"percent_remaining": 93, "resets_in_seconds": 46500},
        "extra_usage": {"monthly_spend": 0, "monthly_limit": 50},
        "rate_limit_tier": "Max",
    }
    usage = usage_client._parse_usage(data)
    assert usage.session.percent_remaining == 97
    assert usage.weekly.reserve_percent == 7
    assert usage.sonnet.percent_remaining == 93
    assert usage.plan_tier == "Max"


@pytest.mark.asyncio
async def test_cache_ttl(usage_client):
    """Second call within TTL returns cached data."""
    mock_data = {"five_hour": {"percent_remaining": 50, "resets_in_seconds": 100}}

    mock_response = MagicMock()
    mock_response.json.return_value = mock_data
    mock_response.raise_for_status = MagicMock()

    call_count = 0

    async def mock_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return mock_response

    with patch("claude_code_remote.usage.get_oauth_token", return_value="tok"):
        with patch("httpx.AsyncClient.get", side_effect=mock_get):
            r1 = await usage_client.get_usage()
            r2 = await usage_client.get_usage()
            assert call_count == 1  # Cached
            assert r1.session.percent_remaining == 50


@pytest.mark.asyncio
async def test_no_token_returns_empty(usage_client):
    """Returns empty UsageData when no token available."""
    with patch("claude_code_remote.usage.get_oauth_token", return_value=None):
        result = await usage_client.get_usage()
        assert result.plan_tier == "unknown"


@pytest.mark.asyncio
async def test_history_write_and_read(usage_client):
    """Test writing and reading history."""
    usage = UsageData()
    usage.plan_tier = "Max"
    await usage_client._append_history(usage)

    history = await usage_client.get_history(days=1)
    assert len(history) == 1
    assert history[0].plan_tier == "Max"
