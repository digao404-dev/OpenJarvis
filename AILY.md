# AILY sobre OpenJarvis

Este fork usa OpenJarvis como runtime da AILY. O vault Markdown em
`~/SegundoCerebro` é a fonte canônica de conhecimento curado; o índice SQLite
é descartável. Capturas automáticas em `Brain/AILY` não entram na busca padrão.

- `upstream`: OpenJarvis oficial; `origin`: fork pessoal.
- Captura de sessões Claude: `aily capture status|scan|review|curate`. O módulo
  preserva `~/.local/state/aily/aily.sqlite3` e o mesmo vault do capturador
  anterior. No macOS, o hook SessionEnd e o LaunchAgent podem chamar esta CLI.
- Busca e MCP: [docs/AILY_VAULT.md](docs/AILY_VAULT.md).
- Chat: `aily chat`; voz: `aily voice`. Por padrão, a conversa usa a persona
  AILY em português, o agente `orchestrator` e as ferramentas de vault e ações.
  No macOS, a voz local usa Luciana; o reconhecimento usa Whisper.
- Ações: `aily action note "Título" "Conteúdo"` ou
  `aily action calendar "Título" 2026-10-22T09:00:00-03:00
  2026-10-22T10:00:00-03:00`. São preparadas como pendentes. Consulte com
  `aily action pending` e aprove com `aily action approve ID`, digitando o ID
  novamente. O resultado e as transições ficam em
  `~/.local/state/aily-platform/actions.sqlite3`.

Eventos exigem Google Calendar conectado (`aily connect gcalendar`) com escopo
de escrita. AILY não executa a ação de calendário sem a aprovação pelo ID.
Se a criação tiver resultado incerto, a ação fica em `needs_review` para
verificação manual antes de qualquer nova tentativa.

Em macOS, instale uma cópia não editável fora de `Documents` para LaunchAgents,
pois o processo em segundo plano pode não ter permissão para abrir executáveis
na pasta Documents. Exemplo:

```sh
python3 -m venv ~/.local/share/aily-platform/venv
~/.local/share/aily-platform/venv/bin/pip install '.[speech]'
```
