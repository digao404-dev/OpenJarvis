# ruff: noqa: E501
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openjarvis.aily_capture.legacy import (
    archive_transient_captures,
    connect,
    duplicate_of,
    flush,
    human_text,
    low_value_note,
    main,
    normalize_capture_metadata,
    record_review,
    redact_secrets,
    scan_one,
)


class ScannerTests(unittest.TestCase):
    def test_tool_result_ignored(self):
        self.assertEqual(human_text({"type": "user", "message": {"content": [{"type": "tool_result", "content": "secret"}]}}), "")

    def test_secret_is_removed_before_capture(self):
        self.assertEqual(redact_secrets("A senha 'EXAMPLE123' foi exposta."),
                         "A senha [REDACTED] foi exposta.")

    def test_only_completed_turn_writes_once(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            session = root / "one.jsonl"
            db = connect(root / "state.sqlite3")
            user = {"type": "user", "uuid": "u1", "message": {"content": "Decidimos registrar conhecimento periodicamente na AILY."}}
            assistant = {"type": "assistant", "uuid": "a1", "message": {"stop_reason": "end_turn", "content": [{"type": "text", "text": "A decisão foi registrada e a implementação será local."}]}}
            session.write_text(json.dumps(user) + "\n")
            with patch("openjarvis.aily_capture.legacy.ollama_extract", return_value=[{"kind": "note", "title": "Decisão AILY", "body": "Registrar conhecimento localmente."}]) as model:
                self.assertEqual(scan_one(db, session), 0)
                with session.open("a") as file:
                    file.write(json.dumps(assistant) + "\n")
                self.assertEqual(scan_one(db, session), 1)
                self.assertEqual(scan_one(db, session), 0)
                self.assertEqual(model.call_count, 1)
            flush(db, root / "vault")
            notes = list((root / "vault/Brain/AILY").glob("*.md"))
            self.assertEqual(len(notes), 1)
            self.assertIn("tipo: aprendizado", notes[0].read_text())

    def test_legacy_pending_task_is_disabled(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            db = connect(root / "state.sqlite3")
            db.execute("INSERT INTO items(id,kind,title,body,session,turn_id,created_at) VALUES(?,?,?,?,?,?,?)",
                       ("one", "task", "Integração Meet", "Implementar", "session-1", "turn-1", "2026-01-01"))
            db.commit()
            flush(db, root / "vault")
            self.assertEqual(db.execute("SELECT state,target FROM items").fetchone(), ("disabled", None))

    def test_cross_turn_duplicate_is_recorded_but_not_published(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            session = root / "-Users-bioma-Documents-bioma-trading-bot" / "one.jsonl"
            session.parent.mkdir()
            db = connect(root / "state.sqlite3")
            with session.open("w") as file:
                for index in (1, 2):
                    file.write(json.dumps({"type": "user", "uuid": f"u{index}", "message": {"content": "Corrigimos o erro de build do Amplify e verificamos a publicação."}}) + "\n")
                    file.write(json.dumps({"type": "assistant", "uuid": f"a{index}", "message": {"stop_reason": "end_turn", "content": [{"type": "text", "text": "O build foi corrigido e o deploy foi verificado em produção."}]}}) + "\n")
            finding = {"kind": "note", "title": "Build do Amplify corrigido", "body": "O build foi corrigido e o deploy foi verificado em produção."}
            with patch("openjarvis.aily_capture.legacy.ollama_extract", return_value=[finding]):
                self.assertEqual(scan_one(db, session), 1)
            self.assertEqual(dict(db.execute("SELECT state,count(*) FROM items GROUP BY state")), {"pending": 1, "duplicate": 1})
            self.assertEqual(db.execute("SELECT project FROM items LIMIT 1").fetchone()[0], "trading-bot")
            flush(db, root / "vault")
            self.assertEqual(len(list((root / "vault/Brain/AILY").glob("*.md"))), 1)

    def test_similar_title_with_different_finding_is_kept(self):
        with tempfile.TemporaryDirectory() as root:
            db = connect(Path(root) / "state.sqlite3")
            db.execute("INSERT INTO items(id,kind,title,body,session,turn_id,created_at,project) VALUES(?,?,?,?,?,?,?,?)",
                       ("one", "note", "Build do Amplify", "O erro era a versão do Node.js.", "s1", "t1", "2026-01-01", "trading-bot"))
            self.assertIsNone(duplicate_of(db, {"kind": "note", "title": "Build do Amplify", "body": "O erro era uma configuração inválida de cache SSM."}, "trading-bot"))
            self.assertIsNone(duplicate_of(db, {"kind": "note", "title": "Outra decisão", "body": "O erro era a versão do Node.js!"}, "trading-bot"))

    def test_transient_status_note_is_filtered(self):
        self.assertTrue(low_value_note({"kind": "note", "title": "Status atual do deploy"}))
        self.assertTrue(low_value_note({"kind": "note", "title": "TradingBot/decisao-existente.md"}))
        self.assertFalse(low_value_note({"kind": "note", "title": "Correção da versão do Node no Amplify"}))

    def test_curating_capture_preserves_origin_and_archives_transient_note(self):
        with tempfile.TemporaryDirectory() as root:
            vault = Path(root) / "vault"
            source = vault / "Brain/AILY/status-um.md"
            source.parent.mkdir(parents=True)
            source.write_text('---\nprojeto: trading-bot\ntags: ["#projeto/trading-bot", "#tema/aily"]\n'
                              'status: pendente\naily_id: "one"\n---\n# Status atual\n', encoding="utf-8")
            db = connect(Path(root) / "state.sqlite3")
            db.execute("INSERT INTO items(id,kind,title,body,session,created_at,state,target,project) "
                       "VALUES(?,?,?,?,?,?,?,?,?)",
                       ("one", "note", "Status atual do deploy", "Estado temporário", "s",
                        "2026-01-01T00:00:00+00:00", "done", str(source), "trading-bot"))
            db.commit()
            self.assertEqual(normalize_capture_metadata(db, vault), 1)
            self.assertEqual(archive_transient_captures(db, vault, days=0), 1)
            target = vault / "Arquivo/AILY/status-um.md"
            self.assertIn("projeto: outro\norigem_repo: trading-bot", target.read_text())
            self.assertIn('"#projeto/outro"', target.read_text())
            self.assertEqual(db.execute("SELECT state FROM items WHERE id='one'").fetchone()[0], "archived")

    def test_promotion_ledger_requires_canonical_evidence_and_tracks_correction(self):
        with tempfile.TemporaryDirectory() as root:
            vault = Path(root) / "vault"
            canonical = vault / "TradingBot/regra.md"
            canonical.parent.mkdir(parents=True)
            canonical.write_text("# Regra\n")
            db = connect(Path(root) / "state.sqlite3")
            db.execute("INSERT INTO items(id,kind,title,body,session,created_at,state,project) "
                       "VALUES(?,?,?,?,?,?,?,?)",
                       ("one", "note", "Regra", "Detalhe", "s", "2026-01-01", "done", "trading-bot"))
            db.commit()
            with self.assertRaises(ValueError):
                record_review(db, vault, "one", "promote", str(canonical))
            record_review(db, vault, "one", "promote", str(canonical), "Confirmado no teste X")
            record_review(db, vault, "one", "wrong", evidence="Teste posterior contrariou o dado")
            self.assertEqual(dict(db.execute("SELECT decision,count(*) FROM review_events GROUP BY decision")),
                             {"promote": 1, "wrong": 1})

    def test_covered_capture_moves_out_of_active_queue(self):
        with tempfile.TemporaryDirectory() as root:
            vault = Path(root) / "vault"
            source = vault / "Brain/AILY/covered.md"
            source.parent.mkdir(parents=True)
            source.write_text('---\nstatus: pendente\naily_id: "one"\n---\n# Covered\n')
            canonical = vault / "Brain/regra.md"
            canonical.write_text("# Regra\n")
            db = connect(Path(root) / "state.sqlite3")
            db.execute("INSERT INTO items(id,kind,title,body,session,created_at,state,target) "
                       "VALUES(?,?,?,?,?,?,?,?)",
                       ("one", "note", "Covered", "Já documentado", "s", "2026-01-01",
                        "done", str(source)))
            db.commit()
            record_review(db, vault, "one", "covered", str(canonical), "Mesmo fato verificado")
            self.assertFalse(source.exists())
            self.assertTrue((vault / "Arquivo/AILY/covered.md").exists())
            self.assertEqual(db.execute("SELECT state FROM items WHERE id='one'").fetchone()[0], "archived")

    def test_run_budget_preserves_unread_turns(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            session = root / "one.jsonl"
            db = connect(root / "state.sqlite3")
            with session.open("w") as file:
                for index in range(3):
                    file.write(json.dumps({"type": "user", "uuid": f"u{index}", "message": {"content": "Registramos um fato útil e validado para sessões futuras."}}) + "\n")
                    file.write(json.dumps({"type": "assistant", "uuid": f"a{index}", "message": {"stop_reason": "end_turn", "content": [{"type": "text", "text": "O fato foi validado e a evidência está disponível no sistema."}]}}) + "\n")
            with patch("openjarvis.aily_capture.legacy.ollama_extract", side_effect=[
                [{"kind": "note", "title": title, "body": body}] for title, body in [
                    ("Cache SSM no Amplify", "A falha de build ocorreu por configuração incorreta de cache SSM."),
                    ("Autenticação na Viasoft", "A autenticação exige a claim ROLES_API no token de acesso."),
                    ("Download SICAR assíncrono", "O demonstrativo PDF é obtido depois que o contrato é salvo."),
                ]
            ]):
                self.assertEqual(scan_one(db, session, max_new=1), 1)
                self.assertEqual(scan_one(db, session, max_new=1), 1)
                self.assertEqual(scan_one(db, session, max_new=1), 1)
            self.assertEqual(db.execute("SELECT count(*) FROM items").fetchone()[0], 3)

    def test_old_transient_capture_is_archived_without_deletion(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            vault = root / "vault"
            source = vault / "Brain/AILY/status-um.md"
            source.parent.mkdir(parents=True)
            source.write_text('---\nstatus: pendente\naily_id: "one"\n---\n# Status atual\n', encoding="utf-8")
            db = connect(root / "state.sqlite3")
            db.execute("INSERT INTO items(id,kind,title,body,session,created_at,state,target) VALUES(?,?,?,?,?,?,?,?)",
                       ("one", "note", "Status atual do deploy", "Estado temporário", "s", "2026-01-01T00:00:00+00:00", "done", str(source)))
            db.commit()
            self.assertEqual(archive_transient_captures(db, vault), 1)
            destination = vault / "Arquivo/AILY/status-um.md"
            self.assertFalse(source.exists())
            self.assertIn("status: arquivado", destination.read_text(encoding="utf-8"))
            self.assertEqual(db.execute("SELECT target FROM items WHERE id='one'").fetchone()[0], str(destination))

    def test_closed_session_snapshot_excludes_later_messages(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            sessions = root / "projects"
            session = sessions / "repo" / "one.jsonl"
            session.parent.mkdir(parents=True)
            first = [
                {"type": "user", "uuid": "u1", "message": {"content": "Registramos uma decisão útil para o projeto."}},
                {"type": "assistant", "uuid": "a1", "message": {"stop_reason": "end_turn", "content": [{"type": "text", "text": "A decisão foi verificada e documentada nesta sessão."}]}}
            ]
            second = [
                {"type": "user", "uuid": "u2", "message": {"content": "Esta mensagem veio depois do encerramento."}},
                {"type": "assistant", "uuid": "a2", "message": {"stop_reason": "end_turn", "content": [{"type": "text", "text": "Esta resposta ainda não deve ser capturada."}]}}
            ]
            session.write_text("".join(json.dumps(row) + "\n" for row in first))
            closed_size = session.stat().st_size
            state = root / "state"
            with patch.object(sys, "argv", ["aily", "close", "--state", str(state), "--sessions", str(sessions)]), \
                 patch.object(sys, "stdin", io.StringIO(json.dumps({"transcript_path": str(session), "session_id": "one"}))):
                self.assertEqual(main(), 0)
            with session.open("a") as file:
                file.write("".join(json.dumps(row) + "\n" for row in second))
            db = connect(state / "aily.sqlite3")
            self.assertEqual(db.execute("SELECT upto_offset FROM closed_sessions").fetchone()[0], closed_size)
            with patch("openjarvis.aily_capture.legacy.ollama_extract", return_value=[{"kind": "note", "title": "Decisão do projeto", "body": "A decisão foi verificada nesta sessão."}]) as model:
                self.assertEqual(scan_one(db, session, end_offset=closed_size), 1)
            self.assertEqual(model.call_count, 1)
            self.assertEqual(db.execute("SELECT offset FROM sessions").fetchone()[0], closed_size)

    def test_scan_ignores_unclosed_session_then_writes_one_note(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            sessions = root / "projects"
            session = sessions / "repo" / "one.jsonl"
            session.parent.mkdir(parents=True)
            session.write_text("\n".join(json.dumps(row) for row in [
                {"type": "user", "uuid": "u1", "message": {"content": "Documentamos uma correção verificada para lembrar depois."}},
                {"type": "assistant", "uuid": "a1", "message": {"stop_reason": "end_turn", "content": [{"type": "text", "text": "A correção foi verificada com teste e registrada."}]}}
            ]) + "\n")
            state, vault = root / "state", root / "vault"
            argv = ["aily", "scan", "--state", str(state), "--sessions", str(sessions), "--vault", str(vault)]
            with patch.object(sys, "argv", argv), patch("openjarvis.aily_capture.legacy.ollama_extract") as model:
                self.assertEqual(main(), 0)
                model.assert_not_called()
            with patch.object(sys, "argv", ["aily", "close", "--state", str(state), "--sessions", str(sessions)]), \
                 patch.object(sys, "stdin", io.StringIO(json.dumps({"transcript_path": str(session), "session_id": "one"}))):
                self.assertEqual(main(), 0)
            with patch.object(sys, "argv", argv), \
                 patch("openjarvis.aily_capture.legacy.ollama_extract", return_value=[{"kind": "note", "title": "Correção verificada", "body": "A correção foi confirmada com teste."}]):
                self.assertEqual(main(), 0)
            self.assertEqual(len(list((vault / "Brain/AILY").glob("*.md"))), 1)


if __name__ == "__main__":
    unittest.main()
