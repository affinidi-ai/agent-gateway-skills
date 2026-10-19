---
name: caller-auth-wrong-key
description: "A wrong caller API key still reaches the upstream; explain why and enforce it."
tags: [task, identity, policies]
runs: 3
max_turns: 15
timeout_seconds: 420
allowed_tools: [Skill, Read, Glob, Grep]
---

I attached an API key requirement to my surface, but a request with a wrong key still reaches the upstream. Is
caller auth broken?
