"""Offline characterization helpers for the FMI custom integration.

The real Home Assistant imports are intentionally not executed here.
Tests execute selected definitions from the source AST without starting HA.
"""

import ast
import copy
import os
from pathlib import Path

import pytest

ROOT = Path(os.environ.get("FMI_SOURCE_ROOT", Path(__file__).resolve().parents[1]))
SOURCE_ROOT = ROOT / "custom_components" / "fmi"


def source_definition(filename, name, namespace=None, methods=None, base=None):
    """Compile one actual source definition with explicit test dependencies.

    This is not a replacement for HA integration tests. It makes behavioral
    baseline tests runnable without a Home Assistant installation or network.
    """
    source = (SOURCE_ROOT / filename).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=filename)
    matches = [
        node
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    ]
    if len(matches) != 1:
        raise AssertionError(f"Expected exactly one {name} in {filename}")

    node = copy.deepcopy(matches[0])
    if isinstance(node, ast.ClassDef):
        if methods is not None:
            node.body = [
                member
                for member in node.body
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
                and member.name in methods
            ]
        if base is not None:
            node.bases = [ast.Name(id=base, ctx=ast.Load())]
            node.keywords = []
        node.decorator_list = []

    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    scope = dict(namespace or {})
    # Only definitions read from this checked-out repository are executed.
    exec(compile(module, str(SOURCE_ROOT / filename), "exec"), scope)  # noqa: S102
    return scope[name]


@pytest.fixture(scope="session")
def forecast_payload():
    """Synthetic, deterministic client-model-shaped weather forecast."""
    import json

    return json.loads((ROOT / "tests/fixtures/forecast.json").read_text())
