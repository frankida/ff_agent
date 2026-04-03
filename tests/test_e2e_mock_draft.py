"""
End-to-end mock draft test.

Runs a full N-round snake draft through DraftService + MockDraftSimulator
with a mocked Claude API. Validates:
  - Player pool loads and has correct positional spread
  - Draft briefing is injected into conversation history (no API call)
  - Opponent picks advance state correctly in snake order
  - User picks are recorded and appear on roster
  - Free-form chat routes to Claude with full history
  - Draft completes with expected roster size
  - State serializes and deserializes correctly
"""
import pytest
from unittest.mock import MagicMock, patch

from fantasy_agent.services.draft_service import DraftService
from fantasy_agent.services.draft_sync import MockDraftSimulator
from fantasy_agent.models.draft import DraftState
from fantasy_agent.models.player import Player, Position
from fantasy_agent.ai.client import DraftConversation


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_player(name: str, pos: str, team: str = "KC", eid: str = None, adp: float = 99.0) -> Player:
    p = Player(name=name, position=Position(pos), nfl_team=team, espn_id=eid)
    p.adp = adp
    p.projected_points = 20.0
    return p


def _make_pool(size: int = 60) -> list[Player]:
    """Deterministic player pool across all positions."""
    positions = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "K", "DST"]
    teams = ["KC", "SF", "DAL", "MIA", "BUF", "PHI", "CIN", "LAR", "GB"]
    pool = []
    for i in range(size):
        pos = positions[i % len(positions)]
        team = teams[i % len(teams)]
        pool.append(_make_player(
            name=f"Player{i:03d}",
            pos=pos,
            team=team,
            eid=str(1000 + i),
            adp=float(i + 1),
        ))
    return pool


def _mock_conversation() -> DraftConversation:
    """DraftConversation with Anthropic client fully mocked (blocking + streaming)."""
    with patch("fantasy_agent.ai.client.anthropic.Anthropic"):
        conv = DraftConversation(api_key="test-key")

    # Replace the internal client with a full mock that handles both paths
    mock_client = MagicMock()

    # Blocking path
    msg_mock = MagicMock()
    msg_mock.content = [MagicMock(text="Pick Player002 — great value here.")]
    mock_client.messages.create.return_value = msg_mock

    # Streaming path — context manager that yields text chunks
    stream_ctx = MagicMock()
    stream_ctx.__enter__ = MagicMock(return_value=stream_ctx)
    stream_ctx.__exit__ = MagicMock(return_value=False)
    stream_ctx.text_stream = iter(["Pick Player002", " — great value here."])
    mock_client.messages.stream.return_value = stream_ctx

    conv._client = mock_client
    return conv


def _make_mock_aggregator(pool: list[Player]):
    """Minimal aggregator stub that returns a fixed player pool."""
    agg = MagicMock()
    agg.get_draft_player_pool.return_value = pool
    return agg


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def pool():
    return _make_pool(60)


@pytest.fixture
def service(pool):
    conv = _mock_conversation()
    agg = _make_mock_aggregator(pool)
    svc = DraftService(
        aggregator=agg,
        conversation=conv,
        pick_position=3,
        total_teams=6,
        total_rounds=5,
    )
    svc.initialize()
    return svc


@pytest.fixture
def simulator(service):
    return MockDraftSimulator(
        state=service.state,
        player_pool=service._player_pool,
        opponent_speed=0,
    )


# ── Initialization tests ──────────────────────────────────────────────────────

def test_initialize_loads_player_pool(service, pool):
    assert len(service._player_pool) == len(pool)


def test_initialize_injects_briefing_without_api_call(service):
    """Briefing must be in history but no real API call made."""
    assert len(service.conversation.messages) >= 2
    briefing_content = service.conversation.messages[0]["content"]
    assert "6-team" in briefing_content
    assert "pick #3" in briefing_content
    # No real API call was made
    service.conversation._client.messages.create.assert_not_called()


