"""Run bounded assertion edits against pinned repository function subsets.

The reviewed catalog owns executable subjects and output controls. Model text
can only add assertions to a test template. This checks function contracts,
not a complete repository build or an authenticated external user task.
"""

import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from . import data

TEMPLATE = "def test_contract():\n    pass\n"
ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "qualification/cell-experiments-v2-20261116/task-fixtures"
CATALOG_PINS = {
    "open": "d57dc0c7cc8e3b54aabbc473b5e9ced596d48afa556a182e9e18b1eb085e5040",
    "confirmation": "0a24e531367fbca187c4750cf7068f37e1e0228c96e4a6a2b282dd9c3ab57bcb",
    "diagnostic": "edb783a8be7c484f2c96fe19edba8aeca67d9be98d4aa91df7f9450d72b80d88",
}
_CATALOG = {}
_CONFIRMATION = None


def load_catalog(name="open"):
    """Load an exact reviewed catalog; confirmation needs an explicit B binding."""
    if name == "confirmation" and _CONFIRMATION is None:
        raise ValueError("confirmation catalog requires a frozen selection receipt")
    filename = {
        "open": "catalog.json",
        "confirmation": "catalog-C.sealed.json",
        "diagnostic": "catalog-diagnostic-20261118.json",
    }[name]
    raw = (FIXTURES / filename).read_bytes()
    if hashlib.sha256(raw).hexdigest() != CATALOG_PINS.get(name):
        raise ValueError("reviewed fixture catalog changed")
    value = json.loads(raw)
    for fixture in value["fixtures"]:
        path = FIXTURES / "sources" / fixture["source"]["archive_name"]
        original = path.read_bytes()
        source = fixture["source"]
        blob = hashlib.sha1(
            b"blob " + str(len(original)).encode() + b"\0" + original
        ).hexdigest()
        if (
            hashlib.sha256(original).hexdigest() != source["sha256"]
            or blob != source["git_blob"]
        ):
            raise ValueError("repository original differs from pinned bytes")
        tree = ast.parse(original)
        lines = original.decode().splitlines(keepends=True)
        parts = [
            "".join(
                lines[
                    min([node.lineno, *[d.lineno for d in node.decorator_list]])
                    - 1 : node.end_lineno
                ]
            ).rstrip("\n")
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.ClassDef))
            and node.name in fixture["nodes"]
        ]
        extracted = "\n\n".join(parts) + "\n"
        if extracted != fixture["subject_source"]:
            raise ValueError("reviewed subject differs from original AST range")
        _CATALOG[fixture["fixture_id"]] = fixture
    return value


