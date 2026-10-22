"""Offline characterization helpers for the upstream root-layout integration.

The real Home Assistant imports are intentionally not executed here: upstream's
flat HACS layout and its current HA compatibility are separate refactor tasks.
Instead, tests execute selected unchanged definitions from the source AST.
"""

import ast
import copy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def source_definition(filename, name, namespace=None, methods=None, base=None):
    """Compile one actual source definition with explicit test dependencies.

    This is not a replacement for HA integration tests. It makes behavioral
    baseline tests runnable without a Home Assistant installation or network.
    """
    source = (ROOT / filename).read_text(encoding="utf-8")
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
    exec(compile(module, str(ROOT / filename), "exec"), scope)
    return scope[name]


@pytest.fixture(scope="session")
def forecast_payload():
    """Synthetic, deterministic client-model-shaped weather forecast."""
    import json

    return json.loads((ROOT / "tests/fixtures/forecast.json").read_text())