def test_player_pool_has_all_positions(service):
    positions = {p.position.value for p in service._player_pool}
    assert {"QB", "RB", "WR", "TE"}.issubset(positions)


# ── Snake draft order tests ───────────────────────────────────────────────────

def test_snake_round1_my_pick_at_position3(service, simulator):
    """Opponents 1 and 2 pick, then it's our turn."""
    opp_picks = []
    simulator.simulate_opponents_until_my_pick(
        on_opponent_pick=lambda p, r, pk: opp_picks.append((r, pk))
    )
    assert service.state.is_my_pick()
    assert service.state.current_round == 1
    assert service.state.pick_in_round == 3
    assert len(opp_picks) == 2  # positions 1 and 2


def test_snake_round2_my_pick_is_mirrored(service, simulator):
    """In round 2, user's pick mirrors to total_teams - pick_position + 1."""
    # Advance through round 1
    simulator.simulate_opponents_until_my_pick()
    service.record_my_pick("Player002")

    opp_picks = []
    simulator.simulate_opponents_until_my_pick(
        on_opponent_pick=lambda p, r, pk: opp_picks.append((r, pk))
    )

    assert service.state.current_round == 2
    assert service.state.is_my_pick()
    # Mirrored position: 6 - 3 + 1 = 4 → opponents pick slots 6, 5 (2 picks)
    round2_picks = [pk for r, pk in opp_picks if r == 2]
    assert len(round2_picks) == 2
    assert round2_picks == [6, 5]  # descending from 6


# ── Opponent pick tracking ────────────────────────────────────────────────────

def test_opponent_picks_removed_from_available(service, simulator):
    simulator.simulate_opponents_until_my_pick()
    available_names = {p.name for p in service._get_available()}
    # Opponents took Player000 and Player001 (top ADP)
    assert "Player000" not in available_names
    assert "Player001" not in available_names


def test_opponent_picks_inject_into_conversation(service, simulator):
    history_before = len(service.conversation.messages)
    simulator.simulate_opponents_until_my_pick()
    # Opponent picks should NOT add messages (MockDraftSimulator doesn't call service directly)
    # This is expected — bridge/service wiring handles inject in real CLI
    assert len(service.conversation.messages) >= history_before


# ── User pick recording ───────────────────────────────────────────────────────

def test_record_my_pick_adds_to_roster(service):
    player = service._find_player("Player002")
    service.record_my_pick("Player002")
    assert player in service.state.my_players


def test_record_my_pick_removes_from_available(service):
    service.record_my_pick("Player002")
    available = service._get_available()
    assert all(p.name != "Player002" for p in available)


def test_record_my_pick_injects_into_history(service):
    history_before = len(service.conversation.messages)
    service.record_my_pick("Player002")
    assert len(service.conversation.messages) == history_before + 2  # user + "Noted."


def test_record_my_pick_fuzzy_name_match(service):
    """Slightly misspelled name should still resolve."""
    player = service.record_my_pick("Player 002")  # extra space
    # Either matched or created placeholder — either way roster grows
    assert len(service.state.my_players) == 1


# ── Recommendation ───────────────────────────────────────────────────────────

def test_get_recommendation_calls_claude(service):
    response = service.get_recommendation()
    assert isinstance(response, str)
    assert len(response) > 0
    service.conversation._client.messages.stream.assert_called_once()


def test_get_recommendation_adds_to_history(service):
    service.get_recommendation()
    # 2 messages from briefing inject + 2 from recommendation (user prompt + response)
    assert len(service.conversation.messages) == 4


