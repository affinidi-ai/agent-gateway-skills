# Helpers for tests/e2e case files. run.sh sources this, then tests/e2e/cases/CASE.sh, in a
# subshell per case. Works with bash 3.2 (the macOS /bin/bash).
#
# A case file may define:
#   setup     runs before the recipe blocks
#   verify    runs after every block succeeded; use the expect_* helpers
#   cleanup   always runs at the end, even after a failure; must remove what the case created
# and may set:
#   E2E_SERIAL=1             the case changes appliance-wide settings; run.sh saves
#                            `fabric agent-gateway settings show` before setup and fails the case when the
#                            settings differ after cleanup
# and may carry a `# priority: P2` line: run.sh then runs it only when named or with
# E2E_PRIORITY=all.
#
# Available to case files:
#   fab ARGS...                    run fabric (the guarded wrapper) with the sandbox environment
#   expect_block N REGEX           block N's output (stdout+stderr) matches the extended regex
#   expect_fail_block N REGEX      block N was marked expect-fail, exited non-zero, and matches
#   expect_json N EXPR [WHAT]      the first JSON document in block N's output makes EXPR true;
#                                  `doc` is the document, `env` the environment (expr.py lists the
#                                  Python subset EXPR may use)
#   json_get FILE EXPR             print EXPR over the JSON in FILE (`doc`, `env`): a string as is,
#                                  anything else as JSON, like jq -r
#   unique NAME                    print NAME-$E2E_RUN_ID, a name no other run uses
#   start_target KIND [VAR] [--lan]
#                                  start `targets.py KIND` (mcp, a2a, a2a1, idp, rest) on a free port and
#                                  export VAR (default MCP_URL, A2A_URL, A2A1_URL, IDP_URL or REST_URL) as its
#                                  URL; --lan binds it to this machine's non-loopback IPv4 address,
#                                  exported as LAN_HOST, instead of 127.0.0.1, unless
#                                  E2E_LOOPBACK_TARGETS lists KIND: then it binds 127.0.0.1 on the
#                                  next listed port and exports LAN_HOST=127.0.0.1. Call it in setup,
#                                  not in a $(...); run.sh stops the target when the case ends
#   target_requests VAR            print the JSON list of requests the target at $VAR recorded
#   clear_target VAR               forget the requests the target at $VAR recorded
#   pass MESSAGE / fail MESSAGE [FILE]
#                                  report a check; fail ends the case and shows FILE's last lines
#
# Environment inside a case: HOME and XDG_CONFIG_HOME point into the sandbox, the saved connection
# is `e2e`, FABRIC_TOKEN holds the administrator token, GATEWAY the gateway URL, FABRIC the fabric
# wrapper, E2E_CASE the case name, E2E_CASE_DIR its work directory (block-N.out lives there),
# E2E_CASES_DIR the directory of case files, E2E_RUN_ID this run's id and PYTHON the interpreter.

pass() {
    printf '  ok: %s\n' "$*"
}

e2e_redact() {
    "$PYTHON" "$E2E_HERE/redact.py"
}

fail() {
    printf '  fail: %s\n' "$1" >&2
    if [ -n "${2:-}" ] && [ -f "$2" ]; then
        printf '  --- last lines of %s ---\n' "${2##*/}" >&2
        tail -n 20 "$2" | e2e_redact | sed 's/^/  | /' >&2
    fi
    exit 1
}

e2e_refuse() {
    printf '  refused: %s\n' "$*" >&2
    exit 3
}

fab() {
    "$FABRIC" "$@"
}

e2e_block_file() {
    printf '%s/block-%s.out' "$E2E_CASE_DIR" "$1"
}

e2e_block_expect() {
    awk -F '\t' -v n="$1" '$1 == n { print $2 }' "$E2E_CASE_DIR/.e2e/blocks"
}

expect_block() {
    local n=$1 re=$2 f
    f=$(e2e_block_file "$n")
    [ -f "$f" ] || fail "expect_block $n: block $n did not run"
    grep -Eq -- "$re" "$f" || fail "block $n output does not match /$re/" "$f"
    pass "block $n matches /$re/"
}

expect_fail_block() {
    local n=$1 re=$2 f rc
    f=$(e2e_block_file "$n")
    [ -f "$f" ] || fail "expect_fail_block $n: block $n did not run"
    [ "$(e2e_block_expect "$n")" = fail ] || fail "block $n is not marked expect-fail in its e2e marker"
    rc=$(cat "$E2E_CASE_DIR/block-$n.rc")
    [ "$rc" != 0 ] || fail "block $n exited 0 but was expected to fail" "$f"
    grep -Eq -- "$re" "$f" || fail "block $n failed, but its output does not match /$re/" "$f"
    pass "block $n failed as expected and matches /$re/"
}

