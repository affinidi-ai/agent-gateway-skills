# Save-time validation of an A2A proxy, following the recipe in
# skills/affinidi-agent-gateway/references/proxies.md. The Direct Line runtime needs a published
# Copilot Studio agent, so only the refusal of a missing secret reference is exercised here.

setup() {
    export A2A_PROXY_NAME
    A2A_PROXY_NAME="$(unique copilot-hr)"
}

verify() {
    expect_fail_block 1 'A2A proxy secret is not accessible'
    expect_json 2 'doc.get("name") == env["A2A_PROXY_NAME"] and doc.get("saved") == 0' \
        "the refused create saved nothing"
}

cleanup() {
    [ -n "${A2A_PROXY_NAME:-}" ] || return 0
    fab agent-gateway a2a-proxies list -o json | jq -r --arg n "$A2A_PROXY_NAME" '.[] | select(.name == $n) | .id' |
        while read -r id; do fab agent-gateway a2a-proxies delete "$id" >/dev/null; done
}
