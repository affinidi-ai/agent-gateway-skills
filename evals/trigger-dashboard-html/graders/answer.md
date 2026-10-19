---
type: llm
focus: last_message
weight: 1
---

Pass only if every statement holds:

- The response says dashboard HTML from a surface URL means the request path is outside every channel prefix,
  so no surface route matched and the dashboard answered instead.
- It tells the user to read the listen addresses and channel prefixes with
  `fabric agent-gateway runtime show surface-routing -o json` and to compare the surface's listen address and route with
  them.
- It gives a check that sends a request to the listen address plus route and expects a JSON-RPC answer.