# expr.py checks EXPR against its allowed grammar before it runs.
expect_json() {
    local n=$1 expr=$2 what=${3:-$2} f
    f=$(e2e_block_file "$n")
    [ -f "$f" ] || fail "expect_json $n: block $n did not run"
    "$PYTHON" "$E2E_HERE/expr.py" check "$f" "$expr" || fail "block $n: $what" "$f"
    pass "block $n: $what"
}

json_get() {
    [ "$#" -eq 2 ] || fail "json_get: expected FILE EXPR"
    [ -f "$1" ] || fail "json_get: no file $1"
    "$PYTHON" "$E2E_HERE/expr.py" get "$1" "$2" || fail "json_get: cannot evaluate $2 over $1" "$1"
}

unique() {
    [ "$#" -eq 1 ] && [ -n "$1" ] || fail "unique: expected one NAME"
    printf '%s-%s\n' "$1" "$E2E_RUN_ID"
}

# ---- test upstreams ----------------------------------------------------------------------------

E2E_VAR_RE='^[A-Za-z_][A-Za-z0-9_]*$'

# The first non-loopback IPv4 address of this machine, from the route to a documentation address.
# A UDP connect sends nothing.
e2e_lan_host() {
    [ -z "${LAN_HOST:-}" ] || return 0
    LAN_HOST=$("$PYTHON" -c 'import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    s.connect(("192.0.2.1", 9))
    ip = s.getsockname()[0]
except OSError:
    ip = ""
print("" if ip.startswith("127.") or ip in ("", "0.0.0.0") else ip)') || LAN_HOST=""
    [ -n "$LAN_HOST" ] || e2e_refuse "start_target --lan: this machine has no non-loopback IPv4 address with a route"
    export LAN_HOST
}

# E2E_LOOPBACK_TARGETS, checked by run.sh: KIND:PORT entries, comma-separated. Each names a fixed
# loopback port for a --lan target of that KIND, which the gateway under test accepts on 127.0.0.1.
e2e_loopback_listed() {
    case ",${E2E_LOOPBACK_TARGETS:-}," in *",$1:"*) return 0 ;; esac
    return 1
}

# The first port E2E_LOOPBACK_TARGETS lists for KIND that no target of this case uses yet.
e2e_loopback_port() {
    local entry
    for entry in $(printf '%s' "${E2E_LOOPBACK_TARGETS:-}" | tr ',' ' '); do
        [ "${entry%%:*}" = "$1" ] || continue
        case " ${E2E_LOOPBACK_USED:-} " in *" ${entry#*:} "*) continue ;; esac
        printf '%s' "${entry#*:}"
        return 0
    done
}

