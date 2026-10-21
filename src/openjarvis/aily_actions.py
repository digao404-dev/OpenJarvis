"""Explicitly approved, locally audited AILY writes."""

from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx

from openjarvis.aily_vault.search import DEFAULT_VAULT

DEFAULT_ACTIONS_DB = Path(
    os.environ.get("AILY_ACTIONS_DB", "~/.local/state/aily-platform/actions.sqlite3")
).expanduser()


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _connect(path: Path = DEFAULT_ACTIONS_DB) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS actions (
        id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL,
        state TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        result TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS action_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, action_id TEXT NOT NULL,
        event TEXT NOT NULL, at TEXT NOT NULL, detail TEXT)""")
    return db


def _validate(kind: str, payload: dict) -> dict:
    if kind == "note":
        title = str(payload.get("title", "")).strip()
        body = str(payload.get("body", "")).strip()
        if not title or not body or len(title) > 160 or len(body) > 20000:
            raise ValueError(
                "Nota exige título (até 160 caracteres) e corpo (até 20.000)."
            )
        return {"title": title, "body": body}
    if kind == "calendar_event":
        title = str(payload.get("title", "")).strip()
        if not title or len(title) > 160:
            raise ValueError("Evento exige título de até 160 caracteres.")
        start = dt.datetime.fromisoformat(str(payload.get("start", "")))
        end = dt.datetime.fromisoformat(str(payload.get("end", "")))
        if start.tzinfo is None or end.tzinfo is None or end <= start:
            raise ValueError(
                "Início/fim exigem fuso horário explícito e fim após início."
            )
        calendar_id = str(payload.get("calendar_id", "primary")).strip()
        if not calendar_id or len(calendar_id) > 200:
            raise ValueError("calendar_id inválido.")
        description = str(payload.get("description", "")).strip()
        if len(description) > 10000:
            raise ValueError("Descrição muito longa.")
        return {
            "title": title,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "description": description,
            "calendar_id": calendar_id,
        }
    raise ValueError(f"Ação não suportada: {kind}")


def prepare(kind: str, payload: dict, db_path: Path = DEFAULT_ACTIONS_DB) -> dict:
    data = _validate(kind, payload)
    action_id = uuid.uuid4().hex[:16]
    now = _now()
    with _connect(db_path) as db:
        db.execute(
            "INSERT INTO actions VALUES (?,?,?,?,?,?,?)",
            (
                action_id,
                kind,
                json.dumps(data, ensure_ascii=False),
                "pending",
                now,
                now,
                None,
            ),
        )
        db.execute(
            "INSERT INTO action_events(action_id,event,at) VALUES (?,?,?)",
            (action_id, "prepared", now),
        )
    return {"id": action_id, "kind": kind, "payload": data, "state": "pending"}


def get(action_id: str, db_path: Path = DEFAULT_ACTIONS_DB) -> dict | None:
    with _connect(db_path) as db:
        row = db.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        data["payload"] = json.loads(data["payload"])
        return data


def list_pending(db_path: Path = DEFAULT_ACTIONS_DB) -> list[dict]:
    with _connect(db_path) as db:
        ids = [
            r["id"]
            for r in db.execute(
                "SELECT id FROM actions WHERE state='pending' ORDER BY created_at"
            )
        ]
    return [get(action_id, db_path) for action_id in ids]


def _write_note(action_id: str, payload: dict, vault: Path) -> dict:
    target_dir = vault.expanduser().resolve() / "Inbox" / "AILY"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{action_id}.md"
    if target.exists():
        raise FileExistsError(f"Nota já existe: {target}")
    title = payload["title"].replace("\n", " ").replace("\r", " ")
    content = f"# {title}\n\n{payload['body']}\n"
    with target.open("x", encoding="utf-8") as stream:
        stream.write(content)
    if target.read_text(encoding="utf-8") != content:
        raise OSError("Verificação da nota falhou.")
    return {"path": str(target), "verified": True}


def _create_calendar_event(
    action_id: str, payload: dict, credentials_path: str | None
) -> dict:
    from openjarvis.connectors.gcalendar import _DEFAULT_CREDENTIALS_PATH
    from openjarvis.connectors.google_auth import call_with_refresh
    from openjarvis.connectors.oauth import load_tokens, resolve_google_credentials

    credentials = resolve_google_credentials(
        credentials_path or _DEFAULT_CREDENTIALS_PATH
    )
    tokens = load_tokens(credentials) or {}
    if not (tokens.get("access_token") or tokens.get("token")):
        raise ValueError(
            "Google Calendar não conectado. "
            "Execute a autenticação do conector primeiro."
        )
    calendar_id = quote(payload["calendar_id"], safe="")
    base = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
    body = {
        "summary": payload["title"],
        "description": payload["description"],
        "start": {"dateTime": payload["start"]},
        "end": {"dateTime": payload["end"]},
    }

    def create(token: str) -> dict:
        response = httpx.post(
            base, headers={"Authorization": f"Bearer {token}"}, json=body, timeout=30.0
        )
        response.raise_for_status()
        return response.json()

    created = call_with_refresh(create, credentials)
    event_id = created.get("id")
    if not event_id:
        raise RuntimeError(
            "Google Calendar não retornou ID do evento; "
            "verifique o calendário antes de repetir."
        )

    def verify(token: str) -> dict:
        response = httpx.get(
            f"{base}/{quote(event_id, safe='')}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()

    verified = call_with_refresh(verify, credentials)
    if verified.get("id") != event_id:
        raise RuntimeError(
            "Evento criado, mas verificação por ID falhou; "
            "verifique o calendário antes de repetir."
        )
    return {"id": event_id, "url": verified.get("htmlLink"), "verified": True}


def approve(
    action_id: str,
    db_path: Path = DEFAULT_ACTIONS_DB,
    vault: Path = DEFAULT_VAULT,
    credentials_path: str | None = None,
) -> dict:
    """Claim once before side effects. Uncertain failures require manual review."""
    with _connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone()
        if not row:
            raise KeyError(action_id)
        if row["state"] != "pending":
            raise ValueError(f"Ação já está em estado {row['state']}.")
        now = _now()
        db.execute(
            "UPDATE actions SET state='executing',updated_at=? WHERE id=?",
            (now, action_id),
        )
        db.execute(
            "INSERT INTO action_events(action_id,event,at) VALUES (?,?,?)",
            (action_id, "approved", now),
        )
        kind, payload = row["kind"], json.loads(row["payload"])
    try:
        result = (
            _write_note(action_id, payload, vault)
            if kind == "note"
            else _create_calendar_event(action_id, payload, credentials_path)
        )
    except Exception as exc:
        with _connect(db_path) as db:
            now = _now()
            db.execute(
                "UPDATE actions SET state='needs_review',updated_at=?,"
                "result=? WHERE id=?",
                (now, str(exc), action_id),
            )
            db.execute(
                "INSERT INTO action_events(action_id,event,at,detail) VALUES (?,?,?,?)",
                (action_id, "needs_review", now, str(exc)),
            )
        raise
    with _connect(db_path) as db:
        now = _now()
        db.execute(
            "UPDATE actions SET state='completed',updated_at=?,result=? WHERE id=?",
            (now, json.dumps(result, ensure_ascii=False), action_id),
        )
        db.execute(
            "INSERT INTO action_events(action_id,event,at,detail) VALUES (?,?,?,?)",
            (action_id, "completed", now, json.dumps(result, ensure_ascii=False)),
        )
    return result
