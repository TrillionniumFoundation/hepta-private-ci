"""Freeze supplied-change views and real comparator commands before observations."""

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

from operational_cohort_plan import canonical, digest


def git(store, *args, missing=False):
    result = subprocess.run(["git", "--git-dir=" + str(store), *args], capture_output=True, timeout=30)
    if result.returncode and not missing:
        raise ValueError(result.stderr.decode(errors="replace"))
    return None if result.returncode else result.stdout


def test_path(path):
    parts = Path(path).parts
    return any(p in ("test", "tests") for p in parts) or Path(path).name.startswith("test_")


def all_files(store, revision):
    return git(store, "ls-tree", "-r", "--name-only", revision).decode().splitlines()


def selector_location(selector, runner, files):
    if runner == "pytest":
        parts = selector.split("::")
        if parts[0] not in files:
            raise ValueError("test file absent at pinned source")
        return parts[0], parts[1:]
    parts = selector.split(".")
    for index in range(len(parts), 0, -1):
        for suffix in (".py", "/__init__.py"):
            path = "/".join(parts[:index]) + suffix
            if path in files:
                return path, parts[index:]
    raise ValueError("test selector cannot be bound to a pinned Python file")


def test_nodes(tree, path, runner):
    found = []
    def visit(body, parents):
        for node in body:
            if isinstance(node, ast.ClassDef):
                visit(node.body, parents + [node.name])
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                names = parents + [node.name]
                found.append(path + "::" + "::".join(names) if runner == "pytest" else path[:-3].replace("/", ".") + "." + ".".join(names))
    visit(tree.body, [])
    return sorted(set(found))


def source_span(lines, node):
    start = min([node.lineno] + [n.lineno for n in getattr(node, "decorator_list", [])]) - 1
    return "".join(lines[start:node.end_lineno])


def test_view(raw, names, path, files, read_file):
    text = raw.decode("utf-8-sig")
    lines, tree = text.splitlines(keepends=True), ast.parse(text)
    body, parent, node = tree.body, None, None
    selected = []
    for name in names:
        matches = [n for n in body if getattr(n, "name", None) == name]
        if not matches:
            raise ValueError("selector body is inherited/dynamic or absent")
        parent, node = node, matches[0]
        body = getattr(node, "body", [])
    if names:
        selected.append(node)
        if isinstance(parent, ast.ClassDef):
            selected.extend(n for n in parent.body if getattr(n, "name", None) in ("setUp", "tearDown", "setup_method", "teardown_method"))
    else:
        selected.extend(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
    symbols = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols[node.name] = node
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            for target in getattr(node, "targets", [getattr(node, "target", None)]):
                if isinstance(target, ast.Name):
                    symbols[target.id] = node
    if isinstance(parent, ast.ClassDef):
        symbols.update({n.name: n for n in parent.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))})
    selected.extend(n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom)))
    for _ in range(6):
        wanted = {n.id for s in selected for n in ast.walk(s) if isinstance(n, ast.Name)}
        wanted |= {n.attr for s in selected for n in ast.walk(s) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "self"}
        additions = [symbols[name] for name in wanted if name in symbols and symbols[name] not in selected]
        if not additions:
            break
        selected.extend(additions)
    selected = sorted(set(selected), key=lambda n: n.lineno)
    fixtures = set()
    for root in selected:
        for node in ast.walk(root):
            if not isinstance(node, ast.Call) or not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
                continue
            function = getattr(node.func, "id", getattr(node.func, "attr", ""))
            if function not in ("read_data", "open", "Path", "load_fixture", "get_testdata"):
                continue
            literal = node.args[0].value
            if len(literal) > 200 or "\n" in literal:
                continue
            for file in files:
                if test_path(file) and (file.endswith("/" + literal) or (function == "read_data" and Path(file).stem == literal)):
                    fixtures.add(file)
    rendered = "TEST SOURCE " + path + "\n" + "\n".join(source_span(lines, n) for n in selected)
    identities = {path: {"sha256": digest(raw), "bytes": len(raw)}}
    for file in sorted(fixtures):
        data = read_file(file)
        try:
            value = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        rendered += "\nFIXTURE " + file + "\n" + value
        identities[file] = {"sha256": digest(data), "bytes": len(data)}
    return {"text": rendered, "source_files": identities,
            "module_lines": len(lines), "selected_source_lines": sum(n.end_lineno - n.lineno + 1 for n in selected)}


