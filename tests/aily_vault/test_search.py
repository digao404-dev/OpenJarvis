"""Focused checks for AILY's vault recall boundary."""

import json
import os
import subprocess
import sys
from pathlib import Path

from openjarvis.aily_vault.search import VaultIndex


def test_search_tracks_sources_and_excludes_pending_by_default(tmp_path: Path):
    vault = tmp_path / "vault"
    canonical = vault / "Sistemas" / "decisao.md"
    pending = vault / "Brain" / "AILY" / "captura.md"
    archived = vault / "Arquivo" / "antiga.md"
    for path in (canonical, pending, archived):
        path.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_text(
        "---\nstatus: ativo\n---\n# Decisão\n\nO motor classifica grãos."
    )
    pending.write_text(
        "---\nstatus: pendente\n---\n# Captura\n\nO motor classifica grãos."
    )
    archived.write_text("# Arquivada\n\nO motor classifica grãos.")

    search = VaultIndex(vault, tmp_path / "index.sqlite3")
    assert search.sync() == (2, 0)
    results = search.search("classifica grãos", refresh=False)
    assert [result.path for result in results] == [str(canonical)]
    assert results[0].status == "ativo"
    assert "classifica grãos" in results[0].excerpt
    assert {
        result.path
        for result in search.search(
            "classifica grãos", include_pending=True, refresh=False
        )
    } == {str(canonical), str(pending)}

    canonical.unlink()
    assert search.sync() == (0, 1)
    assert search.search("classifica grãos", refresh=False) == []


def test_cli_and_mcp_return_the_same_curated_note(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "decisao.md"
    note.write_text(
        "---\nstatus: ativo\n---\n# Decisão Atlas\n\nUsamos o índice local."
    )
    env = os.environ | {
        "AILY_VAULT_PATH": str(vault),
        "AILY_VAULT_INDEX": str(tmp_path / "index.sqlite3"),
    }

    cli = subprocess.run(
        [
            str(Path(sys.executable).with_name("jarvis")),
            "--quiet",
            "memory",
            "vault-search",
            "Atlas",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert str(note) in cli.stdout
    assert "status: ativo" in cli.stdout

    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "aily_vault_search",
                "arguments": {"query": "Atlas"},
            },
        },
    ]
    mcp = subprocess.run(
        [sys.executable, "-m", "openjarvis.aily_vault.mcp_stdio"],
        input="\n".join(json.dumps(req) for req in requests) + "\n",
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    responses = [json.loads(line) for line in mcp.stdout.splitlines()]
    assert [tool["name"] for tool in responses[1]["result"]["tools"]] == [
        "aily_vault_search", "aily_prepare_action", "aily_action_status"
    ]
    assert responses[2]["result"]["isError"] is False
    assert str(note) in responses[2]["result"]["content"][0]["text"]
