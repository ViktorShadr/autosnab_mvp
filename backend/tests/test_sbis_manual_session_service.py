import time

import pytest

from app.services import sbis_manual_session_service as session_service


@pytest.fixture(autouse=True)
def _clear_sessions():
    session_service._SESSIONS.clear()
    yield
    session_service._SESSIONS.clear()


def test_create_and_get_session_round_trip():
    token = session_service.create_session(login="op", password="pw", account_number=None)

    session = session_service.get_session(token)

    assert session.login == "op"
    assert session.password == "pw"


def test_get_session_raises_for_unknown_token():
    with pytest.raises(session_service.SbisManualSessionError):
        session_service.get_session("does-not-exist")


def test_get_session_raises_for_empty_token():
    with pytest.raises(session_service.SbisManualSessionError):
        session_service.get_session(None)


def test_drop_session_invalidates_it():
    token = session_service.create_session(login="op", password="pw", account_number=None)
    session_service.drop_session(token)

    with pytest.raises(session_service.SbisManualSessionError):
        session_service.get_session(token)


def test_idle_session_expires(monkeypatch):
    token = session_service.create_session(login="op", password="pw", account_number=None)
    monkeypatch.setattr(
        session_service, "_SESSION_IDLE_TTL_SECONDS", 0
    )
    stored = session_service._SESSIONS[token]
    stored.last_used_at = time.time() - 10

    with pytest.raises(session_service.SbisManualSessionError):
        session_service.get_session(token)


def test_get_session_returned_object_is_mutable_by_reference():
    token = session_service.create_session(login="op", password="pw", account_number=None)
    session = session_service.get_session(token)

    session.documents_cache = {"doc-1": {"Тип": "ДокОтгрВх"}}

    assert session_service.get_session(token).documents_cache == {"doc-1": {"Тип": "ДокОтгрВх"}}
