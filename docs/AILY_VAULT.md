# AILY: busca no vault

Esta integração lê `~/SegundoCerebro` e mantém um índice SQLite descartável em
`~/.local/state/aily-platform/vault.sqlite3`. O vault não é modificado. Defina
`AILY_VAULT_PATH` e `AILY_VAULT_INDEX` para usar outros caminhos.

O índice é atualizado incrementalmente a cada busca. Arquivos em `Arquivo/`
ficam fora do índice. Capturas em `Brain/AILY/` entram com `status: pendente`,
mas ficam fora dos resultados normais. Use `--include-pending` ou o parâmetro
MCP `include_pending: true` para inspecioná-las. Cada resultado inclui o
caminho absoluto da fonte e o status encontrado no frontmatter.

## Terminal

```sh
source .venv/bin/activate
jarvis memory vault-index
jarvis memory vault-search classificacao
jarvis memory vault-search --include-pending classificacao
```

## Claude Code via MCP

O servidor stdio expõe `aily_vault_search`, `aily_prepare_action` e
`aily_action_status`. A execução exige `aily action approve ID` no terminal:

```sh
claude mcp add aily-vault -- /CAMINHO/DA/VENV/bin/python -m openjarvis.aily_vault.mcp_stdio
```

Instale o fork na mesma venv antes de registrar o servidor. Configure
`AILY_VAULT_PATH` no ambiente do processo Claude se o vault não estiver no
caminho padrão. O servidor MCP não executa ações pendentes. Configure o Google Calendar
se quiser criar eventos após aprovação.

O comando `jarvis vault` do OpenJarvis gerencia credenciais criptografadas;
não se refere ao vault Markdown da AILY.
