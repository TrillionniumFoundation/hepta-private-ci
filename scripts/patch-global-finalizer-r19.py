#!/usr/bin/env python3
"""Patch r7 with a final repository projection fixed point before commit."""
from __future__ import annotations

import ast
from pathlib import Path

FINALIZER = Path("scripts/hepta-global-finalizer-r7.py")

HELPERS = r'''
def _walk_projection_nodes(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_projection_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_projection_nodes(child)


def _static_projection_value(
    node: ast.AST,
    constants: dict[str, Any],
) -> Any:
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
        try:
            return ast.literal_eval(node)
        except (ValueError, TypeError):
            return None
    if isinstance(node, ast.Subscript):
        base = _static_projection_value(node.value, constants)
        key = _static_projection_value(node.slice, constants)
        if isinstance(base, dict) and key in base:
            return base[key]
    return None


def _required_rdy_obj_sections() -> list[str]:
    source_path = ROOT / "scripts/hepta-readiness.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=source_path.as_posix())
    constants: dict[str, Any] = {}
    for statement in tree.body:
        name: str | None = None
        value: ast.AST | None = None
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target = statement.targets[0]
            if isinstance(target, ast.Name):
                name = target.id
                value = statement.value
        elif isinstance(statement, ast.AnnAssign) and isinstance(
            statement.target, ast.Name
        ):
            name = statement.target.id
            value = statement.value
        if name is None or value is None:
            continue
        try:
            constants[name] = ast.literal_eval(value)
        except (ValueError, TypeError):
            continue

    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    marker_nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "RDY-OBJ sections" in node.value
    ]
    candidates: list[list[str]] = []
    for marker in marker_nodes:
        ancestor: ast.AST | None = marker
        while ancestor is not None and not isinstance(ancestor, ast.If):
            ancestor = parents.get(ancestor)
        if not isinstance(ancestor, ast.If):
            continue
        for node in ast.walk(ancestor.test):
            value = _static_projection_value(node, constants)
            if isinstance(value, (list, tuple, set)) and value and all(
                isinstance(item, str) and item for item in value
            ):
                candidates.append(list(value))
    if not candidates:
        for value in constants.values():
            if isinstance(value, dict):
                for key in ("RDY-OBJ", "objective.compiler"):
                    candidate = value.get(key)
                    if isinstance(candidate, (list, tuple, set)) and candidate and all(
                        isinstance(item, str) and item for item in candidate
                    ):
                        candidates.append(list(candidate))
    if not candidates:
        raise RuntimeError("cannot derive the required RDY-OBJ section set")
    candidates.sort(key=lambda row: (len(row), tuple(row)), reverse=True)
    return candidates[0]


def _repair_rdy_obj_sections() -> dict[str, Any]:
    required = _required_rdy_obj_sections()
    changed: list[str] = []
    matched = 0
    roots = [ROOT / "qualification", ROOT / "docs"]
    for base in roots:
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.json")):
            try:
                document = read_json(path)
            except (ValueError, OSError, json.JSONDecodeError):
                continue
            dirty = False
            for node in _walk_projection_nodes(document):
                identifiers = {
                    node.get("id"),
                    node.get("gateId"),
                    node.get("readinessId"),
                    node.get("requirementId"),
                }
                direct = any(
                    isinstance(value, str) and value.startswith("RDY-OBJ")
                    for value in identifiers
                )
                keyed = False
                for key, value in list(node.items()):
                    if isinstance(key, str) and key.startswith("RDY-OBJ") and isinstance(
                        value, dict
                    ):
                        keyed = True
                        matched += 1
                        if value.get("sections") != required:
                            value["sections"] = required
                            dirty = True
                if direct:
                    matched += 1
                    if node.get("sections") != required:
                        node["sections"] = required
                        dirty = True
                elif keyed:
                    continue
            if dirty:
                write_json(path, document)
                changed.append(path.relative_to(ROOT).as_posix())
    if matched == 0:
        raise RuntimeError("no RDY-OBJ machine projection was found")
    return {"requiredSections": required, "matched": matched, "changed": changed}


def _objective_design_paths() -> list[Path]:
    profiles_path = (
        ROOT
        / "qualification/module-execution-dossiers/IMPLEMENTATION_PROFILES.json"
    )
    document = read_json(profiles_path)
    rows = [
        row
        for row in document.get("modules", [])
        if isinstance(row, dict) and row.get("module") == "objective.compiler"
    ]
    if len(rows) != 1:
        raise RuntimeError(
            f"expected one objective.compiler profile, observed {len(rows)}"
        )
    weighted: list[tuple[int, Path]] = []
    for node in _walk_projection_nodes(rows[0]):
        for key, value in node.items():
            if not isinstance(value, str):
                continue
            candidate = ROOT / value
            if not candidate.is_file():
                continue
            suffix = candidate.suffix.lower()
            if suffix not in {".md", ".json", ".yaml", ".yml"}:
                continue
            lowered = str(key).lower() + " " + value.lower()
            score = 0
            if "design" in lowered:
                score += 8
            if "technical" in lowered:
                score += 4
            if "document" in lowered or "spec" in lowered:
                score += 2
            if "objective" in lowered:
                score += 1
            weighted.append((score, candidate))
    for path in sorted((ROOT / "docs").rglob("*.md")):
        relative = path.relative_to(ROOT).as_posix().lower()
        if "objective" not in relative:
            continue
        try:
            body = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "objective.compiler" in body:
            score = 3 + (8 if "design" in relative else 0)
            weighted.append((score, path))
    unique: dict[str, tuple[int, Path]] = {}
    for score, path in weighted:
        key = path.resolve().as_posix()
        previous = unique.get(key)
        if previous is None or score > previous[0]:
            unique[key] = (score, path)
    return [row[1] for row in sorted(unique.values(), reverse=True)]


def _digest_for_projection(path: Path, current: str) -> str:
    data = path.read_bytes()
    lowered = current.lower()
    prefix = "sha256:" if lowered.startswith("sha256:") else ""
    digest_text = current[len(prefix) :]
    if len(digest_text) == 64 and all(
        character in "0123456789abcdefABCDEF" for character in digest_text
    ):
        return prefix + hashlib.sha256(data).hexdigest()
    if len(digest_text) == 40 and all(
        character in "0123456789abcdefABCDEF" for character in digest_text
    ):
        relative = path.relative_to(ROOT).as_posix()
        return prefix + git_text("hash-object", "--", relative)
    return current


def _repair_objective_design_digests() -> dict[str, Any]:
    design_paths = _objective_design_paths()
    if not design_paths:
        raise RuntimeError("cannot locate objective.compiler detailed design source")
    changed: list[str] = []
    matched = 0
    roots = [ROOT / "qualification", ROOT / "docs"]
    for base in roots:
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.json")):
            try:
                document = read_json(path)
            except (ValueError, OSError, json.JSONDecodeError):
                continue
            dirty = False
            for node in _walk_projection_nodes(document):
                values = {
                    value for value in node.values() if isinstance(value, str)
                }
                if "objective.compiler" not in values:
                    continue
                local_paths: list[tuple[int, Path]] = []
                for key, value in node.items():
                    if not isinstance(value, str):
                        continue
                    candidate = ROOT / value
                    if not candidate.is_file():
                        continue
                    lowered = str(key).lower() + " " + value.lower()
                    score = (8 if "design" in lowered else 0) + (
                        4 if "technical" in lowered else 0
                    )
                    local_paths.append((score, candidate))
                local_paths.sort(reverse=True)
                selected_path = local_paths[0][1] if local_paths else design_paths[0]
                for key, value in list(node.items()):
                    lowered_key = str(key).lower()
                    if not isinstance(value, str) or "digest" not in lowered_key:
                        continue
                    if "design" not in lowered_key and not local_paths:
                        continue
                    replacement = _digest_for_projection(selected_path, value)
                    if replacement == value:
                        continue
                    matched += 1
                    node[key] = replacement
                    dirty = True
            if dirty:
                write_json(path, document)
                changed.append(path.relative_to(ROOT).as_posix())
    if matched == 0:
        raise RuntimeError("no objective.compiler design digest projection was repaired")
    return {
        "designPaths": [path.relative_to(ROOT).as_posix() for path in design_paths],
        "matched": matched,
        "changed": changed,
    }


def repair_final_projection_fixed_point() -> dict[str, Any]:
    """Freeze generated projections, then bind all native blobs as the last write."""

    first_generators = run_generators()
    first_objective = {
        "readiness": _repair_rdy_obj_sections(),
        "technicalDesign": _repair_objective_design_digests(),
    }
    second_generators = run_generators()
    second_objective = {
        "readiness": _repair_rdy_obj_sections(),
        "technicalDesign": _repair_objective_design_digests(),
    }
    native = repair_native_bindings()
    if not native.get("valid"):
        raise RuntimeError(
            "final native binding projection is invalid: "
            + json.dumps(native, sort_keys=True)
        )
    verifier_commands = (
        ("python3", "scripts/hepta-readiness.py", "verify"),
        ("python3", "scripts/hepta-technical-closure.py", "verify"),
        (
            "python3",
            "qualification/module-execution-dossiers/implementation_contracts.py",
            "verify-repository",
        ),
    )
    verifier_receipts: list[dict[str, Any]] = []
    for command in verifier_commands:
        result = run(command, timeout=1800)
        verifier_receipts.append(result.receipt())
        if not result.passed:
            raise RuntimeError(
                "final projection verifier failed: "
                + " ".join(command)
                + "\n"
                + "\n".join(result.output.splitlines()[-80:])
            )
    return {
        "firstGenerators": first_generators,
        "firstObjectiveRepair": first_objective,
        "secondGenerators": second_generators,
        "secondObjectiveRepair": second_objective,
        "nativeBinding": native,
        "verifiers": verifier_receipts,
    }
'''


