---
name: nearmiss-api-gateway-compare
description: "Near-miss: choosing a general API gateway is not an Agent Gateway task."
tags: [trigger, near-miss]
runs: 3
max_turns: 8
timeout_seconds: 240
allowed_tools: [Skill, Read, Glob, Grep]
---

Compare Kong, Apigee and AWS API Gateway for rate limiting and auth plugins. Which one fits best?
