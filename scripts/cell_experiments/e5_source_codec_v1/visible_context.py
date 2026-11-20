"""Before/task-only context admission with complete source units and fixtures."""

import ast
import re
from pathlib import PurePosixPath

from context_graph import ContextGraph, dotted
from source_actions import bind, canonical
from source_units import sha
from task_fixture_paths import resolve as resolve_task_fixture_paths

BUILTIN_FIXTURES = frozenset(
    {
        "capsys",
        "capsysbinary",
        "capfd",
        "capfdbinary",
        "caplog",
        "monkeypatch",
        "tmp_path",
        "tmp_path_factory",
        "tmpdir",
        "tmpdir_factory",
        "request",
        "record_property",
        "record_testsuite_property",
        "record_xml_attribute",
        "pytestconfig",
        "cache",
        "doctest_namespace",
        "recwarn",
    }
)
SETUP_NAMES = frozenset(
    {
        "setUp",
        "setUpClass",
        "setup_method",
        "setup_class",
        "setup_function",
        "setup_module",
        "tearDown",
        "tearDownClass",
        "teardown_method",
        "teardown_class",
        "teardown_function",
        "teardown_module",
    }
)
FRAME = re.compile(r"([^\s:]+\.(?:py|pyx)):(\d+): in ([^\n]+)")


