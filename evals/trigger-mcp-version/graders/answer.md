---
type: llm
focus: last_message
weight: 1
---

Pass only if every statement holds:

- The response says the gateway serves MCP protocol versions `2024-11-05` and `2026-07-28` only, and refuses a
  request whose `MCP-Protocol-Version` header names any other version, such as `2025-06-18`, with HTTP 400 and
  `-32022`.
- It says no gateway setting or fabric flag widens the accepted versions, and does not invent one.
- It gives a realistic way forward, such as making the upstream serve `2024-11-05` (the gateway asks the upstream
  for it on every `initialize`), putting the service behind an MCP proxy (`proxy://`), a client that sends no
  version header, or a client and upstream that both use `2026-07-28`.
