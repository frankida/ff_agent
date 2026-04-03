"""Tests for DraftConversation and draft briefing context helpers."""
import pytest
from unittest.mock import MagicMock, patch

from fantasy_agent.ai.client import DraftConversation, TOKEN_WARNING_THRESHOLD
from fantasy_agent.ai.context import build_draft_briefing, build_opponent_picks_summary
from fantasy_agent.models.player import Player, Position


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_player(name: str, pos: str, team: str = "KC", pts: float = 15.0) -> Player:
    p = Player(name=name, position=Position(pos), nfl_team=team)
    p.projected_points = pts
    return p


@pytest.fixture
def mock_client():
    """Returns a DraftConversation with a mocked Anthropic client."""
    with patch("fantasy_agent.ai.client.anthropic.Anthropic") as MockAnthropic:
        instance = MockAnthropic.return_value
        # Default blocking response
        msg_mock = MagicMock()
        msg_mock.content = [MagicMock(text="Draft CMC — elite RB, great value here.")]
        instance.messages.create.return_value = msg_mock
        conv = DraftConversation(api_key="test-key")
        conv._client = instance
        yield conv


# ── DraftConversation tests ───────────────────────────────────────────────────

def test_send_appends_messages(mock_client):
    mock_client.send("Who should I pick at 5?", stream=False)
    assert len(mock_client.messages) == 2
    assert mock_client.messages[0]["role"] == "user"
    assert mock_client.messages[1]["role"] == "assistant"


def test_send_accumulates_history(mock_client):
    mock_client.send("Who at pick 5?", stream=False)
    mock_client.send("What about RBs?", stream=False)
    assert len(mock_client.messages) == 4
    assert mock_client.messages[2]["role"] == "user"
    assert mock_client.messages[2]["content"] == "What about RBs?"


def test_send_returns_response_text(mock_client):
    result = mock_client.send("Pick advice?", stream=False)
    assert result == "Draft CMC — elite RB, great value here."


def test_inject_context_no_api_call(mock_client):
    mock_client.inject_context("Opponents picked: Josh Allen (QB, BUF)")
    # No API call should have been made
    mock_client._client.messages.create.assert_not_called()


def test_inject_context_adds_to_history(mock_client):
    mock_client.inject_context("Opponent took Justin Jefferson.")
    assert len(mock_client.messages) == 2
    assert mock_client.messages[0]["role"] == "user"
    assert mock_client.messages[1] == {"role": "assistant", "content": "Noted."}


def test_inject_context_visible_in_subsequent_send(mock_client):
    mock_client.inject_context("Opponent took Ja'Marr Chase.")
    mock_client.send("Should I pivot to RB?", stream=False)
    # Full history (inject pair + real send pair) sent to API
    call_messages = mock_client._client.messages.create.call_args[1]["messages"]
    assert any("Ja'Marr Chase" in m["content"] for m in call_messages)


def test_token_estimate_grows_with_history(mock_client):
    assert mock_client.get_token_estimate() == 0
    mock_client.inject_context("x" * 400)  # inject 400 chars
    estimate = mock_client.get_token_estimate()
    # 400 chars / 4 = 100 tokens (user msg) + "Noted." ~= 101
    assert estimate >= 100


def test_token_warning_printed(mock_client, capsys):
    # Fill history with enough content to exceed threshold
    large_content = "a" * (TOKEN_WARNING_THRESHOLD * 4 + 100)
    mock_client.inject_context(large_content)
    mock_client.send("any question?", stream=False)
    captured = capsys.readouterr()
    assert "Warning" in captured.out


# ── build_draft_briefing tests ────────────────────────────────────────────────

def test_briefing_contains_league_info():
    players = [_make_player("CMC", "RB"), _make_player("Justin Jefferson", "WR")]
    result = build_draft_briefing(
        total_teams=12, pick_position=5, scoring="std", top_available=players
    )
    assert "12-team" in result
    assert "pick #5" in result
    assert "Standard" in result


def test_briefing_lists_players():
    players = [_make_player("CMC", "RB"), _make_player("Tyreek Hill", "WR")]
    result = build_draft_briefing(
        total_teams=10, pick_position=1, scoring="ppr", top_available=players
    )
    assert "CMC" in result
    assert "Tyreek Hill" in result


def test_briefing_respects_top_n():
    players = [_make_player(f"Player{i}", "RB") for i in range(50)]
    result = build_draft_briefing(
        total_teams=12, pick_position=3, scoring="std", top_available=players, top_n=10
    )
    assert "Player0" in result
    assert "Player10" not in result


# ── build_opponent_picks_summary tests ───────────────────────────────────────

def test_opponent_summary_empty():
    result = build_opponent_picks_summary([])
    assert "No new" in result


def test_opponent_summary_lists_players():
    picks = [_make_player("Josh Allen", "QB", "BUF"), _make_player("Davante Adams", "WR", "LV")]
    result = build_opponent_picks_summary(picks)
    assert "Josh Allen" in result
    assert "Davante Adams" in result
    assert "QB" in result
    assert "WR" in result
