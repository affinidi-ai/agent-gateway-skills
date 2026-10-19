---
name: nearmiss-k8s-opa
description: "Near-miss: Rego for an OPA sidecar on Kubernetes is not an Agent Gateway task."
tags: [trigger, near-miss]
runs: 3
max_turns: 8
timeout_seconds: 240
allowed_tools: [Skill, Read, Glob, Grep]
---

Write a Rego policy for the OPA sidecar on a Kubernetes ingress that blocks requests without a valid JWT.
