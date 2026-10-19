#!/usr/bin/env bash
# Report what changed upstream since the reviewed commits, page by page. A report only: it never
# edits anything, and it exits 0 whatever it finds (2 on usage errors, and when a git command fails,
# so that a failure never reads as "unchanged").
#
# Usage: scripts/drift-report.sh GATEWAY_CLONE GATEWAY_REF [FABRIC_CLI_CLONE FABRIC_CLI_REF]
#   FABRIC=path/to/fabric   also compare .github/fabric-cli-snapshot.json with that binary
#
# The skill rests on two upstream repositories: the Agent Gateway source and the fabric CLI. The
# baselines are .github/skill-drift-matrix.json's baseline.agent_gateway and baseline.fabric_cli.
# A matrix path that starts with affinidi-trust-fabric-cli/ is a path in the CLI repository with that prefix
# removed; every other path is in the gateway repository. Without the CLI clone and ref, the CLI
# paths are not compared and the report says so.
#
# For each page, it prints the page's source paths that changed between the baseline and the new
# ref (git diff --name-status -M), with renames as `old -> new`, and each file's added and deleted
# lines (git diff --numstat), so that a large change stands out from a one-line edit in a file many
# pages name. A rename shows only when both paths are in the page's entry; otherwise it shows as a
# delete here and the new path is listed below. Then it prints changed files under the gateway's
# src/ and config/, and the CLI's src/, that no page names, leaving out test code
# (src/component_tests/, tests/ directories, *_tests.rs and *.test.rs). It never fetches: each
# baseline and new ref must already be in its clone. If a baseline is not, it says so and lists
# every page as changed.
set -uo pipefail

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
MATRIX="$REPO/.github/skill-drift-matrix.json"
CLI_PREFIX="affinidi-trust-fabric-cli/"

usage() {
    awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "${BASH_SOURCE[0]}"
}

die() {
    printf 'drift-report.sh: %s\n' "$*" >&2
    exit 2
}

case "${1:-}" in
    -h|--help) usage; exit 0 ;;
esac
[ "$#" -eq 2 ] || [ "$#" -eq 4 ] || { usage >&2; exit 2; }
command -v jq >/dev/null 2>&1 || die "jq is required"

gw_clone=$1
git -C "$gw_clone" rev-parse --git-dir >/dev/null 2>&1 || die "not a git clone: $gw_clone"
gw_new=$(git -C "$gw_clone" rev-parse --verify --quiet "$2^{commit}") || die "$2 is not a commit in $gw_clone"
gw_base=$(jq -er '.baseline.agent_gateway' "$MATRIX") || die "cannot read baseline.agent_gateway from $MATRIX"

cli_clone="" cli_new="" cli_base=""
if [ "$#" -eq 4 ]; then
    cli_clone=$3
    git -C "$cli_clone" rev-parse --git-dir >/dev/null 2>&1 || die "not a git clone: $cli_clone"
    cli_new=$(git -C "$cli_clone" rev-parse --verify --quiet "$4^{commit}") || die "$4 is not a commit in $cli_clone"
    cli_base=$(jq -er '.baseline.fabric_cli' "$MATRIX") || die "cannot read baseline.fabric_cli from $MATRIX"
fi

pages=()
while IFS= read -r page; do pages+=("$page"); done < <(jq -r '.pages | keys_unsorted[]' "$MATRIX")

# Test code, which no page describes: left out of the list of files in no page's entry.
TEST_PATHS=(':(exclude)src/component_tests' ':(exclude,glob)**/tests/**' ':(exclude,glob)**/*_tests.rs'
            ':(exclude,glob)**/*.test.rs')

# changes CLONE BASE NEW SHOWN_PREFIX -- PATHSPEC...
# Prints the changes between BASE and NEW for the pathspecs, one per line: STATUS PATH (+ADDED
# -DELETED), or STATUS OLD -> NEW (...) for a rename or copy, with SHOWN_PREFIX in front of each
# path. It fails when git fails. --name-status and --numstat list the same changes in the same
# order, so their lines are paired.
changes() {
    local clone=$1 base=$2 new=$3 prefix=$4 status numstat
    shift 4
    status=$(git -C "$clone" diff --name-status -M "$base" "$new" "$@") || return 1
    numstat=$(git -C "$clone" diff --numstat -M "$base" "$new" "$@") || return 1
    [ -n "$status" ] || return 0
    paste <(printf '%s\n' "$status") <(printf '%s\n' "$numstat") | awk -F '\t' -v p="$prefix" '
        { rename = ($1 ~ /^[RC]/); a = rename ? $4 : $3; d = rename ? $5 : $4
          count = (a == "-") ? "binary" : sprintf("+%s -%s", a, d)
          if (rename) printf "  %-4s %s%s -> %s%s (%s)\n", substr($1, 1, 1), p, $2, p, $3, count
          else printf "  %-4s %s%s (%s)\n", $1, p, $2, count }'
}

