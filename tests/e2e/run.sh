#!/usr/bin/env bash
# Run the literate end-to-end cases against a live gateway. Never run in CI.
#
# Usage: tests/e2e/run.sh [CASE...]
#   With no CASE, runs every case that has recipe blocks under E2E_DOCS_ROOT and a case file,
#   except `# priority: P2` cases unless E2E_PRIORITY=all. A CASE named here always runs.
#
# Environment:
#   FABRIC_E2E_HOST   gateway URL, for example http://localhost:8080 (required)
#   FABRIC_E2E_TOKEN  administrator bearer token: session token or personal access token (required)
#   FABRIC            fabric binary (default: fabric on PATH)
#   E2E_DOCS_ROOT     Markdown holding the recipes (default: skills/)
#   E2E_CASES_DIR     directory of CASE.sh files (default: tests/e2e/cases)
#   E2E_PRIORITY=all  also run the `# priority: P2` cases when no CASE is named
#   E2E_RUN_ID        suffix `unique` adds to resource names: lowercase letters and digits
#                     (default: 8 random hex digits)
#   E2E_LOOPBACK_TARGETS  KIND:PORT[,KIND:PORT...]: `start_target KIND --lan` binds 127.0.0.1 on
#                     the next PORT listed for KIND instead of the LAN address, for a gateway that
#                     accepts those loopback URLs (see CONTRIBUTING.md, "A gateway to run against")
#   E2E_KEEP=1        keep the work directory, under .e2e-work/, for debugging (redacted)
#   PYTHON            Python 3 interpreter (default: python3)
#
# Each run gets a sandbox: HOME and XDG_CONFIG_HOME inside a fresh work directory, one saved
# connection `e2e`, the token passed as FABRIC_TOKEN, a D-Bus session address that reaches no bus
# and, on macOS, one throwaway keychain as the default and only keychain. `fabric` on PATH and
# $FABRIC are a wrapper that refuses anything that would make fabric read or write an OS keychain
# or start its interactive shell, and every case's file and recipe blocks are checked for sign-in,
# sign-out, `config remove` and `agent-gateway shell` before any of it runs. The real keychain
# state is read here only, never in a case; when it changes, the runner prints the saved state and
# the commands that restore it, and never runs them.
# On any system but macOS, a missing dbus-send refuses the run. Everything else the runner prints
# passes through tests/e2e/redact.py. Exit status: 0 when every case run passed, 1 otherwise, 2 on
# usage errors.
set -euo pipefail

E2E_HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
E2E_REPO=$(cd "$E2E_HERE/../.." && pwd -P)
PYTHON=${PYTHON:-python3}

usage() {
    awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "${BASH_SOURCE[0]}"
}

die() {
    printf 'run.sh: %s\n' "$*" >&2
    exit 2
}

case "${1:-}" in
    -h|--help) usage; exit 0 ;;
esac

# Nothing from the caller's environment may pre-set what the runner computes per run or per case.
unset E2E_REAL_HOME LAN_HOST E2E_TARGET_PIDS E2E_LOOPBACK_USED E2E_GUARD_LOG E2E_SERIAL

[ -n "${FABRIC_E2E_HOST:-}" ] || die "FABRIC_E2E_HOST is not set (the gateway URL, for example http://localhost:8080)"
[ -n "${FABRIC_E2E_TOKEN:-}" ] || die "FABRIC_E2E_TOKEN is not set (an administrator session token or personal access token)"
case "$FABRIC_E2E_HOST" in
    http://*|https://*) ;;
    *) die "FABRIC_E2E_HOST must start with http:// or https://" ;;