start_target() {
    local kind="" var="" lan=0 arg host=127.0.0.1 port=0 log pid url="" i=0
    for arg in "$@"; do
        case "$arg" in
            --lan) lan=1 ;;
            -*) fail "start_target: unknown option $arg" ;;
            *)
                if [ -z "$kind" ]; then kind=$arg
                elif [ -z "$var" ]; then var=$arg
                else fail "start_target: expected KIND [VAR] [--lan]"
                fi ;;
        esac
    done
    case "$kind" in
        mcp|a2a|a2a1|idp|rest) ;;
        *) fail "start_target: KIND must be mcp, a2a, a2a1, idp or rest, not '$kind'" ;;
    esac
    [ -n "$var" ] || var="$(printf '%s' "$kind" | tr '[:lower:]' '[:upper:]')_URL"
    printf '%s\n' "$var" | grep -Eq "$E2E_VAR_RE" || fail "start_target: '$var' is not a variable name"
    if [ "$lan" = 1 ] && e2e_loopback_listed "$kind"; then
        port=$(e2e_loopback_port "$kind")
        [ -n "$port" ] || e2e_refuse "start_target $kind --lan: every E2E_LOOPBACK_TARGETS port for $kind is already in use in this case"
        [ "${LAN_HOST:-127.0.0.1}" = 127.0.0.1 ] \
            || e2e_refuse "start_target $kind --lan: this case already has a target on the LAN address, and LAN_HOST cannot also be loopback"
        E2E_LOOPBACK_USED="${E2E_LOOPBACK_USED:-} $port"
        LAN_HOST=127.0.0.1
        export LAN_HOST
    elif [ "$lan" = 1 ]; then
        [ "${LAN_HOST:-}" != 127.0.0.1 ] \
            || e2e_refuse "start_target $kind --lan: this case already has a loopback target from E2E_LOOPBACK_TARGETS, and LAN_HOST cannot also be the LAN address"
        e2e_lan_host
        host=$LAN_HOST
    fi
    log="$E2E_CASE_DIR/.e2e/target-$var.log"
    [ -n "${E2E_RECORDER_SECRET:-}" ] || E2E_RECORDER_SECRET=$(od -An -tx1 -N16 /dev/urandom | tr -d ' \n')
    export E2E_RECORDER_SECRET
    # The test servers never need the gateway administrator token, so they never get it.
    env -u FABRIC_TOKEN -u FABRIC_E2E_TOKEN \
        "$PYTHON" "$E2E_HERE/targets.py" "$kind" --host "$host" --port "$port" > "$log" 2>&1 < /dev/null &
    pid=$!
    E2E_TARGET_PIDS="${E2E_TARGET_PIDS:-} $pid"
    while [ "$i" -lt 200 ]; do
        url=$(sed -n 's/^listening \(http:[^ ]*\)$/\1/p' "$log" | head -n 1)
        [ -z "$url" ] || break
        kill -0 "$pid" 2>/dev/null || fail "targets.py $kind exited before it listened" "$log"
        sleep 0.05
        i=$((i + 1))
    done
    [ -n "$url" ] || fail "targets.py $kind did not print a listening URL within 10 seconds" "$log"
    if [ "$lan" = 1 ] && [ "$host" != 127.0.0.1 ] && ! curl -fsS --noproxy '*' --max-time 5 -o /dev/null \
        -H "X-E2E-Recorder: $E2E_RECORDER_SECRET" "$url/_e2e/requests" 2>/dev/null; then
        e2e_refuse "start_target --lan: the $kind target listens on this machine's LAN address but does not answer a request from this machine, so the gateway cannot reach it either (something on this machine drops connections to its own LAN address)"
    fi
    export "$var=$url"
}

e2e_stop_targets() {
    local pid
    for pid in ${E2E_TARGET_PIDS:-}; do
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    done
    E2E_TARGET_PIDS=""
}

# The URL in the variable named $1, checked.
e2e_target_url() {
    local var=${1:-} url
    printf '%s\n' "$var" | grep -Eq "$E2E_VAR_RE" || fail "expected the name of a variable that holds a target URL, not '$var'"
    url=${!var:-}
    [ -n "$url" ] || fail "$var is not set; start the target with start_target first"
    printf '%s' "$url"
}

target_requests() {
    local url
    url=$(e2e_target_url "${1:-}") || exit 1
    curl -fsS --noproxy '*' --max-time 10 -H "X-E2E-Recorder: $E2E_RECORDER_SECRET" "$url/_e2e/requests" || fail "target_requests: GET $url/_e2e/requests failed"
}

clear_target() {
    local url
    url=$(e2e_target_url "${1:-}") || exit 1
    curl -fsS --noproxy '*' --max-time 10 -X DELETE -o /dev/null -H "X-E2E-Recorder: $E2E_RECORDER_SECRET" \
        "$url/_e2e/requests" \
        || fail "clear_target: DELETE $url/_e2e/requests failed"
}

# ---- the guard -------------------------------------------------------------------------------

# The sandbox must never offer a path to a real keychain.
e2e_check_sandbox() {
    case "$HOME" in
        "$E2E_WORK"/*) ;;
        *) e2e_refuse "HOME is not inside the sandbox" ;;
    esac
    if [ -e "$HOME/Library/Keychains" ] || [ -L "$HOME/Library/Keychains" ]; then
        e2e_refuse "the sandbox HOME has Library/Keychains; refusing so no recipe can reach a real keychain"
    fi
}

# Refuses the case when its file, a recipe block or a file a block writes names login, logout,
# config remove or agent-gateway shell, before any of it runs.
E2E_SCAN_RE='\blog(in|out)\b|config[[:space:]]+remove|agent-gateway[[:space:]]+shell\b'

# Prints NAME:LINE:TEXT for each match in FILE from line FROM (default 1) on. A file grep cannot
# read is a finding too.
e2e_scan_file() {
    local out rc=0
    out=$(grep -nE -- "$E2E_SCAN_RE" "$1") || rc=$?
    [ "$rc" -le 1 ] || printf '%s: cannot be read\n' "$1"
    printf '%s\n' "$out" | awk -F: -v from="${2:-1}" -v name="${1##*/}" 'NF && $1 >= from { print name ":" $0 }'
}