def implementation_views(store, bug):
    before, after = bug["revisions"]["base"], bug["revisions"]["candidate"]
    changed = git(store, "diff", "--name-only", before, after).decode().splitlines()
    production = [p for p in changed if p.endswith(".py") and not test_path(p) and Path(p).name != "setup.py"]
    contexts, source_files, diffs = {"base": [], "candidate": []}, {"base": {}, "candidate": {}}, []
    for path in production:
        patch = git(store, "diff", "--no-ext-diff", "--unified=40", before, after, "--", path).decode()
        diffs.append("\n".join(line for line in patch.splitlines() if not line.startswith("index ")))
        ranges = re.findall(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", patch, re.MULTILINE)
        for role, revision, offset in (("base", before, 0), ("candidate", after, 2)):
            raw = git(store, "show", revision + ":" + path, missing=True) or b""
            lines = raw.decode("utf-8-sig").splitlines(keepends=True)
            included = set()
            for match in ranges:
                start, count = int(match[offset]), int(match[offset + 1] or 1)
                included.update(range(max(0, start - 1), min(len(lines), max(0, start - 1) + count)))
            contexts[role].append("IMPLEMENTATION " + path + "\n" + "".join(lines[i] for i in sorted(included)))
            source_files[role][path] = {"sha256": digest(raw), "bytes": len(raw), "total_lines": len(lines), "included_lines": len(included)}
    return {"production_paths": production, "diff": "\n".join(diffs),
            "contexts": {role: "\n".join(values) for role, values in contexts.items()}, "source_files": source_files}


def prepare_case(store, bug):
    revision = bug["revisions"]["candidate"]
    files = all_files(store, revision)
    read_file = lambda path: git(store, "show", revision + ":" + path)
    case = {"schema": "hepta.operational-prepared-case.v1", "bug": bug,
            "implementation": implementation_views(store, bug), "commands": [], "preparation_errors": []}
    blocked_nodes = {node for cmd in bug["commands"] for node in cmd["nodes"]}
    for number, command in enumerate(bug["commands"]):
        args = shlex.split(command["original"])
        args = args[1:] if args[0] == "pytest" else args[3:]
        record = {"id": "primary-" + str(number), **command, "args": args, "comparators": []}
        try:
            locations = [selector_location(n, command["runner"], files) for n in command["nodes"]]
            views = [test_view(read_file(path), names, path, files, read_file) for path, names in locations]
            record["view"] = {"text": "\n".join(v["text"] for v in views),
                "source_files": {name: item for v in views for name, item in v["source_files"].items()}}
            path, _ = locations[0]
            tree = ast.parse(read_file(path).decode("utf-8-sig"))
            alternatives = [n for n in test_nodes(tree, path, command["runner"]) if n not in blocked_nodes]
            alternatives.sort(key=lambda n: digest((bug["group_id"] + "\n" + n).encode()))
            for selector in alternatives[:3]:
                selected_path, names = selector_location(selector, command["runner"], files)
                record["comparators"].append({"id": "control-" + digest(selector.encode())[:16],
                    "runner": command["runner"], "nodes": [selector], "args": ["-q", selector],
                    "view": test_view(read_file(selected_path), names, selected_path, files, read_file)})
        except (ValueError, SyntaxError, UnicodeDecodeError) as error:
            record["view_error"] = type(error).__name__ + ": " + str(error)
        case["commands"].append(record)
    case["test_tree_roots"] = sorted({"/".join(Path(path).parts[:i + 1]) for path in files
        for i, part in enumerate(Path(path).parts) if part in ("test", "tests")})
    case["declared_test_files"] = bug["test_files"]
    case["fixed_test_paths"] = [p for p in files if test_path(p) or p in bug["test_files"]]
    return case


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--sources", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    raw = Path(args.protocol).read_bytes()
    plan = json.loads(raw)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    records = {}
    for bug in plan["bugs"]:
        case = prepare_case(Path(args.sources) / (bug["project"] + ".git"), bug)
        name = bug["project"] + "-" + str(bug["bug_id"]) + ".json"
        data = canonical(case)
        (output / name).write_bytes(data)
        records[name] = {"sha256": digest(data), "bytes": len(data), "group_id": bug["group_id"]}
    manifest = {"schema": "hepta.operational-prepared-cases.v1", "protocol_sha256": digest(raw),
        "source_code_sha256": digest(Path(__file__).read_bytes()), "cases": records,
        "before_any_upstream_test_execution": True,
        "supplement": "Run the complete fixed test tree and declared test files on both source revisions, avoiding test-fixture confounding. Exact original declared overlay remains recorded per case.",
        "context": "Supplied candidate-change hunks, selected test body, statically referenced local helpers/imports and literal fixtures. This is partial decision context, not a whole-program correctness proof."}
    (output / "manifest.json").write_bytes(canonical(manifest))
    print(json.dumps({"cases": len(records), "manifest_sha256": digest(canonical(manifest)), "bytes": sum(r["bytes"] for r in records.values())}))


if __name__ == "__main__":
    main()