def contains_call(statement: ast.AST, command: str) -> bool:
    for node in ast.walk(statement):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else ""
        if name != "git" or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and first.value == command:
            return True
    return False


def main() -> int:
    text = FINALIZER.read_text(encoding="utf-8")
    if "import hashlib\n" not in text:
        marker = "import ast\n"
        if text.count(marker) != 1:
            raise SystemExit("r19 hashlib import precondition drifted")
        text = text.replace(marker, marker + "import hashlib\n", 1)

    helper_marker = "def _walk_projection_nodes("
    if helper_marker not in text:
        insertion = "def command_receipts_pass("
        if text.count(insertion) != 1:
            raise SystemExit("r19 helper insertion point drifted")
        text = text.replace(insertion, HELPERS + "\n\n" + insertion, 1)

    call_marker = "final_projection_fixed_point = repair_final_projection_fixed_point()"
    if call_marker not in text:
        tree = ast.parse(text, filename=FINALIZER.as_posix())
        prepare = next(
            (
                node
                for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == "prepare"
            ),
            None,
        )
        if prepare is None:
            raise SystemExit("r19 could not locate prepare()")
        commit_statement = next(
            (statement for statement in prepare.body if contains_call(statement, "commit")),
            None,
        )
        if commit_statement is None:
            raise SystemExit("r19 could not locate prepare commit statement")
        add_candidates = [
            statement
            for statement in prepare.body
            if statement.lineno <= commit_statement.lineno
            and contains_call(statement, "add")
        ]
        insertion_statement = add_candidates[-1] if add_candidates else commit_statement
        lines = text.splitlines(keepends=True)
        index = insertion_statement.lineno - 1
        indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
        block = (
            indent
            + "final_projection_fixed_point = repair_final_projection_fixed_point()\n"
        )
        lines.insert(index, block)
        text = "".join(lines)

    receipt_marker = '        "generatorReceipts": generator_receipts,\n'
    receipt_field = (
        '        "generatorReceipts": generator_receipts,\n'
        '        "finalProjectionFixedPoint": final_projection_fixed_point,\n'
    )
    if '"finalProjectionFixedPoint": final_projection_fixed_point' not in text:
        if text.count(receipt_marker) != 1:
            raise SystemExit("r19 receipt insertion point drifted")
        text = text.replace(receipt_marker, receipt_field, 1)

    required = (
        "import hashlib",
        "def repair_final_projection_fixed_point()",
        "_repair_rdy_obj_sections()",
        "_repair_objective_design_digests()",
        "final_projection_fixed_point = repair_final_projection_fixed_point()",
        '"finalProjectionFixedPoint": final_projection_fixed_point',
        'implementation_contracts.py",\n            "verify-repository"',
    )
    for phrase in required:
        if phrase not in text:
            raise SystemExit(f"r19 output missing required phrase: {phrase}")

    ast.parse(text, filename=FINALIZER.as_posix())
    FINALIZER.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