e2e_scan_case() {
    local f hits
    hits=$(
        e2e_scan_file "$E2E_CASE_FILE"
        # Line 1 of a block is its Markdown path, not code.
        for f in "$E2E_CASE_DIR"/.e2e/block-*.sh; do
            if [ -f "$f" ]; then e2e_scan_file "$f" 2; fi
        done
        for f in "$E2E_CASE_DIR"/* "$E2E_CASE_DIR"/.[!.]*; do
            if [ -f "$f" ]; then e2e_scan_file "$f"; fi
        done
    )
    [ -n "$hits" ] || return 0
    printf '%s\n' "$hits" | sed 's/^/  guard: /' >&2
    e2e_refuse "case $E2E_CASE names login, logout, config remove or agent-gateway shell (above), which reach the OS keychain or read commands from standard input"
}

e2e_guard_refusals() {
    wc -l < "$E2E_GUARD_LOG" | tr -d ' '
}

# ---- appliance-wide settings (E2E_SERIAL=1) ----------------------------------------------------

e2e_settings_snapshot() {
    [ "${E2E_SERIAL:-}" = 1 ] || return 0
    fab agent-gateway settings show -o json > "$E2E_CASE_DIR/.e2e/settings-before.json" \
        || fail "E2E_SERIAL=1: could not save the settings before the case"
}

e2e_settings_check() {
    [ "${E2E_SERIAL:-}" = 1 ] && [ -f "$E2E_CASE_DIR/.e2e/settings-before.json" ] || return 0
    local diff
    fab agent-gateway settings show -o json > "$E2E_CASE_DIR/.e2e/settings-after.json" || {
        printf '  fail: E2E_SERIAL=1: could not read the settings after the case\n' >&2
        return 1
    }
    diff=$("$PYTHON" - "$E2E_CASE_DIR/.e2e/settings-before.json" "$E2E_CASE_DIR/.e2e/settings-after.json" <<'PY'
import json, sys
before, after = (json.load(open(p, encoding="utf-8")) for p in sys.argv[1:3])
print(" ".join(sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))))
PY
    ) || {
        printf '  fail: E2E_SERIAL=1: could not compare the settings before and after the case\n' >&2
        return 1
    }
    if [ -n "$diff" ]; then
        printf '  fail: E2E_SERIAL=1: the case did not restore these settings: %s\n' "$diff" >&2
        return 1
    fi
    pass "the appliance-wide settings are as they were before the case"
}

# ---- running a case --------------------------------------------------------------------------

e2e_finish() {
    local status=$? cleanup_status
    set +e
    if declare -F cleanup >/dev/null; then
        (set -e; cleanup)
        cleanup_status=$?
        if [ "$cleanup_status" != 0 ]; then
            printf '  fail: cleanup exited %s; the case may have left resources behind\n' "$cleanup_status" >&2
            [ "$status" = 3 ] || status=1
        fi
    fi
    e2e_stop_targets
    if ! (e2e_settings_check); then
        [ "$status" = 3 ] || status=1
    fi
    exit "$status"
}

e2e_run_blocks() {
    local n expect src rc out refusals
    while IFS="$(printf '\t')" read -r n expect src; do
        [ -n "$n" ] || continue
        out="$E2E_CASE_DIR/block-$n.out"
        refusals=$(e2e_guard_refusals)
        set +e
        "$BASH" -euo pipefail "$E2E_CASE_DIR/.e2e/block-$n.sh" > "$out" 2>&1 < /dev/null
        rc=$?
        set -e
        printf '%s\n' "$rc" > "$E2E_CASE_DIR/block-$n.rc"
        if [ "$(e2e_guard_refusals)" != "$refusals" ]; then
            e2e_refuse "block $n ($src): the e2e guard refused a fabric call"
        fi
        if [ -e "$HOME/Library/Keychains" ] || [ -L "$HOME/Library/Keychains" ]; then
            fail "block $n ($src) created Library/Keychains in the sandbox HOME"
        fi
        if [ "$expect" = fail ]; then
            [ "$rc" != 0 ] || fail "block $n ($src) was marked expect-fail but exited 0" "$out"
        else
            [ "$rc" = 0 ] || fail "block $n ($src) exited $rc" "$out"
        fi
    done < "$E2E_CASE_DIR/.e2e/blocks"
}
