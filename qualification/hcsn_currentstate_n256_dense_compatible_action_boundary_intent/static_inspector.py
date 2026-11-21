"""Standard-library inspection of the unexecuted action-boundary source."""

import ast
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ACTION = HERE / "action_boundary.py"
ORACLE = (
    ROOT
    / "qualification/hcsn_currentstate_n256_firststep_dense_oracle_source/dense_oracle.py"
)


def function(tree, name):
    matches = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
    if len(matches) != 1:
        raise ValueError(f"function identity: {name}")
    return matches[0]


def literals(tree):
    result = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                result[target.id] = ast.literal_eval(node.value)
    return result


def imported_roots(tree):
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def verify():
    action_text = ACTION.read_text()
    action_tree = ast.parse(action_text)
    oracle_tree = ast.parse(ORACLE.read_text())
    values = literals(action_tree)
    expected = {
        "EXECUTION_ALLOWED": False,
        "BOUNDARY_COORDINATES": 68105,
        "EXTENDED_GENERATOR_SHAPE": (257, 257),
        "INITIAL_SHAPE": (5, 257),
        "SELECTOR_SHAPES": ((257, 1), (257, 2)),
        "DURATION_NUMERATOR": 1,
        "DURATION_DENOMINATOR": 1000,
        "DISCOUNT_HEX": ("0x0.0p+0", "0x1.3333333333333p-3"),
        "AUGMENTED_DIMENSIONS": (258, 259),
        "ACTION_ORDER": ("undiscounted_hit", "discounted_hit_and_occupation"),
    }
    if values != expected:
        raise ValueError("boundary constants")
    action_fn = function(action_tree, "dense_compatible_stream_action")
    oracle_fn = function(oracle_tree, "_stream_action")
    action_signature = ast.dump(action_fn.args, include_attributes=False)
    oracle_signature = ast.dump(oracle_fn.args, include_attributes=False)
    action_body = ast.dump(ast.Module(body=action_fn.body, type_ignores=[]), include_attributes=False)
    oracle_body = ast.dump(ast.Module(body=oracle_fn.body, type_ignores=[]), include_attributes=False)
    if action_signature != oracle_signature or action_body != oracle_body:
        raise ValueError("dense action is not AST-identical to frozen oracle")
    forbidden_tokens = ("expm_multiply", "allclose", "rtol", "atol", "ulp_allowance")
    if any(token in action_text.lower() for token in forbidden_tokens):
        raise ValueError("forbidden rescue or sparse action")
    forbidden_imports = {"numpy", "scipy", "torch", "jax", "tensorflow"}
    if imported_roots(action_tree) & forbidden_imports:
        raise ValueError("numerical import in source-only action")
    module_calls = [
        node for node in action_tree.body
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
    ]
    if module_calls:
        raise ValueError("module-level execution")
    return {
        "status": "PASS_STATIC_ACTION_BOUNDARY_HOLD",
        "boundary_coordinates": 68105,
        "action_ast_identical": True,
        "numerical_calls": 0,
    }
