---
type: llm
focus: last_message
weight: 1
---

Pass only if every statement holds:

- The response says the gateway serves the callback at `<oauth_callback_route>/<provider_id>`, at the root of
  the gateway, not under the `/api` management prefix.
- It says `oauth_callback_route` is configuration and tells the user to read it from the running gateway with
  `fabric agent-gateway runtime show surface-routing -o json`, instead of presenting one fixed path as the answer.
- If it names `/oauth/callback` or `/v1/identity/oauth/callback`, it says which is the code default and which
  the example configuration sets.
- It says the redirect URI the gateway sends is the credential provider's `callback_url` when set, otherwise the
  gateway base URL built from `did.domain` plus the provider's `callback_path`, and that the URI registered
  with Google must match it exactly.
