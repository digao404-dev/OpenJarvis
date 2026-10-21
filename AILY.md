# AILY sobre OpenJarvis

Este checkout é a base da próxima AILY. O capturador existente continua
separado nesta fase.

- `upstream`: repositório oficial OpenJarvis.
- Branch de integração: `codex/aily-vault-integration`.
- [Busca no vault e MCP](docs/AILY_VAULT.md): primeira integração própria.

O vault Markdown é a fonte canônica para conhecimento curado. O índice SQLite
é derivado e pode ser apagado e reconstruído. As capturas automáticas de
`Brain/AILY` não entram na recuperação padrão.

Próximas migrações: incorporar o capturador de sessões como módulo, definir
a identidade AILY e adicionar ferramentas de ação com confirmações e rastros.
