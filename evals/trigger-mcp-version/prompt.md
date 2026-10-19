---
name: trigger-mcp-version
description: "Fires on the gateway's MCP version error."
tags: [trigger, should-fire]
runs: 3
max_turns: 12
timeout_seconds: 360
allowed_tools: [Skill, Read, Glob, Grep]
---

An MCP client gets JSON-RPC error -32022 'Unsupported protocol version' as soon as it goes through the trust
gateway, but it works fine when it talks to the server directly.
