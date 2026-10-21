"""AILY command: identity, capture, approved actions, and OpenJarvis runtime."""

from __future__ import annotations

import argparse
import json
import os
import sys

from openjarvis.aily_actions import approve, get, list_pending, prepare

PERSONA = (
    "Você é AILY (Artificial Intelligence Linking Your Context, Ideas & Actions), "
    "assistente pessoal do usuário. Responda em português, com clareza. "
    "Use aily_vault_search para buscar contexto no vault antes de afirmar "
    "fatos pessoais. "
    "Trate capturas pendentes como não verificadas. Para anotar ou criar evento, "
    "use aily_prepare_action e mostre o ID, detalhes e comando de aprovação. "
    "Nunca afirme que uma ação foi executada antes do resultado confirmado "
    "por aily_action_status."
)
TOOLS = "aily_vault_search,aily_prepare_action,aily_action_status"


def _action(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="aily action")
    sub = parser.add_subparsers(dest="command", required=True)
    note = sub.add_parser("note", help="Preparar uma nota no vault")
    note.add_argument("title")
    note.add_argument("body")
    event = sub.add_parser("calendar", help="Preparar evento Google Calendar")
    event.add_argument("title")
    event.add_argument("start", help="ISO 8601 com fuso")
    event.add_argument("end", help="ISO 8601 com fuso")
    event.add_argument("--description", default="")
    event.add_argument("--calendar-id", default="primary")
    sub.add_parser("pending", help="Listar ações aguardando aprovação")
    status = sub.add_parser("status", help="Consultar ação e resultado")
    status.add_argument("id")
    accepted = sub.add_parser("approve", help="Aprovar e executar uma ação")
    accepted.add_argument("id")
    ns = parser.parse_args(args)
    if ns.command == "note":
        result = prepare("note", {"title": ns.title, "body": ns.body})
    elif ns.command == "calendar":
        result = prepare(
            "calendar_event",
            {
                "title": ns.title,
                "start": ns.start,
                "end": ns.end,
                "description": ns.description,
                "calendar_id": ns.calendar_id,
            },
        )
    elif ns.command == "pending":
        result = list_pending()
    elif ns.command == "status":
        result = get(ns.id)
        if result is None:
            parser.error("Ação não encontrada.")
    else:
        result = get(ns.id)
        if result is None:
            parser.error("Ação não encontrada.")
        if result["state"] != "pending":
            parser.error(f"Ação já está em estado {result['state']}.")
        if not sys.stdin.isatty():
            parser.error("Aprovação exige terminal interativo.")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        answer = input(f"Para executar, digite o ID {ns.id}: ").strip()
        if answer != ns.id:
            print("Cancelado; a ação continua pendente.")
            return 1
        result = approve(ns.id)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] == "capture":
        from openjarvis.aily_capture.legacy import main as capture_main

        raise SystemExit(capture_main(args[1:]))
    if args and args[0] == "action":
        raise SystemExit(_action(args[1:]))
    if not args or args[0] in ("chat", "voice"):
        os.environ["AILY_MODE"] = "1"
        extra = args[1:] if args else []
        if args and args[0] == "voice" and "--voice" not in extra:
            extra = ["--voice", *extra]
        if "--agent" not in extra and "-a" not in extra:
            extra = ["--agent", "orchestrator", *extra]
        if "--tools" not in extra:
            extra = ["--tools", TOOLS, *extra]
        if "--system" not in extra:
            extra = ["--system", PERSONA, *extra]
        args = ["chat", *extra]
    from openjarvis.cli import cli

    cli.main(args=args, prog_name="aily")


if __name__ == "__main__":
    main()
