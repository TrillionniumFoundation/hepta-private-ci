#!/usr/bin/env python3
"""Integrate the failure-site v2 projection reconciler into r7."""
from __future__ import annotations

import ast
import re
from pathlib import Path

FINALIZER = Path("scripts/hepta-global-finalizer-r7.py")
WORKFLOW = Path(".github/workflows/hepta-global-finalizer-r7.yml")
HELPER = "hepta-final-projection-repair-v2.py"

FUNCTION = r'''def finalize_generated_state() -> dict[str, Any]:
    """Reconcile generated projections and bind native blobs before staging."""

    repair_script = Path(__file__).with_name(
        "hepta-final-projection-repair-v2.py"
    )
    if not repair_script.is_file():
        raise RuntimeError(
            f"final projection repair artifact is missing: {repair_script}"
        )
    repair_result = run(("python3", str(repair_script)), timeout=1800)
    if not repair_result.passed:
        raise RuntimeError(
            "final projection repair failed:\n"
            + "\n".join(repair_result.output.splitlines()[-160:])
        )

    receipt_path = (
        ROOT
        / "qualification/global-gap-closure-final-r7/FINAL_PROJECTION_REPAIR.json"
    )
    if not receipt_path.is_file():
        raise RuntimeError("final projection repair did not emit its receipt")
    receipt = read_json(receipt_path)
    if receipt.get("passed") is not True:
        raise RuntimeError(
            "final projection repair receipt is not passing: "
            + json.dumps(receipt, sort_keys=True)
        )

    native = repair_native_bindings()
    if not native.get("valid"):
        raise RuntimeError(
            "post-repair native binding projection is invalid: "
            + json.dumps(native, sort_keys=True)
        )

    commands = (
        ("python3", "scripts/hepta-readiness.py", "verify"),
        ("python3", "scripts/hepta-technical-closure.py", "verify"),
        (
            "python3",
            "qualification/module-execution-dossiers/implementation_contracts.py",
            "verify-repository",
        ),
    )
    verifier_receipts: list[dict[str, Any]] = []
    for command in commands:
        verification = run(command, timeout=1800)
        verifier_receipts.append(verification.receipt())
        if not verification.passed:
            raise RuntimeError(
                "post-repair verifier failed: "
                + " ".join(command)
                + "\n"
                + "\n".join(verification.output.splitlines()[-160:])
            )

    repair_sha256 = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    summary = {
        "executor": repair_script.name,
        "executorBlob": git_text(
            "hash-object", "--", repair_script.as_posix()
        ),
        "repairReceiptPath": receipt_path.relative_to(ROOT).as_posix(),
        "repairReceiptSha256": repair_sha256,
        "nativeBindings": native,
        "verifiers": verifier_receipts,
    }
    prepare_path = (
        ROOT / "qualification/global-gap-closure-final-r7/PREPARE.json"
    )
    if prepare_path.is_file():
        prepare_receipt = read_json(prepare_path)
        prepare_receipt["finalGeneratedState"] = summary
        write_json(prepare_path, prepare_receipt)
    return summary
'''


def call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def contains_git(statement: ast.AST, command: str) -> bool:
    for node in ast.walk(statement):
        if not isinstance(node, ast.Call) or call_name(node) != "git" or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and first.value == command:
            return True
    return False


def contains_fixed_point_call(statement: ast.AST) -> bool:
    return any(
        isinstance(node, ast.Call)
        and call_name(node)
        in {
            "finalize_generated_state",
            "repair_final_projection_fixed_point",
        }
        for node in ast.walk(statement)
    )


def remove_line_ranges(text: str, ranges: list[tuple[int, int]]) -> str:
    lines = text.splitlines(keepends=True)
    for start, end in sorted(ranges, reverse=True):
        del lines[start - 1 : end]
    return "".join(lines)