printf 'Gateway: baseline %s, new %s\n' "$gw_base" "$gw_new"
if [ -n "$cli_clone" ]; then
    printf 'fabric CLI: baseline %s, new %s\n\n' "$cli_base" "$cli_new"
else
    printf 'fabric CLI: not compared; pass FABRIC_CLI_CLONE and FABRIC_CLI_REF to compare its paths.\n\n'
fi

missing=()
git -C "$gw_clone" cat-file -e "$gw_base^{commit}" 2>/dev/null || missing+=("the gateway baseline is not in $gw_clone")
if [ -n "$cli_clone" ]; then
    git -C "$cli_clone" cat-file -e "$cli_base^{commit}" 2>/dev/null || missing+=("the fabric CLI baseline is not in $cli_clone")
fi

if [ "${#missing[@]}" -gt 0 ]; then
    printf 'The baseline is not in this clone (%s), so nothing can be compared. Treat every page as changed:\n' \
        "$(IFS=';'; printf '%s' "${missing[*]}")"
    printf '  %s\n' "${pages[@]}"
else
    unchanged=()
    for page in "${pages[@]}"; do
        gw_paths=() cli_paths=()
        while IFS= read -r p; do
            case "$p" in
                "$CLI_PREFIX"*) cli_paths+=("${p#"$CLI_PREFIX"}") ;;
                *) gw_paths+=("$p") ;;
            esac
        done < <(jq -r --arg p "$page" '.pages[$p].source_paths[]' "$MATRIX")
        total=$(( ${#gw_paths[@]} + ${#cli_paths[@]} ))
        changed=""
        if [ "${#gw_paths[@]}" -gt 0 ]; then
            changed=$(changes "$gw_clone" "$gw_base" "$gw_new" "" -- "${gw_paths[@]}") \
                || die "git diff failed for the source paths of $page (above)"
        fi
        if [ -n "$cli_clone" ] && [ "${#cli_paths[@]}" -gt 0 ]; then
            cli_changed=$(changes "$cli_clone" "$cli_base" "$cli_new" "$CLI_PREFIX" -- "${cli_paths[@]}") \
                || die "git diff failed for the fabric CLI source paths of $page (above)"
            if [ -n "$cli_changed" ]; then
                changed=$(printf '%s\n%s' "$changed" "$cli_changed" | sed '/^$/d')
            fi
        fi
        if [ -z "$changed" ]; then
            unchanged+=("$page")
            continue
        fi
        printf '%s: %d of %d source paths changed\n' "$page" "$(printf '%s\n' "$changed" | wc -l | tr -d ' ')" "$total"
        printf '%s\n\n' "$changed"
    done
    printf 'Unchanged: %d pages\n' "${#unchanged[@]}"
    [ "${#unchanged[@]}" -eq 0 ] || printf '  %s\n' "${unchanged[@]}"
    printf '\n'

    gw_excludes=() cli_excludes=()
    while IFS= read -r p; do
        case "$p" in
            "$CLI_PREFIX"*) cli_excludes+=(":(exclude)${p#"$CLI_PREFIX"}") ;;
            *) gw_excludes+=(":(exclude)$p") ;;
        esac
    done < <(jq -r '[.pages[].source_paths[]] | unique[]' "$MATRIX")
    unowned=$(changes "$gw_clone" "$gw_base" "$gw_new" "" -- src config \
        ${gw_excludes[@]+"${gw_excludes[@]}"} "${TEST_PATHS[@]}") \
        || die "git diff failed for the files in no page's entry (above)"
    if [ -n "$cli_clone" ]; then
        cli_unowned=$(changes "$cli_clone" "$cli_base" "$cli_new" "$CLI_PREFIX" -- src \
            ${cli_excludes[@]+"${cli_excludes[@]}"} "${TEST_PATHS[@]}") \
            || die "git diff failed for the fabric CLI files in no page's entry (above)"
        [ -z "$cli_unowned" ] || unowned=$(printf '%s\n%s' "$unowned" "$cli_unowned" | sed '/^$/d')
    fi
    printf 'Changed under the gateway'"'"'s src/ and config/ and the CLI'"'"'s src/ but in no page'"'"'s entry, test code left out: %d\n' \
        "$( [ -z "$unowned" ] && echo 0 || printf '%s\n' "$unowned" | wc -l | tr -d ' ')"
    [ -z "$unowned" ] || printf '%s\n' "$unowned"
fi

printf '\n'
if [ -n "${FABRIC:-}" ]; then
    printf 'CLI snapshot against %s:\n' "$FABRIC"
    "${PYTHON:-python3}" "$REPO/scripts/gen-cli-reference.py" --check --fabric "$FABRIC"
    case $? in
        0) printf 'The CLI snapshot matches.\n' ;;
        1) printf 'The CLI snapshot differs (above); run make cli-reference FABRIC=%s and review the diff.\n' "$FABRIC" ;;
        *) printf 'The CLI snapshot could not be compared (above).\n' ;;
    esac
else
    printf 'CLI snapshot: not compared; set FABRIC to a fabric binary built from the new fabric CLI ref.\n'
fi
exit 0