def functions(graph, unit):
    return [
        n
        for n in graph.nodes[unit["unit_id"]]
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def fixture_info(node):
    declared, autouse = False, False
    for dec in node.decorator_list:
        func = dec.func if isinstance(dec, ast.Call) else dec
        if (dotted(func) or "").split(".")[-1] != "fixture":
            continue
        declared = True
        if isinstance(dec, ast.Call):
            autouse |= any(
                k.arg == "autouse"
                and isinstance(k.value, ast.Constant)
                and k.value.value is True
                for k in dec.keywords
            )
    return declared, autouse


def parameter_names(node):
    result = set()
    for dec in node.decorator_list:
        if not isinstance(dec, ast.Call) or not (dotted(dec.func) or "").endswith(
            ".parametrize"
        ):
            continue
        names = set()
        if (
            dec.args
            and isinstance(dec.args[0], ast.Constant)
            and isinstance(dec.args[0].value, str)
        ):
            names.update(x.strip() for x in dec.args[0].value.split(","))
        elif (
            dec.args
            and isinstance(dec.args[0], (ast.List, ast.Tuple))
            and all(
                isinstance(x, ast.Constant) and isinstance(x.value, str)
                for x in dec.args[0].elts
            )
        ):
            names.update(x.value for x in dec.args[0].elts)
        else:
            raise ValueError("dynamic parameter-name declaration cannot be reduced")
        for keyword in dec.keywords:
            if keyword.arg != "indirect":
                continue
            if (
                isinstance(keyword.value, ast.Constant)
                and type(keyword.value.value) is bool
            ):
                if keyword.value.value:
                    names.clear()
            elif isinstance(keyword.value, (ast.List, ast.Tuple)) and all(
                isinstance(x, ast.Constant) and isinstance(x.value, str)
                for x in keyword.value.elts
            ):
                names -= {x.value for x in keyword.value.elts}
            else:
                raise ValueError(
                    "dynamic indirect parameter declaration cannot be reduced"
                )
        result.update(names)
    return result


def select(visible):
    """No material record, after bytes, target, patch, or changed-file list accepted."""
    if set(visible) != {"identity", "identity_sha256", "runtime", "task", "cases"}:
        raise ValueError(
            "selector accepts only the sanitized visible-material interface"
        )
    identity = visible["identity"]
    if sha(canonical(identity)) != visible["identity_sha256"]:
        raise ValueError("visible material identity changed")
    for label in ("runtime", "task"):
        if [
            {"path": p, "sha256": sha(b), "bytes": len(b)}
            for p, b in sorted(visible[label].items())
        ] != identity[label]:
            raise ValueError("visible material bytes changed")
    if sha(canonical(visible["cases"])) != identity["cases_sha256"]:
        raise ValueError("before cases changed")
    graph = ContextGraph(visible["runtime"], visible["task"])
    tests = identity["test_paths"]
    roots = []
    missing = []
    # Preserve every originally selected case, including passing parameters.
    # Function text includes its entire original parameter decorators.
    for case in visible["cases"]:
        name = case["name"].split("[", 1)[0]
        matches = []
        for path in tests:
            graph.load(path)
            module = path.rsplit(".", 1)[0].replace("/", ".")
            if module not in case["classname"]:
                continue
            if case["classname"].endswith(module):
                matches += [
                    u
                    for u in graph.by_path.get(path, [])
                    if u["kind"] == "function" and u["qualname"] == name
                ]
            elif module + "." in case["classname"]:
                klass = case["classname"].rsplit(module + ".", 1)[1]
                for header in graph.by_path.get(path, []):
                    if header["kind"] == "class_header" and header["qualname"] == klass:
                        graph.add(
                            header,
                            "original selected execution class, including inherited setup",
                        )
                        matches += graph.class_members(header, name)
        if not matches:
            missing.append(case["classname"] + "::" + case["name"])
        for unit in matches:
            graph.add(unit, "complete original selected test, all parameters")
            roots.append(unit["unit_id"])
    if missing:
        graph.blockers.add(
            "generated or unresolved complete test boundary: "
            + str(len(missing))
            + " selected cases"
        )
    fixture_paths = set(tests)
    for path in tests:
        for parent in [PurePosixPath(path).parent, *PurePosixPath(path).parents]:
            candidate = str(parent / "conftest.py")
            if candidate in visible["task"]:
                fixture_paths.add(candidate)
    fixtures = {}
    for path in sorted(fixture_paths):
        graph.load(path)
        for unit in graph.by_path.get(path, []):
            if "pytestmark" in unit["exports"]:
                graph.add(unit, "complete module/class pytest marks")
            if "pytest_plugins" in unit["exports"]:
                graph.blockers.add(
                    "pytest plugin fixture closure not resolved: " + path
                )
            for node in functions(graph, unit):
                declared, autouse = fixture_info(node)
                if declared:
                    fixtures.setdefault(node.name, []).append(unit)
                if autouse or node.name in SETUP_NAMES:
                    # Setup outside selected classes is not a dependency.
                    scopes = {
                        graph.units[k]["parent_class"]
                        for k in roots
                        if graph.units[k]["path"] == path
                    }
                    if unit["parent_class"] is None or unit["parent_class"] in scopes:
                        graph.add(unit, "complete applicable setup or autouse fixture")
                if node.name == "pytest_generate_tests":
                    graph.blockers.add(
                        "dynamic pytest parameter generator needs complete case binding: "
                        + path
                    )
    processed = set()
    while set(graph.selected) - processed:
        for key in sorted(set(graph.selected) - processed):
            processed.add(key)
            unit = graph.units[key]
            for node in functions(graph, unit):
                declared, _ = fixture_info(node)
                if key not in roots and not declared:
                    continue
                try:
                    parameters = parameter_names(node)
                except ValueError as error:
                    graph.blockers.add(
                        str(error) + ": " + unit["path"] + ":" + unit["qualname"]
                    )
                    parameters = set()
                needed = {
                    a.arg
                    for a in [
                        *node.args.posonlyargs,
                        *node.args.args,
                        *node.args.kwonlyargs,
                    ]
                }
                needed -= parameters | {"self", "cls"}
                positional = [*node.args.posonlyargs, *node.args.args]
                if node.args.defaults:
                    needed -= {a.arg for a in positional[-len(node.args.defaults) :]}
                needed -= {
                    a.arg
                    for a, default in zip(node.args.kwonlyargs, node.args.kw_defaults)
                    if default is not None
                }
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Call) and (dotted(dec.func) or "").endswith(
                        ".usefixtures"
                    ):
                        if all(
                            isinstance(a, ast.Constant) and isinstance(a.value, str)
                            for a in dec.args
                        ):
                            needed |= {a.value for a in dec.args}
                        else:
                            graph.blockers.add(
                                "dynamic usefixtures declaration: "
                                + unit["path"]
                                + ":"
                                + unit["qualname"]
                            )
                for name in sorted(needed):
                    if name in fixtures:
                        for dep in fixtures[name]:
                            graph.add(dep, "complete named fixture for " + key)
                    elif name not in BUILTIN_FIXTURES:
                        graph.blockers.add(
                            "required fixture binding absent: "
                            + unit["path"]
                            + ":"
                            + name
                        )
        graph.close()
    runtime_frames = []
    for case in visible["cases"]:
        for raw_path, line, function in FRAME.findall(case["failure"] or ""):
            matches = [
                p
                for p in visible["runtime"]
                if raw_path == p or raw_path.endswith("/" + p)
            ]
            if len(matches) != 1:
                continue
            path = matches[0]
            graph.load(path)
            candidates = [
                u
                for u in graph.by_path.get(path, [])
                if u["start_line"] <= int(line) - 1 < u["end_line"]
            ]
            if not candidates:
                graph.blockers.add(
                    "before runtime frame has no complete source boundary: "
                    + path
                    + ":"
                    + line
                )
            for unit in candidates:
                graph.add(unit, "original before failure frame")
                runtime_frames.append(
                    {
                        "path": path,
                        "line": int(line),
                        "function": function,
                        "unit_id": unit["unit_id"],
                    }
                )
    graph.retain_project_attribute_closure()
    entrypoints = set(roots)
    for key in graph.selected:
        for node in functions(graph, graph.units[key]):
            if graph.units[key]["path"] not in visible["runtime"] and (
                fixture_info(node)[0] or node.name in SETUP_NAMES
            ):
                entrypoints.add(key)
    fixture_resolution = resolve_task_fixture_paths(graph, sorted(entrypoints))
    for path in fixture_resolution["paths"]:
        if path.endswith(".py"):
            graph.all_file(path, "complete statically resolved original task script")
    graph.retain_project_attribute_closure()
    for key in graph.task_io_units - set(fixture_resolution["resolved_units"]):
        unit = graph.units[key]
        graph.blockers.add(
            "task file/script input has no complete static fixture binding: "
            + unit["path"]
            + ":"
            + unit["qualname"]
        )
    binding, _ = bind(identity["source_id"], visible["runtime"])
    units = sorted(
        [graph.units[k] for k in graph.selected],
        key=lambda u: (u["path"], u["start_line"]),
    )
    allowed = [u["unit_id"] for u in units if u["path"] in visible["runtime"]]
    if not allowed:
        graph.blockers.add(
            "no runtime action location follows from before/task evidence"
        )
    failures = [
        {"case": c["classname"] + "::" + c["name"], "text": c["failure"]}
        for c in visible["cases"]
        if c["failure"] is not None
    ]
    header = (
        "Repair the bound original runtime using one JSON action. Keep every original test and fixture.\n"
        'Return only {"schema":"hepta.source-unit-line-actions.v1","binding_sha256":"HASH","edits":['
        '{"unit_id":"ID","kind":"replace_lines","start_line":0,"end_line":1,"replacement":"text"}]}.'
        "\nIndices are zero-based original file lines; end is exclusive. Replace only visible unit intervals. "
        "A new complete helper may use kind insert_after with equal indices adjacent to a visible unit, "
        "crossing unchanged whitespace only. Empty edits means no change. Preserve coupled .py/.pyx files.\n"
    )
    pieces = [
        header,
        "Source: " + identity["source_id"],
        "Binding: " + binding["binding_sha256"],
        "Original selector: " + identity["selector"],
        "Original selected cases (none removed): " + str(len(visible["cases"])),
        "Original before failures:\n" + canonical(failures).decode(),
    ]
    for unit in units:
        if unit["path"] in fixture_resolution["paths"]:
            continue  # The complete unchanged fixture file is rendered once below.
        role = (
            "runtime action unit"
            if unit["path"] in visible["runtime"]
            else "fixed task unit"
        )
        pieces.append(
            "\n"
            + role
            + " "
            + unit["path"]
            + " "
            + unit["qualname"]
            + "\n"
            + "ID "
            + unit["unit_id"]
            + " original lines ["
            + str(unit["start_line"])
            + ","
            + str(unit["end_line"])
            + ") SHA256 "
            + unit["text_sha256"]
            + "\n"
            + unit["text"]
        )
    for path in fixture_resolution["paths"]:
        raw = visible["task"][path]
        try:
            text = raw.decode("utf-8")
        except UnicodeError:
            graph.blockers.add("required original fixture is not UTF-8 text: " + path)
            continue
        pieces.append(
            "\nComplete original task fixture "
            + path
            + " SHA256 "
            + sha(raw)
            + "\n"
            + text
        )
    prompt = "\n".join(pieces)
    context_identity = {
        "visible_identity_sha256": visible["identity_sha256"],
        "binding_sha256": binding["binding_sha256"],
        "allowed_units": sorted(allowed),
        "unit_texts": [{"id": u["unit_id"], "sha256": u["text_sha256"]} for u in units],
        "prompt_sha256": sha(prompt.encode()),
    }
    return {
        "schema": "hepta.e5-visible-context.v1",
        "source_id": identity["source_id"],
        "context_identity_sha256": sha(canonical(context_identity)),
        "visible_identity_sha256": visible["identity_sha256"],
        "binding": binding,
        "units": [
            {**u, "selection_reason": graph.selected[u["unit_id"]]} for u in units
        ],
        "allowed_units": sorted(allowed),
        "before_runtime_frames": runtime_frames,
        "selected_case_count": len(visible["cases"]),
        "unresolved_cases": missing,
        "external_import_contracts": sorted(graph.external_imports),
        "dependency_contracts": sorted(graph.dependency_contracts),
        "task_fixture_resolution": fixture_resolution,
        "blockers": sorted(graph.blockers),
        "v1_static_context_closed": not graph.blockers,
        "arbitrary_python_semantic_completeness_proven": False,
        "static_scope": "Complete selected units and resolved lexical/project receiver dependencies; explicit Python/external object API contracts; unsupported dynamic behavior blocks v1.",
        "prompt": prompt,
        "prompt_sha256": sha(prompt.encode()),
        "prompt_bytes": len(prompt.encode()),
        "training_execution_admitted": False,
    }