def patch_finalizer() -> None:
    text = FINALIZER.read_text(encoding="utf-8")
    if "import hashlib\n" not in text:
        anchors = ("import ast\n", "import argparse\n")
        for anchor in anchors:
            if text.count(anchor) == 1:
                text = text.replace(anchor, anchor + "import hashlib\n", 1)
                break
        else:
            raise SystemExit("r24 could not place hashlib import")

    pattern = re.compile(
        r"def finalize_generated_state\(\) -> dict\[str, Any\]:\n"
        r".*?\n(?=def command_receipts_pass\()",
        re.DOTALL,
    )
    if pattern.search(text):
        text = pattern.sub(FUNCTION + "\n\n", text, count=1)
    elif "def finalize_generated_state()" not in text:
        marker = "def command_receipts_pass("
        if text.count(marker) != 1:
            raise SystemExit("r24 helper insertion point drifted")
        text = text.replace(marker, FUNCTION + "\n\n" + marker, 1)

    # Remove stale receipt references that could evaluate before the final call.
    text = re.sub(
        r'^\s*"(?:finalGeneratedState|finalProjectionFixedPoint)"\s*:\s*'
        r'(?:final_generated_state|final_projection_fixed_point),\s*\n',
        "",
        text,
        flags=re.MULTILINE,
    )

    tree = ast.parse(text, filename=FINALIZER.as_posix())
    prepare = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "prepare"
        ),
        None,
    )
    if prepare is None:
        raise SystemExit("r24 prepare() not found")

    stale_ranges = [
        (statement.lineno, statement.end_lineno or statement.lineno)
        for statement in prepare.body
        if contains_fixed_point_call(statement)
    ]
    if stale_ranges:
        text = remove_line_ranges(text, stale_ranges)
        tree = ast.parse(text, filename=FINALIZER.as_posix())
        prepare = next(
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "prepare"
        )

    commit_statement = next(
        (statement for statement in prepare.body if contains_git(statement, "commit")),
        None,
    )
    if commit_statement is None:
        raise SystemExit("r24 prepare commit statement not found")
    add_statements = [
        statement
        for statement in prepare.body
        if statement.lineno < commit_statement.lineno and contains_git(statement, "add")
    ]
    if not add_statements:
        raise SystemExit("r24 final staging statement not found")
    insertion = add_statements[-1]
    lines = text.splitlines(keepends=True)
    index = insertion.lineno - 1
    indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
    lines.insert(index, indent + "finalize_generated_state()\n")
    text = "".join(lines)

    tree = ast.parse(text, filename=FINALIZER.as_posix())
    prepare = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "prepare"
    )
    fixed_calls = [
        node
        for node in ast.walk(prepare)
        if isinstance(node, ast.Call) and call_name(node) == "finalize_generated_state"
    ]
    if len(fixed_calls) != 1:
        raise SystemExit(
            f"r24 expected one final generated-state call, observed {len(fixed_calls)}"
        )
    fixed_line = fixed_calls[0].lineno
    final_add_line = max(
        statement.lineno
        for statement in prepare.body
        if contains_git(statement, "add")
    )
    final_commit_line = min(
        statement.lineno
        for statement in prepare.body
        if contains_git(statement, "commit")
    )
    if not fixed_line < final_add_line < final_commit_line:
        raise SystemExit(
            "r24 final generated-state call is not immediately before final staging"
        )

    required = (
        "def finalize_generated_state()",
        '"hepta-final-projection-repair-v2.py"',
        "finalize_generated_state()",
        'prepare_receipt["finalGeneratedState"] = summary',
        'receipt.get("passed") is not True',
        "repairReceiptSha256",
    )
    for phrase in required:
        if phrase not in text:
            raise SystemExit(f"r24 finalizer missing {phrase!r}")
    FINALIZER.write_text(text, encoding="utf-8")


def patch_workflow() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    text = text.replace(
        "scripts/hepta-final-projection-repair.py",
        "scripts/hepta-final-projection-repair-v2.py",
    )
    text = text.replace(
        "hepta-final-projection-repair.py",
        "hepta-final-projection-repair-v2.py",
    )
    if "      - scripts/hepta-final-projection-repair-v2.py\n" not in text:
        path_marker = "      - scripts/hepta-global-finalizer-r7.py\n"
        if text.count(path_marker) != 1:
            raise SystemExit("r24 workflow path trigger insertion point drifted")
        text = text.replace(
            path_marker,
            path_marker + "      - scripts/hepta-final-projection-repair-v2.py\n",
            1,
        )
    copy_marker = (
        '          cp scripts/hepta-global-finalizer-r7.py \\\n'
        '            "${RUNNER_TEMP}/hepta-r7-executor/'
        'hepta-global-finalizer-r7.py"\n'
    )
    copy_block = (
        copy_marker
        + '          cp scripts/hepta-final-projection-repair-v2.py \\\n'
        + '            "${RUNNER_TEMP}/hepta-r7-executor/'
        + 'hepta-final-projection-repair-v2.py"\n'
        + '          python3 -m py_compile \\\n'
        + '            "${RUNNER_TEMP}/hepta-r7-executor/'
        + 'hepta-final-projection-repair-v2.py"\n'
    )
    if (
        '${RUNNER_TEMP}/hepta-r7-executor/hepta-final-projection-repair-v2.py'
        not in text
    ):
        if text.count(copy_marker) != 1:
            raise SystemExit("r24 workflow executor copy insertion point drifted")
        text = text.replace(copy_marker, copy_block, 1)
    text = text.replace("cancel-in-progress: false", "cancel-in-progress: true")
    if "cancel-in-progress: true" not in text:
        raise SystemExit("r24 workflow concurrency is not superseding stale runs")
    if text.count("hepta-final-projection-repair-v2.py") < 3:
        raise SystemExit("r24 workflow did not bind v2 helper in trigger and artifact")
    WORKFLOW.write_text(text, encoding="utf-8")


def main() -> int:
    patch_finalizer()
    patch_workflow()
    ast.parse(FINALIZER.read_text(encoding="utf-8"), filename=FINALIZER.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
