import ast
from pathlib import Path

import pytest


def test_list_episodes_defines_offset_parameter_and_applies_it():
    path = Path(__file__).resolve().parents[1] / "app/routers/api_episodes.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    list_fn = next(
        node for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "list_episodes"
    )

    arg_names = [arg.arg for arg in list_fn.args.args]
    assert "offset" in arg_names
    assert "limit" in arg_names

    defaults_by_arg = {}
    positional_args = list_fn.args.args
    defaults = list_fn.args.defaults
    first_default_index = len(positional_args) - len(defaults)
    for idx, arg in enumerate(positional_args):
        if idx >= first_default_index:
            defaults_by_arg[arg.arg] = defaults[idx - first_default_index]

    limit_default = defaults_by_arg["limit"]
    assert isinstance(limit_default, ast.Call)
    assert isinstance(limit_default.func, ast.Name)
    assert limit_default.func.id == "Query"

    default_kw = next(
        kw for kw in limit_default.keywords
        if kw.arg == "default"
    )
    assert isinstance(default_kw.value, ast.Constant)
    assert default_kw.value.value == 200

    offset_used = False
    for node in ast.walk(list_fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "offset":
                offset_used = True
                break

    assert offset_used
