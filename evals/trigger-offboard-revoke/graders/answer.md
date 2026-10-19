---
type: llm
focus: last_message
weight: 1
---

Pass only if every statement holds:

- The response uses `fabric agent-gateway delegation-vault revoke-user` with the user's hash as bare hex, and warns that a
  `sha256:`-prefixed hash matches nothing while still answering 200.
- Before the revoke step, it says the user's grants are removed, and it leaves the decision to the user: it
  asks them to confirm, or says what the change affects and lets them run it.
- Its check reads the result: a `revoked` count of at least 1, and no grants left for that hash in `fabric
  agent-gateway delegation-vault list -o json`.
- It says revocation stays inside the gateway, so the tokens must also be revoked at each OAuth provider.
