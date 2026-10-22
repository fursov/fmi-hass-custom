#!/usr/bin/env bash
# Run characterization tests independently of the custom integration package.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
test_root="$(mktemp -d)"
trap 'rm -rf "$test_root"' EXIT

cp -R "$repo_root/tests" "$test_root/tests"
(
    cd "$test_root"
    FMI_SOURCE_ROOT="$repo_root" python -m pytest -q tests -o xfail_strict=true
)
