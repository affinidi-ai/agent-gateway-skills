---
type: llm
focus: last_message
weight: 1
---

Pass only if every statement holds:

- The response says a surface policy sees the caller's authentication under `input.source_auth`, tagged by
  `method`, and that validated JWT claims are under `input.source_auth.claims` when the method is `jwt_bearer`.
- It says `input.caller` (including `input.caller.jwt_bearer`) does not exist.
- It says `input.jwt` exists only in per-tool MCP policies, not in a surface policy.
- The Rego it proposes declares `package surface.policy`, requires `input.source_auth.method == "jwt_bearer"`
  and checks the `role` claim.
- It recommends capturing the real OPA input for one request before relying on the rule.
