---
type: llm
focus: last_message
weight: 1
---

Pass only if every statement holds:

- The response says a failed caller credential does not block the request on its own.
- It says the request continues with `input.source_auth.method` equal to `failed`.
- It proposes a surface policy in `package surface.policy` that denies unless `input.source_auth.method` is an
  accepted method (such as `api_key`).
- Before the step that attaches the policy, it says every caller without a valid key is then refused, and it
  leaves the decision to the user: it asks them to confirm, or says what the change affects and lets them run
  it.
- Its check sends requests through the data plane, including one with a wrong key (expect a deny) and one with
  a valid key (expect success).