esac
case "$FABRIC_E2E_HOST" in
    *[[:space:]\"\\]*) die "FABRIC_E2E_HOST must not contain spaces, quotes or backslashes" ;;
esac
FABRIC_BIN=$(command -v "${FABRIC:-fabric}" 2>/dev/null) || die "fabric binary not found: ${FABRIC:-fabric} (set FABRIC)"
case "$FABRIC_BIN" in
    /*) ;;
    *) FABRIC_BIN="$(cd "$(dirname "$FABRIC_BIN")" && pwd -P)/$(basename "$FABRIC_BIN")" ;;
esac
command -v "$PYTHON" >/dev/null 2>&1 || die "Python not found: $PYTHON (set PYTHON)"
PYTHON=$(command -v "$PYTHON")
case "${E2E_PRIORITY:-}" in
    ""|all) ;;
    *) die "E2E_PRIORITY must be empty or all" ;;
esac
if [ -z "${E2E_RUN_ID:-}" ]; then
    E2E_RUN_ID=$(od -An -tx1 -N4 /dev/urandom | tr -d ' \n')
fi
case "$E2E_RUN_ID" in
    *[!a-z0-9]*) die "E2E_RUN_ID must be lowercase letters and digits only" ;;
esac
if [ -n "${E2E_LOOPBACK_TARGETS:-}" ]; then
    loopback_re='^(mcp|a2a|a2a1|idp|rest):[1-9][0-9]{0,4}(,(mcp|a2a|a2a1|idp|rest):[1-9][0-9]{0,4})*$'
    [[ $E2E_LOOPBACK_TARGETS =~ $loopback_re ]] \
        || die "E2E_LOOPBACK_TARGETS must be KIND:PORT entries separated by commas, KIND one of mcp, a2a, a2a1, idp or rest"
    for entry in ${E2E_LOOPBACK_TARGETS//,/ }; do
        [ "${entry#*:}" -le 65535 ] || die "E2E_LOOPBACK_TARGETS port ${entry#*:} is above 65535"
    done
fi

E2E_DOCS_ROOT=${E2E_DOCS_ROOT:-skills/}
case "$E2E_DOCS_ROOT" in /*) ;; *) E2E_DOCS_ROOT="$E2E_REPO/$E2E_DOCS_ROOT" ;; esac
E2E_CASES_DIR=${E2E_CASES_DIR:-$E2E_HERE/cases}
case "$E2E_CASES_DIR" in /*) ;; *) E2E_CASES_DIR="$E2E_REPO/$E2E_CASES_DIR" ;; esac
[ -e "$E2E_DOCS_ROOT" ] || die "E2E_DOCS_ROOT does not exist: $E2E_DOCS_ROOT"

if [ "${E2E_KEEP:-}" = 1 ]; then
    mkdir -p "$E2E_REPO/.e2e-work"
    E2E_WORK=$(mktemp -d "$E2E_REPO/.e2e-work/run.XXXXXX")
else
    E2E_WORK=$(mktemp -d "${TMPDIR:-/tmp}/fabric-e2e.XXXXXX")
fi
E2E_WORK=$(cd "$E2E_WORK" && pwd -P)
remove_work() {
    if [ "${E2E_KEEP:-}" = 1 ]; then
        "$PYTHON" "$E2E_HERE/redact.py" --tree "$E2E_WORK" || printf 'run.sh: could not redact %s\n' "$E2E_WORK" >&2
        printf 'run.sh: kept the work directory %s\n' "$E2E_WORK" >&2
    else
        rm -rf "$E2E_WORK"
    fi
}

refuse_run() {
    printf 'run.sh: refused: %s\n' "$*" >&2
    printf 'e2e: FAILED, refused before any case ran\n'
    exit 1
}

# macOS: one throwaway keychain for the run. The real search list and default keychain are read
# with the real HOME, which is kept in this shell only and never exported. The two labels start in
# column 0 and security indents every path, so keychain_restore_hint can split the saved state.
real_keychains() {
    local list default
    list=$(HOME="$real_home" security list-keychains -d user 2>&1) || return 1
    default=$(HOME="$real_home" security default-keychain -d user 2>&1) || return 1
    printf 'search list:\n%s\ndefault keychain:\n%s\n' "$list" "$default"
}

# Prints, once, the real state saved before the run and the commands that restore it. It never
# runs them: whoever runs the tests decides.
keychain_restore_hint() {
    [ -z "${kc_hint_shown:-}" ] || return 0
    kc_hint_shown=1
    local unquote='s/^[[:space:]]*"\(.*\)"[[:space:]]*$/\1/p' list default p
    list=$(printf '%s\n' "$kc_before" | awk '/^default keychain:$/ { exit } NR > 1' | sed -n "$unquote")
    default=$(printf '%s\n' "$kc_before" | awk 'found; /^default keychain:$/ { found = 1 }' | sed -n "$unquote" | head -n 1)
    {
        printf 'run.sh: the real keychain state before the run was:\n'
        printf '%s\n' "$kc_before" | sed 's/^/    /'
        printf 'run.sh: to restore it, run these yourself; run.sh does not run them:\n'
        printf '    security list-keychains -d user -s'
        while IFS= read -r p; do
            [ -z "$p" ] || printf ' %q' "$p"
        done <<EOF
$list
EOF
        printf '\n'
        if [ -n "$default" ]; then
            printf '    security default-keychain -d user -s %q\n' "$default"
        else
            printf '    (no default keychain was reported before the run, so there is none to restore)\n'
        fi
    } >&2
}

keychain_start() {
    local view p pw
    command -v security >/dev/null 2>&1 || refuse_run "security(1) is not available"
    kc_before=$(real_keychains) || refuse_run "cannot read the keychain search list"
    view=$( { security list-keychains -d user; security default-keychain -d user; } 2>/dev/null || true)
    while IFS= read -r p; do
        p=$(printf '%s\n' "$p" | sed -n 's/^[[:space:]]*"\(.*\)"[[:space:]]*$/\1/p')
        [ -n "$p" ] || continue
        case "$p" in
            "$E2E_WORK"/*) ;;
            *) refuse_run "security does not isolate keychain preferences under the sandbox HOME (it reports $p)" ;;
        esac
    done <<EOF
$view
EOF
    mkdir -p "$E2E_WORK/keychains"
    kc="$E2E_WORK/keychains/run.keychain-db"
    pw=$(od -An -tx1 -N16 /dev/urandom | tr -d ' \n')
    kc_created=1
    # The probe: create-keychain adds the new keychain to the search list security sees, so a leak
    # shows here, before the search list is replaced below.
    security create-keychain -p "$pw" "$kc" >/dev/null
    if [ "$(real_keychains)" != "$kc_before" ]; then
        keychain_restore_hint
        refuse_run "creating a keychain under the sandbox HOME changed the real keychain search list"
    fi
    security list-keychains -d user -s "$kc" >/dev/null
    security default-keychain -d user -s "$kc" >/dev/null
    security unlock-keychain -p "$pw" "$kc" >/dev/null
    if [ "$(real_keychains)" != "$kc_before" ]; then
        keychain_restore_hint
        refuse_run "setting the sandbox keychain search list changed the real one"
    fi
}

keychain_stop() {
    [ -n "${kc_created:-}" ] || return 0
    kc_created=
    local status=0
    if ! security delete-keychain "$kc" >/dev/null 2>&1 || [ -e "$kc" ]; then
        printf 'run.sh: could not delete the throwaway keychain\n' >&2
        status=1
    fi
    if [ "$(real_keychains)" != "$kc_before" ]; then
        printf 'run.sh: the real keychain search list or default keychain changed during the run\n' >&2
        keychain_restore_hint
        status=1
    elif [ -n "${kc_hint_shown:-}" ]; then
        printf 'run.sh: after the throwaway keychain was deleted, the real keychain state matches the saved state again\n' >&2
    fi
    return "$status"
}

finish_run() {
    local status=$?
    keychain_stop || status=1
    remove_work
    exit "$status"
}
trap finish_run EXIT

# The sandbox. Everything below runs with it.
real_home=${HOME:-}
export E2E_WORK E2E_DOCS_ROOT E2E_CASES_DIR E2E_HERE E2E_RUN_ID PYTHON
export HOME="$E2E_WORK/home"
export XDG_CONFIG_HOME="$HOME/.config"
mkdir -p "$XDG_CONFIG_HOME"
case "$(uname -s)" in
    Darwin) config_dir="$HOME/Library/Application Support/fabric" ;;
    *) config_dir="$XDG_CONFIG_HOME/fabric" ;;
esac
mkdir -p "$config_dir"
printf 'current = "e2e"\n\n[connections.e2e]\nhost = "%s"\n' "$FABRIC_E2E_HOST" > "$config_dir/config.toml"
chmod 600 "$config_dir/config.toml"

# Linux: fabric's keyring reaches the Secret Service over the D-Bus session bus. Point the bus
# address at a socket that does not exist, keep XDG_RUNTIME_DIR (where a D-Bus client looks for a
# bus when no address is set) inside the sandbox, and drop the display variables a D-Bus client can
# autolaunch a bus from. Then prove it with dbus-send, with the address as
# fabric sees it and without it, as a block that unsets it would; no dbus-send means no proof.
export DBUS_SESSION_BUS_ADDRESS="unix:path=$E2E_WORK/no-bus" XDG_RUNTIME_DIR="$E2E_WORK/run"
unset DISPLAY WAYLAND_DISPLAY
mkdir -m 700 "$XDG_RUNTIME_DIR"
session_bus_answers() {
    dbus-send --session --print-reply --reply-timeout=2000 --dest=org.freedesktop.DBus / \
        org.freedesktop.DBus.ListNames >/dev/null 2>&1
}
if [ "$(uname -s)" != Darwin ]; then
    command -v dbus-send >/dev/null 2>&1 || refuse_run "dbus-send is not available, so nothing can prove that" \
        "fabric's keyring has no D-Bus session bus to reach; install the D-Bus tools (the dbus package)"
    if session_bus_answers || (unset DBUS_SESSION_BUS_ADDRESS; session_bus_answers); then
        refuse_run "a D-Bus session bus answers inside the sandbox, so fabric could reach a real keyring"
    fi
fi

# The fabric wrapper. Paths are written into it, so nothing a case does to its environment can point
# it at another configuration, HOME or binary. A refusal is appended to E2E_GUARD_LOG, which lib.sh
# checks after every block and the loop below checks after every case.
E2E_GUARD_LOG="$E2E_WORK/.guard-refusals"
: > "$E2E_GUARD_LOG"
mkdir -p "$E2E_WORK/bin"
{
    printf '#!/bin/bash\n'
    printf '# Written by tests/e2e/run.sh: refuses every fabric call that could reach an OS keychain or start its shell.\n'
    printf 'real=%q\nconfig=%q\nhome=%q\nxdg=%q\nlog=%q\n' \
        "$FABRIC_BIN" "$config_dir/config.toml" "$HOME" "$XDG_CONFIG_HOME" "$E2E_GUARD_LOG"
    cat <<'WRAPPER'
refuse() {
    printf '%s\n' "$1" >> "$log"
    printf 'e2e guard: refused a fabric call: %s\n' "$1" >&2
    exit 3
}
[ "${HOME:-}" = "$home" ] && [ "${XDG_CONFIG_HOME:-}" = "$xdg" ] \
    || refuse "runs fabric with HOME or XDG_CONFIG_HOME outside the sandbox"
[ -n "${FABRIC_TOKEN:-}" ] || refuse "runs fabric with FABRIC_TOKEN empty, so it would read the OS keychain"
# Every command is under the group word agent-gateway, which the global options follow, then the
# subcommand; before the group, fabric takes only --help and --version. `agent-gateway shell` is
# fabric's interactive shell, which reads commands from standard input. A call with no subcommand
# is refused too, in case the binary starts that shell for it. Skip the global
# options and their values, as `fabric agent-gateway --help` lists them.
group=
skip=
found=
for arg in "$@"; do
    if [ -n "$skip" ]; then
        skip=
        continue
    fi
    if [ -z "$group" ]; then
        case "$arg" in
            agent-gateway) group=1 ;;
            -h|--help|-V|--version|[!-]*) found=1; break ;;
            *) refuse "runs fabric with ${arg%%=*} before agent-gateway, where fabric takes only --help and --version" ;;
        esac
        continue
    fi
    case "$arg" in
        -c|--connection|--host|--token|-o|--output) skip=1 ;;
        --connection=*|--host=*|--token=*|--output=*|-c?*|-o?*|--allow-http|--) ;;
        shell) refuse "runs fabric agent-gateway shell, the interactive shell, which reads commands from standard input" ;;
        -h|--help|[!-]*) found=1; break ;;
        *) refuse "runs fabric with ${arg%%=*} before any subcommand, an option this wrapper does not know, so it cannot tell whether a subcommand follows" ;;
    esac
done
[ -n "$found" ] || refuse "runs fabric with no subcommand after agent-gateway"
if grep -Eq '(^|[^[:alnum:]_-])token[^[:alnum:]_-]*=' "$config"; then
    refuse "the sandbox config holds a token line, which fabric moves into the OS keychain"
fi
after_config=
for arg in "$@"; do
    case "$arg" in
        login|logout) refuse "runs fabric $arg, which writes the OS keychain" ;;
        config) after_config=1 ;;
        remove) [ -z "$after_config" ] || refuse "runs fabric config remove, which deletes a keychain entry" ;;
    esac
done
exec "$real" "$@"
WRAPPER
} > "$E2E_WORK/bin/fabric"
chmod 755 "$E2E_WORK/bin/fabric"
export PATH="$E2E_WORK/bin:$PATH"
export FABRIC="$E2E_WORK/bin/fabric" GATEWAY="$FABRIC_E2E_HOST" FABRIC_TOKEN="$FABRIC_E2E_TOKEN" NO_COLOR=1
export E2E_GUARD_LOG
unset FABRIC_E2E_TOKEN FABRIC_HOST FABRIC_CONNECTION FABRIC_PAT FABRIC_BIN

redact() {
    "$PYTHON" "$E2E_HERE/redact.py"
}

run_case() (
    set -euo pipefail
    unset real_home kc_before kc kc_created kc_hint_shown
    unset -f real_keychains keychain_restore_hint keychain_start keychain_stop finish_run remove_work refuse_run
    E2E_CASE=$1
    E2E_CASE_DIR="$E2E_WORK/$E2E_CASE"
    export E2E_CASE E2E_CASE_DIR
    mkdir -p "$E2E_CASE_DIR"
    . "$E2E_HERE/lib.sh"
    e2e_check_sandbox
    E2E_CASE_FILE="$E2E_CASES_DIR/$E2E_CASE.sh"
    [ -f "$E2E_CASE_FILE" ] || e2e_refuse "no case file $E2E_CASE_FILE"
    "$PYTHON" "$E2E_HERE/extract.py" --root "$E2E_DOCS_ROOT" emit "$E2E_CASE" "$E2E_CASE_DIR" >&2 \
        || e2e_refuse "could not extract the recipe blocks of $E2E_CASE"
    e2e_scan_case
    E2E_SERIAL=
    . "$E2E_CASE_FILE"
    trap e2e_finish EXIT
    cd "$E2E_CASE_DIR"
    e2e_settings_snapshot
    if declare -F setup >/dev/null; then
        setup
    fi
    e2e_run_blocks
    if declare -F verify >/dev/null; then
        verify
    fi
)

listing=$("$PYTHON" "$E2E_HERE/extract.py" --root "$E2E_DOCS_ROOT" list) || {
    printf '%s\n' "$listing"
    printf 'run.sh: the e2e markers under %s have problems\n' "$E2E_DOCS_ROOT" >&2
    exit 1
}

cases=()
excluded=()
if [ "$#" -gt 0 ]; then
    cases=("$@")
else
    while IFS="$(printf '\t')" read -r name source; do
        [ -n "$name" ] || continue
        if [ ! -f "$E2E_CASES_DIR/$name.sh" ]; then
            printf 'run.sh: note: %s (%s) has recipe blocks but no case file; not run\n' "$name" "$source" >&2
            continue
        fi
        priority=$(sed -n 's/^#[[:space:]]*priority:[[:space:]]*\([^[:space:]]*\).*/\1/p' "$E2E_CASES_DIR/$name.sh" \
            | head -n 1 || true)
        if [ "$priority" = P2 ] && [ "${E2E_PRIORITY:-}" != all ]; then
            excluded+=("$name")
            continue
        fi
        cases+=("$name")
    done <<EOF
$listing
EOF
fi
for name in ${excluded[@]+"${excluded[@]}"}; do
    printf 'EXCLUDED %s (priority P2; set E2E_PRIORITY=all or name the case to run it)\n' "$name"
done
if [ "${#cases[@]}" -eq 0 ]; then
    printf 'run.sh: no e2e cases to run under %s\n' "$E2E_DOCS_ROOT" >&2
    printf 'e2e: FAILED, no cases ran\n'
    exit 1
fi

if [ "$(uname -s)" = Darwin ]; then
    keychain_start
fi

passed=0
failed=0
refused=0
for name in "${cases[@]}"; do
    printf 'RUN     %s\n' "$name"
    before=$(wc -l < "$E2E_GUARD_LOG")
    set +e
    run_case "$name" 2> >(redact >&2) | redact
    status=${PIPESTATUS[0]}
    set -e
    if [ "$(wc -l < "$E2E_GUARD_LOG")" -gt "$before" ]; then
        sed -n "$((before + 1)),\$p" "$E2E_GUARD_LOG" | sed 's/^/  refused: the e2e guard refused a fabric call: /' | redact >&2
        status=3
    fi
    case "$status" in
        0) passed=$((passed + 1)); printf 'PASS    %s\n' "$name" ;;
        3) refused=$((refused + 1)); printf 'REFUSED %s\n' "$name" ;;
        *) failed=$((failed + 1)); printf 'FAIL    %s\n' "$name" ;;
    esac
done

total=${#cases[@]}
if ! keychain_stop; then
    printf 'e2e: FAILED, the keychain check at the end of the run failed (%d cases)\n' "$total"
    exit 1
fi
tail_note=""
if [ "${#excluded[@]}" -gt 0 ]; then
    tail_note="; excluded ${#excluded[@]} P2: ${excluded[*]}"
fi
if [ $((failed + refused)) -gt 0 ]; then
    printf 'e2e: FAILED, %d passed, %d failed, %d refused (%d cases)%s\n' "$passed" "$failed" "$refused" "$total" "$tail_note"
    exit 1
fi
printf 'e2e: OK, %d passed (%d cases)%s\n' "$passed" "$total" "$tail_note"
