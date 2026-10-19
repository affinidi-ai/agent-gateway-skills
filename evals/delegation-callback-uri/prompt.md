---
name: delegation-callback-uri
description: "The redirect URI to register with an OAuth provider for credential delegation."
tags: [task, credentials]
runs: 3
max_turns: 15
timeout_seconds: 420
allowed_tools: [Skill, Read, Glob, Grep]
---

I'm registering an OAuth app with Google for per-user credential delegation through the gateway. What redirect
URI do I give Google?
