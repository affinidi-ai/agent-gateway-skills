---
type: llm
focus: last_message
weight: 1
---

Pass only if every statement holds:

- Before the create step, the procedure reads the routing view with `fabric agent-gateway runtime show surface-routing -o
  json` and takes the listen address and a route under one of its channel prefixes from that output, instead
  of assuming a host, port or path prefix.
- Its create step uses `fabric agent-gateway surfaces create` and passes `--protocol mcp` explicitly, with the MCP server's
  URL as the target endpoint.
- Its check reads the surface back with `fabric agent-gateway surfaces get <id> -o json` and also sends at least one MCP
  request (`initialize` or `tools/list`) to the data-plane URL (listen address plus route), not only a
  management API call.
- It says the upstream must stop accepting direct calls (or be unreachable except through the gateway),
  otherwise callers can bypass the gateway.
- It gives an undo, such as deleting the new surface, and does not delete anything without the user's
  go-ahead.
