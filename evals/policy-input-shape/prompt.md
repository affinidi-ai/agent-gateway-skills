---
name: policy-input-shape
description: "Which OPA input fields a surface policy reads for a JWT claim."
tags: [task, policies]
runs: 3
max_turns: 15
timeout_seconds: 420
allowed_tools: [Skill, Read, Glob, Grep]
---

I want a Rego rule on my surface that only lets through callers whose JWT has the claim role=agent. Which
input fields do I reference? Is it input.caller.jwt_bearer or input.jwt?
