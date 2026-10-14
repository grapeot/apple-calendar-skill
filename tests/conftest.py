"""Pytest fixtures: a synthetic offline store discovered via env override."""
import pytest

from fixtures import build_store


@pytest.fixture
def store_dir(tmp_path, monkeypatch):
    """A synthetic store; APPLE_CALENDAR_STORE_DIR points discovery at it.

    The CLI's default group-container path is untouched: no live data is
    read during offline tests.
    """
    from apple_calendar import store

    build_store(tmp_path)
    monkeypatch.setenv(store.STORE_DIR_ENV, str(tmp_path))
    return tmp_path