def unlock_confirmation(selection_path, expected_sha256):
    """Bind a retained B selection before exposing C; not independent custody."""
    global _CONFIRMATION
    raw = Path(selection_path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("selection receipt changed")
    value = json.loads(raw)
    if not isinstance(value, dict) or not value:
        raise ValueError("nonempty frozen selection receipt required")
    _CONFIRMATION = {"sha256": expected_sha256, "opened_at_ns": time.time_ns()}
    load_catalog("confirmation")
    return copy.deepcopy(_CONFIRMATION)


def _literal(node):
    value = ast.literal_eval(node)
    raw = data.canonical(value)
    if len(raw) > 4096:
        raise ValueError("assertion literal exceeds bound")

    def check(item, depth=0):
        if depth > 8:
            raise ValueError("assertion literal nesting exceeds bound")
        if type(item) in (int, float) and abs(item) > 1_000_000:
            raise ValueError("assertion numeric literal exceeds bound")
        if isinstance(item, (list, tuple, dict)):
            if len(item) > 64:
                raise ValueError("assertion collection exceeds bound")
            for child in item.values() if isinstance(item, dict) else item:
                check(child, depth + 1)

    check(value)
    return value


def checked_test(answer):
    """Accept only bounded literal calls and assertions; never imports or effects."""
    patch = data._parse(answer)
    if not isinstance(patch, dict) or set(patch) != {"edits"}:
        raise ValueError("expected edits object")
    edits = patch["edits"]
    if not isinstance(edits, list) or len(edits) != 1:
        raise ValueError("one test-file edit required")
    edit = edits[0]
    if (
        not isinstance(edit, dict)
        or set(edit) != {"path", "old", "new"}
        or edit["path"] != "test_contract.py"
        or edit["old"] != "    pass"
        or not isinstance(edit["new"], str)
        or len(edit["new"].encode()) > 8192
    ):
        raise ValueError("invalid bounded test edit")
    source = TEMPLATE.replace(edit["old"], edit["new"], 1)
    tree = ast.parse(source)
    if len(list(ast.walk(tree))) > 256 or len(tree.body) != 1:
        raise ValueError("test AST exceeds bound")
    function = tree.body[0]
    if (
        not isinstance(function, ast.FunctionDef)
        or function.name != "test_contract"
        or function.decorator_list
        or function.returns
        or function.type_comment
        or function.args.args
        or function.args.kwonlyargs
        or function.args.posonlyargs
        or function.args.vararg
        or function.args.kwarg
        or not 1 <= len(function.body) <= 12
        or not all(
            isinstance(node, ast.Assert) and node.msg is None for node in function.body
        )
    ):
        raise ValueError("test must contain only one to twelve assertions")
    calls = 0

    def expression(node):
        nonlocal calls
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id != "subject":
                raise ValueError("only reviewed subject calls are allowed")
            if node.keywords or not 1 <= len(node.args) <= 3:
                raise ValueError("literal positional subject arguments required")
            for arg in node.args:
                _literal(arg)
            calls += 1
        elif isinstance(node, ast.Subscript):
            expression(node.value)
            _literal(node.slice)
        elif isinstance(node, ast.Compare):
            if not all(
                isinstance(
                    op,
                    (
                        ast.Eq,
                        ast.NotEq,
                        ast.Lt,
                        ast.LtE,
                        ast.Gt,
                        ast.GtE,
                        ast.Is,
                        ast.IsNot,
                    ),
                )
                for op in node.ops
            ):
                raise ValueError("unsupported assertion comparison")
            expression(node.left)
            for right in node.comparators:
                expression(right)
        elif isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            for child in node.values:
                expression(child)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            expression(node.operand)
        else:
            _literal(node)

    for assertion in function.body:
        expression(assertion.test)
    if not 1 <= calls <= 24:
        raise ValueError("tests must call the actual subject")
    return source, len(function.body), calls


def _subject(fixture):
    import math
    import re
    from dataclasses import dataclass
    import numpy as np

    namespace = dict(
        np=np,
        math=math,
        re=re,
        json=json,
        Path=Path,
        dataclass=dataclass,
        CellError=ValueError,
        ReplayImportError=ValueError,
    )
    namespace.update(fixture.get("globals", {}))
    namespace["_require"] = lambda condition, message: (
        None if condition else (_ for _ in ()).throw(ValueError(message))
    )
    namespace["read_bounded"] = lambda value, limit: value.encode("utf-8")
    exec(
        compile(fixture["subject_source"], "<pinned repository subset>", "exec"),
        namespace,
    )
    entry = fixture["entry"]
    name = fixture["function"]
    function = namespace[name]
    if entry == "mse":

        def objective(prediction, target):
            p, y = np.asarray(prediction), np.asarray(target)
            loss, gradient = function("mse", y.shape[1], "contract").loss_and_gradient(
                p, y
            )
            return {"loss": loss, "gradient": gradient.tolist()}

        return objective
    if entry == "numpy_metric":
        return lambda prediction, target: function(
            np.asarray(prediction), np.asarray(target)
        )
    if entry == "hex":
        return lambda value: function(value).hex()
    if entry == "strict_int":
        return lambda value, minimum: function(value, "contract", minimum)
    if entry == "path_string":
        return lambda value: function(Path(value))
    return function


def _mutate(value, control, arguments):
    result = copy.deepcopy(value)
    if "when_first_arg" in control and arguments[0] != control["when_first_arg"]:
        return result
    kind = control["kind"]
    if kind == "constant":
        return control["value"]
    if kind == "suffix":
        return result + control["value"]
    if kind == "toggle":
        return not result
    if kind == "drop":
        result.pop(control["key"], None)
        return result
    target = result
    for key in control["path"][:-1]:
        target = target[key]
    target[control["path"][-1]] += control["value"]
    return result


def _worker(request):
    fixture, source = request["fixture"], request["source"]
    subject = _subject(fixture)
    results = []
    for control in [None, *fixture["controls"]]:
        actual_calls = []

        def observed(*args):
            result = subject(*args)
            output = result if control is None else _mutate(result, control, args)
            actual_calls.append({"arguments": args, "output": output})
            return output

        namespace = {"__builtins__": {}, "subject": observed}
        try:
            exec(compile(source, "test_contract.py", "exec"), namespace)
            namespace["test_contract"]()
            passed, error = True, None
        except Exception as failure:
            passed, error = False, type(failure).__name__
        results.append(
            {
                "control": "original" if control is None else control["id"],
                "passed": passed,
                "error": error,
                "calls": actual_calls,
            }
        )
    return {
        "observations": results,
        "original_passed": results[0]["passed"],
        "controls_rejected": sum(not r["passed"] for r in results[1:]),
        "control_count": len(results) - 1,
    }


def verify_patch(parameters, answer):
    """Apply actual test bytes in a new directory, execute, and inspect outcomes."""
    if not _CATALOG:
        load_catalog()
    if set(parameters) != {"fixture_id", "fixture_sha256"}:
        raise ValueError("fixture binding required")
    fixture = _CATALOG.get(parameters["fixture_id"])
    if fixture is None or data.digest(fixture) != parameters["fixture_sha256"]:
        raise ValueError("fixture missing, sealed, or changed")
    started = time.perf_counter_ns()
    try:
        source, assertions, calls = checked_test(answer)
    except (ValueError, TypeError, SyntaxError, KeyError) as error:
        return {
            "success": False,
            "reason": "invalid_test_patch",
            "feedback": str(error),
            "executed": False,
            "controls_rejected": 0,
        }
    with tempfile.TemporaryDirectory(prefix="hepta-repo-test-") as directory:
        test = Path(directory) / "test_contract.py"
        test.write_text(source, encoding="utf-8")
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(ROOT / "scripts"),
            "OPENBLAS_NUM_THREADS": "1",
            "OMP_NUM_THREADS": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        command = [sys.executable, "-m", "cell_experiments.repo_execution", "--worker"]
        try:
            run = subprocess.run(
                command,
                input=data.canonical({"fixture": fixture, "source": source}),
                cwd=directory,
                env=env,
                capture_output=True,
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "reason": "test_timeout",
                "executed": True,
                "controls_rejected": 0,
                "wall_ns": time.perf_counter_ns() - started,
            }
        raw = run.stdout
        try:
            result = (
                data._parse(raw) if run.returncode == 0 and len(raw) <= 65536 else None
            )
        except (ValueError, TypeError):
            result = None
        success = bool(
            result
            and result["original_passed"]
            and result["controls_rejected"] == result["control_count"] > 0
        )
        return {
            "success": success,
            "reason": "business_tests_passed" if success else "business_tests_failed",
            "executed": True,
            "exit_code": run.returncode,
            "assertions": assertions,
            "planned_subject_calls_per_arm": calls,
            "test_sha256": hashlib.sha256(test.read_bytes()).hexdigest(),
            "fixture_sha256": data.digest(fixture),
            "stdout_sha256": hashlib.sha256(raw).hexdigest(),
            "stderr": run.stderr[:4096].decode("utf-8", errors="replace"),
            "wall_ns": time.perf_counter_ns() - started,
            "result": result,
            "controls_rejected": 0 if result is None else result["controls_rejected"],
            "full_repository_integration": False,
            "independent_user_evidence": False,
        }


data.register_verifier("repo_patch", "1", verify_patch)


if __name__ == "__main__":
    if sys.argv[1:] != ["--worker"]:
        raise SystemExit("explicit worker mode required")
    request = data._parse(sys.stdin.buffer.read(262145))
    print(json.dumps(_worker(request), sort_keys=True, allow_nan=False))
