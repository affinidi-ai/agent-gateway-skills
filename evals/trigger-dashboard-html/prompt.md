---
name: trigger-dashboard-html
description: "Fires on a surface that answers dashboard HTML, without the product being named."
tags: [trigger, should-fire]
runs: 3
max_turns: 12
timeout_seconds: 360
allowed_tools: [Skill, Read, Glob, Grep]
---

curl to my surface route returns HTML for the dashboard instead of JSON-RPC. Is the route wrong?
