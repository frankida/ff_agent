"""Tests for the SQLite TTL cache."""
import time
import pytest
from unittest.mock import patch
from pathlib import Path


@pytest.fixture(autouse=True)
def temp_cache(tmp_path, monkeypatch):
    """Redirect cache DB to a temp directory for each test."""
    import fantasy_agent.cache.manager as manager_mod
    temp_db = tmp_path / "test_cache.db"
    monkeypatch.setattr(manager_mod, "CACHE_DB", temp_db)
    monkeypatch.setattr(manager_mod, "CACHE_DIR", tmp_path)
    yield temp_db


class TestCacheDecorator:
    def test_caches_return_value(self):
        from fantasy_agent.cache.manager import cache

        call_count = 0

        class Dummy:
            @cache(ttl_seconds=60)
            def fetch(self, key: str) -> str:
                nonlocal call_count
                call_count += 1
                return f"result-{key}"

        d = Dummy()
        r1 = d.fetch("abc")
        r2 = d.fetch("abc")
        assert r1 == "result-abc"
        assert r2 == "result-abc"
        assert call_count == 1  # called only once

    def test_different_args_get_different_entries(self):
        from fantasy_agent.cache.manager import cache

        class Dummy:
            @cache(ttl_seconds=60)
            def fetch(self, key: str) -> str:
                return f"result-{key}"

        d = Dummy()
        assert d.fetch("a") == "result-a"
        assert d.fetch("b") == "result-b"

    def test_expired_entry_calls_function_again(self):
        from fantasy_agent.cache.manager import cache

        call_count = 0

        class Dummy:
            @cache(ttl_seconds=1)
            def fetch(self) -> str:
                nonlocal call_count
                call_count += 1
                return "fresh"

        d = Dummy()
        d.fetch()
        assert call_count == 1

        # Manually expire by patching time
        with patch("fantasy_agent.cache.manager.time") as mock_time:
            mock_time.time.return_value = time.time() + 10  # 10s in the future
            d.fetch()

        assert call_count == 2

    def test_clear_cache_empties_db(self):
        from fantasy_agent.cache.manager import cache, clear_cache, cache_status

        class Dummy:
            @cache(ttl_seconds=60)
            def fetch(self, x: int) -> int:
                return x * 2

        d = Dummy()
        d.fetch(1)
        d.fetch(2)

        status_before = cache_status()
        assert status_before["total_entries"] == 2

        clear_cache()
        status_after = cache_status()
        assert status_after["total_entries"] == 0

    def test_cache_status_returns_correct_counts(self):
        from fantasy_agent.cache.manager import cache, cache_status

        class Dummy:
            @cache(ttl_seconds=3600)
            def fetch(self, n: int) -> int:
                return n

        d = Dummy()
        d.fetch(1)
        d.fetch(2)
        d.fetch(3)

        status = cache_status()
        assert status["total_entries"] == 3
        assert status["active_entries"] == 3
        assert status["expired_entries"] == 0

    def test_returns_none_gracefully(self):
        from fantasy_agent.cache.manager import cache

        class Dummy:
            @cache(ttl_seconds=60)
            def fetch(self) -> None:
                return None

        d = Dummy()
        assert d.fetch() is None
        # Second call should use cache (not raise)
        assert d.fetch() is None
