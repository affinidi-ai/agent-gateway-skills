---
type: llm
focus: last_message
weight: 1
---

Pass only if every statement holds:

- The response says `input.caller` does not exist in a surface policy's input, so the rule never matches and
  the default deny refuses every request.
- It says the caller is `input.source_auth`, tagged by `method`, and that it is present only when the surface
  checks a caller credential; it tells the user to check the surface's `access_point.caller_authentication`.
- The corrected policy it proposes keeps `package surface.policy` and tests `input.source_auth.method ==
  "jwt_bearer"` and `input.source_auth.claims.role == "agent"`.
- Before the change, it saves the current policy definition, simulates the draft, says the update changes every
  surface that uses the definition, and leaves the decision to the user: it asks them to confirm, or says what
  the change affects and lets them run it.
- Its check sends a real request through the data plane with a token whose role is `agent`. It does not tell the
  user to run a bare `fabric agent-gateway runtime reload` (a full reload of the whole gateway).
