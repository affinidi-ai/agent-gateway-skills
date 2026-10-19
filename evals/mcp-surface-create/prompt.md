---
name: mcp-surface-create
description: "Put an MCP server behind the gateway and prove it serves."
tags: [task, surfaces, mcp]
runs: 3
max_turns: 20
timeout_seconds: 480
allowed_tools: [Skill, Read, Glob, Grep]
---

I have an MCP server running at http://192.0.2.10:9000/mcp. Put it behind the Agent Gateway so the agents call
it through the gateway. Give me the exact fabric commands, and tell me how I will know it worked.
