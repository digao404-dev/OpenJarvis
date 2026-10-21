"""Read-only Markdown vault search with a disposable SQLite FTS5 index."""

from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

DEFAULT_VAULT = Path(os.environ.get("AILY_VAULT_PATH", "~/SegundoCerebro")).expanduser()
DEFAULT_INDEX = Path(
    os.environ.get("AILY_VAULT_INDEX", "~/.local/state/aily-platform/vault.sqlite3")
).expanduser()
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_STATUS = re.compile(r"^status:\s*['\"]?([^\n'\"]+)", re.IGNORECASE | re.MULTILINE)
_TITLE = re.compile(r"^#\s+(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class VaultResult:
    path: str
    title: str
    status: str
    excerpt: str
    score: float


class VaultIndex:
    """Index Markdown notes without changing the vault itself.

    Notes under Brain/AILY are unverified captures. They are indexed for
    explicit inspection but omitted from normal recall. Arquivo is omitted.
    """

    def __init__(self, vault: Path = DEFAULT_VAULT, index: Path = DEFAULT_INDEX):
        self.vault = Path(vault).expanduser().resolve()
        self.index = Path(index).expanduser()
        if not self.vault.is_dir():
            raise ValueError(f"Vault inexistente: {self.vault}")

    def _connect(self) -> sqlite3.Connection:
        self.index.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.index, timeout=10)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY, mtime_ns INTEGER NOT NULL, size INTEGER NOT NULL
        )""")
        db.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS notes USING fts5(
            path UNINDEXED, title, body, status UNINDEXED,
            tokenize='unicode61 remove_diacritics 2'
        )""")
        if db.execute("PRAGMA user_version").fetchone()[0] < 1:
            with db:
                db.execute("DELETE FROM notes")
                db.execute("DELETE FROM files")
                db.execute("PRAGMA user_version=1")
        return db

    def _files(self):
        for path in self.vault.rglob("*.md"):
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(self.vault)
            if any(part.startswith(".") for part in relative.parts):
                continue
            if relative.parts[0].casefold() == "arquivo":
                continue
            yield path, relative

    @staticmethod
    def _status(relative: Path, text: str) -> str:
        if relative.parts[:2] == ("Brain", "AILY"):
            return "pendente"
        frontmatter = text.split("\n---", 1)[0] if text.startswith("---\n") else ""
        match = _STATUS.search(frontmatter)
        return match.group(1).strip().casefold() if match else "sem_status"

    def sync(self) -> tuple[int, int]:
        """Incrementally update changed notes and remove deleted notes."""
        db = self._connect()
        updated = 0
        removed = 0
        try:
            known = {
                row[0]: (row[1], row[2])
                for row in db.execute("SELECT path, mtime_ns, size FROM files")
            }
            seen: set[str] = set()
            with db:
                for path, relative in self._files():
                    key = relative.as_posix()
                    seen.add(key)
                    stat = path.stat()
                    signature = (stat.st_mtime_ns, stat.st_size)
                    if known.get(key) == signature:
                        continue
                    try:
                        content = path.read_text(encoding="utf-8")
                    except (OSError, UnicodeError):
                        continue
                    title_match = _TITLE.search(content)
                    title = title_match.group(1).strip() if title_match else path.stem
                    status = self._status(relative, content)
                    body = (
                        content.split("\n---", 1)[1]
                        if content.startswith("---\n") and "\n---" in content
                        else content
                    )
                    db.execute("DELETE FROM notes WHERE path=?", (key,))
                    db.execute(
                        "INSERT INTO notes(path,title,body,status) VALUES(?,?,?,?)",
                        (key, title, body, status),
                    )
                    db.execute(
                        "INSERT INTO files(path,mtime_ns,size) VALUES(?,?,?) "
                        "ON CONFLICT(path) DO UPDATE SET "
                        "mtime_ns=excluded.mtime_ns,size=excluded.size",
                        (key, *signature),
                    )
                    updated += 1
                for key in known.keys() - seen:
                    db.execute("DELETE FROM notes WHERE path=?", (key,))
                    db.execute("DELETE FROM files WHERE path=?", (key,))
                    removed += 1
            return updated, removed
        finally:
            db.close()

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        include_pending: bool = False,
        refresh: bool = True,
    ) -> list[VaultResult]:
        """Search using quoted FTS terms and return attributable excerpts."""
        terms = _TOKEN.findall(query)[:12]
        if not terms:
            return []
        if refresh:
            self.sync()
        expression = " AND ".join(f'"{term}"' for term in terms)
        db = self._connect()
        try:
            rows = db.execute(
                """SELECT path,title,status,
                          snippet(notes,2,'','',' … ',28),-bm25(notes,0,5,1,0)
                   FROM notes WHERE notes MATCH ?
                     AND (? OR status NOT IN ('pendente','arquivado'))
                   ORDER BY bm25(notes,0,5,1,0) LIMIT ?""",
                (expression, int(include_pending), max(1, min(int(top_k), 20))),
            ).fetchall()
        finally:
            db.close()
        return [
            VaultResult(
                path=str(self.vault / path),
                title=title,
                status=status,
                excerpt=" ".join(excerpt.split()),
                score=score,
            )
            for path, title, status, excerpt, score in rows
        ]
