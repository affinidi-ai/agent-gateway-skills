---
name: policy-403-missing-field
description: "A surface policy reads input.caller, which never exists, so it denies every call; name the real input and a safe fix."
tags: [task, policies, smoke]
runs: 3
max_turns: 15
timeout_seconds: 420
allowed_tools: [Skill, Read, Glob, Grep]
---

Every call to my surface gets a 403 and I can't see why. The policy attached to it is in `package
surface.policy`, has `default allow := false`, and allows a request when
`input.caller.jwt_bearer.claims.role == "agent"`. What is wrong, and how do I fix it?