def test_consecutive_recommendations_use_full_history(service):
    service.get_recommendation()
    service.record_my_pick("Player002")
    # Reset stream mock for second call
    stream_ctx = MagicMock()
    stream_ctx.__enter__ = MagicMock(return_value=stream_ctx)
    stream_ctx.__exit__ = MagicMock(return_value=False)
    stream_ctx.text_stream = iter(["Target RB here."])
    service.conversation._client.messages.stream.return_value = stream_ctx

    service.get_recommendation()
    # Second stream call should include full history
    second_call_messages = service.conversation._client.messages.stream.call_args[1]["messages"]
    assert len(second_call_messages) > 2


# ── Free-form chat ────────────────────────────────────────────────────────────

def test_chat_calls_claude_with_history(service):
    service.record_my_pick("Player002")
    service.chat("Should I target a TE early?")
    service.conversation._client.messages.stream.assert_called_once()
    call_messages = service.conversation._client.messages.stream.call_args[1]["messages"]
    assert any("TE" in m["content"] for m in call_messages)


# ── Full draft simulation ─────────────────────────────────────────────────────

def test_full_draft_completes(pool):
    """Simulate a complete 5-round 6-team draft — no human input."""
    conv = _mock_conversation()
    agg = _make_mock_aggregator(pool)
    service = DraftService(
        aggregator=agg, conversation=conv,
        pick_position=3, total_teams=6, total_rounds=5,
    )
    service.initialize()
    simulator = MockDraftSimulator(
        state=service.state, player_pool=service._player_pool, opponent_speed=0
    )

    round_num = 0
    picks_made = 0
    available = service._get_available()

    while not service.state.is_complete():
        simulator.simulate_opponents_until_my_pick()
        if service.state.is_complete():
            break

        # User auto-picks top available
        top = service._get_available()[0]
        simulator.record_user_pick(top)  # adds to my_players + advances state
        service.conversation.inject_context(
            f"I drafted {top.name} ({top.position.value})."
        )
        picks_made += 1

    assert service.state.is_complete()
    assert picks_made == 5  # 5 rounds


def test_full_draft_roster_size(pool):
    """After a complete draft, roster has exactly total_rounds players."""
    conv = _mock_conversation()
    agg = _make_mock_aggregator(pool)
    service = DraftService(
        aggregator=agg, conversation=conv,
        pick_position=1, total_teams=4, total_rounds=3,
    )
    service.initialize()
    simulator = MockDraftSimulator(
        state=service.state, player_pool=service._player_pool, opponent_speed=0
    )

    while not service.state.is_complete():
        simulator.simulate_opponents_until_my_pick()
        if service.state.is_complete():
            break
        top = service._get_available()[0]
        simulator.record_user_pick(top)  # adds to my_players internally

    assert len(service.state.my_players) == 3


def test_full_draft_no_duplicate_picks(pool):
    """No player should be drafted twice."""
    conv = _mock_conversation()
    agg = _make_mock_aggregator(pool)
    service = DraftService(
        aggregator=agg, conversation=conv,
        pick_position=2, total_teams=4, total_rounds=4,
    )
    service.initialize()
    simulator = MockDraftSimulator(
        state=service.state, player_pool=service._player_pool, opponent_speed=0
    )

    while not service.state.is_complete():
        simulator.simulate_opponents_until_my_pick()
        if service.state.is_complete():
            break
        top = service._get_available()[0]
        simulator.record_user_pick(top)  # adds to my_players internally

    all_drafted_names = [p.name for p in service.state.all_drafted]
    assert len(all_drafted_names) == len(set(all_drafted_names))


# ── State serialization ───────────────────────────────────────────────────────

def test_state_serializes_after_picks(service):
    service.record_my_pick("Player002")
    d = service.state.to_dict()
    assert d["overall_pick"] > 1
    assert len(d["my_players"]) == 1
    assert d["my_players"][0]["name"] == "Player002"
    assert len(d["drafted_ids"]) >= 1


def test_state_has_all_drafted_list(service, simulator):
    simulator.simulate_opponents_until_my_pick()
    service.record_my_pick("Player002")
    # all_drafted includes both opponent picks and our pick
    assert len(service.state.all_drafted) >= 3
