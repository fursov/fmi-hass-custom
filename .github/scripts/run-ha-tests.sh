#!/usr/bin/env bash
# Exercise the checked-in HACS package layout in a separate HA pytest environment.
# Copy the integration directory as-is; do not repackage or rewrite its contents.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
test_root="$(mktemp -d)"
trap 'rm -rf "$test_root"' EXIT

mkdir -p "$test_root/custom_components" "$test_root/integration_tests"
touch "$test_root/custom_components/__init__.py"

cp -R "$repo_root/custom_components/fmi" "$test_root/custom_components/fmi"
cp -R "$repo_root/integration_tests/." "$test_root/integration_tests/"

cat > "$test_root/pytest.ini" <<'PYTEST'
[pytest]
asyncio_mode = auto
asyncio_default_fixture_loop_scope = function
addopts = -ra
PYTEST

(
  cd "$test_root"
  export PYTHONPATH="$test_root"
  python -m pytest -q integration_tests
)
