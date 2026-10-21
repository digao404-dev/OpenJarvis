from pathlib import Path
from unittest.mock import patch

import pytest

from openjarvis.aily_actions import approve, get, prepare


def test_note_requires_approval_and_is_verified(tmp_path: Path):
    db = tmp_path / "actions.sqlite3"
    vault = tmp_path / "vault"
    action = prepare("note", {"title": "Decisão", "body": "Usar o vault."}, db)
    assert not (vault / "Inbox").exists()
    result = approve(action["id"], db, vault)
    assert result["verified"]
    assert Path(result["path"]).read_text() == "# Decisão\n\nUsar o vault.\n"
    assert get(action["id"], db)["state"] == "completed"
    with pytest.raises(ValueError):
        approve(action["id"], db, vault)


def test_calendar_validates_timezone_and_verifies_event(tmp_path: Path):
    db = tmp_path / "actions.sqlite3"
    payload = {
        "title": "Consulta",
        "start": "2026-10-22T09:00:00-03:00",
        "end": "2026-10-22T10:00:00-03:00",
    }
    with pytest.raises(ValueError):
        prepare("calendar_event", {**payload, "start": "2026-10-22T09:00:00"}, db)
    action = prepare("calendar_event", payload, db)
    assert get(action["id"], db)["state"] == "pending"

    class Response:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self.data

    with (
        patch(
            "openjarvis.connectors.oauth.load_tokens",
            return_value={"access_token": "test"},
        ),
        patch(
            "openjarvis.connectors.google_auth.call_with_refresh",
            side_effect=lambda fn, _: fn("test"),
        ),
        patch(
            "openjarvis.aily_actions.httpx.post",
            return_value=Response({"id": "event-1"}),
        ) as post,
        patch(
            "openjarvis.aily_actions.httpx.get",
            return_value=Response(
                {"id": "event-1", "htmlLink": "https://calendar.example/e"}
            ),
        ) as read,
    ):
        result = approve(action["id"], db, credentials_path="test.json")
    assert result == {
        "id": "event-1",
        "url": "https://calendar.example/e",
        "verified": True,
    }
    assert post.call_args.kwargs["json"]["summary"] == "Consulta"
    assert read.call_args.args[0].endswith("/event-1")
    assert get(action["id"], db)["state"] == "completed"
