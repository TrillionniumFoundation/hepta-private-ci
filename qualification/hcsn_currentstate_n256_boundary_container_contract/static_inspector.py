"""Static guards for the source-only boundary container contract."""

import ast
from pathlib import Path


HERE = Path(__file__).resolve().parent
FILES = (HERE / "boundary_codec.py", HERE / "compare_boundary.py")


def _roots(tree):
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(item.name.split(".")[0] for item in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def verify():
    forbidden_imports = {"numpy", "scipy", "torch", "jax", "tensorflow", "subprocess"}
    forbidden_calls = {"eval", "exec", "compile", "__import__"}
    for path in FILES:
        text = path.read_text()
        tree = ast.parse(text)
        if _roots(tree) & forbidden_imports:
            raise ValueError(f"forbidden import: {path.name}")
        calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        if calls & forbidden_calls:
            raise ValueError(f"dynamic execution: {path.name}")
        if path.name == "compare_boundary.py" and "boundary_codec" in text:
            raise ValueError("comparator is not independent")
    return {
        "status": "PASS_STATIC_CONTAINER_HOLD",
        "files": 2,
        "authentic_boundary_calls": 0,
    }
