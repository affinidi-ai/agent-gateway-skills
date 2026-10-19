---
name: trigger-offboard-revoke
description: "Fires on revoking a leaver's delegated grants."
tags: [trigger, should-fire, safety]
runs: 3
max_turns: 12
timeout_seconds: 360
allowed_tools: [Skill, Read, Glob, Grep]
---

A contractor just left. Revoke all their delegated grants in the delegation vault and check it actually
worked.
