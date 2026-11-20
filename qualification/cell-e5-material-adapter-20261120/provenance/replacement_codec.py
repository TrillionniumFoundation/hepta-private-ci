"""Complete-function transport into the unchanged upstream strict patch gate."""

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import time

NATIVE_PATH = Path(
    "/home/qian-qi/work/hepta-upstream-current-policy-20261118-2e9b/"
    "execution-code/native_sandbox.py"
)
NATIVE_SHA256 = "49cced4d3eb61ee86b1f55a11ca097be7618a0fc9b59e515f1b1d7676bec671c"
TASKS_PATH = Path(
    "/home/qian-qi/work/hepta-upstream-current-policy-20261118-2e9b/prepared/TASKS.json"
)
TASKS_SHA256 = "b30229f6fe886a0d23151b3e761592e3e11eeb333bdaf7e79c606eb6f85a08de"
SOURCE_INVENTORY_SHA256 = (
    "686f1d77e274486034044ead9ec1b5db25c98c87b530264e1128766da785d0fa"
)
CONSTANT_INSERT_BEFORE = {"tox-dev/platformdirs": "_VALUE_PATTERN"}
FORMAT = "closed_python_function_v1"
MAXIMUM_RAW_BYTES = 32768


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def write(path, value):
    raw = value if isinstance(value, bytes) else canonical(value) + b"\n"
    with Path(path).open("xb") as stream:
        stream.write(raw)
    return sha(raw)


def native_module():
    if sha(NATIVE_PATH.read_bytes()) != NATIVE_SHA256:
        raise ValueError("original native verifier bytes changed")
    spec = importlib.util.spec_from_file_location(
        "replacement_original_native", NATIVE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.SOURCES_SHA != SOURCE_INVENTORY_SHA256:
        raise ValueError("original upstream inventory binding changed")
    return module


def original_task(project):
    raw = TASKS_PATH.read_bytes()
    if sha(raw) != TASKS_SHA256:
        raise ValueError("original A task bytes changed")
    matches = [row for row in json.loads(raw) if row["project_id"] == project]
    if len(matches) != 1:
        raise ValueError("one bound original A task required")
    return matches[0]


def node_span(text, node):
    """Keep exact original line bytes; never AST-unparse a generated replacement."""
    lines = text.splitlines(keepends=True)
    first = (
        min([node.lineno, *[row.lineno for row in getattr(node, "decorator_list", [])]])
        - 1
    )
    last = node.end_lineno
    start = len("".join(lines[:first]))
    end = len("".join(lines[:last]))
    return start, end, text[start:end]


def source_binding(project):
    """Derive trusted replacement spans only from the bound BEFORE revision."""
    native = native_module()
    task = original_task(project)
    _, folder = native.source(project)
    path, name, extra = native.TARGETS[project]
    before = (folder / "before" / path).read_bytes()
    if (
        task["source_path"] != path
        or task["allowed_function"] != name
        or task["optional_module_constant"] != extra
        or task["original_source_sha256"] != sha(before)
    ):
        raise ValueError("bound original source identity differs")
    text = before.decode("utf-8")
    tree = ast.parse(text)
    fn = native.function(tree, name)
    start, end, old = node_span(text, fn)
    if text.count(old) != 1:
        raise ValueError("trusted original function text is not unique")
    binding = {
        "project_id": project,
        "path": path,
        "function": name,
        "optional_constant": extra,
        "original_source_sha256": sha(before),
        "original_tests_sha256": task["original_tests_sha256"],
        "function_start_character": start,
        "function_end_character": end,
        "function_old_sha256": sha(old.encode()),
        "function_old": old,
        "constant_slot": None,
        "original_task_file_sha256": TASKS_SHA256,
        "native_verifier_sha256": NATIVE_SHA256,
    }
    if extra:
        existing = [row for row in tree.body if native.constant_name(row) == extra]
        if existing:
            raise ValueError("this frozen panel expects no original optional constant")
        anchor_name = CONSTANT_INSERT_BEFORE[project]
        anchors = [row for row in tree.body if native.constant_name(row) == anchor_name]
        if len(anchors) != 1:
            raise ValueError("exactly one original constant insertion anchor required")
        left, right, anchor = node_span(text, anchors[0])
        if text.count(anchor) != 1 or not (right <= start or left >= end):
            raise ValueError("constant insertion anchor is not unique and disjoint")
        binding["constant_slot"] = {
            "insert_before_original_name": anchor_name,
            "start_character": left,
            "end_character": right,
            "anchor_old": anchor,
            "anchor_sha256": sha(anchor.encode()),
        }
    return before, binding


def parse_payload(project, answer, native):
    if not isinstance(answer, str) or not 0 < len(answer.encode()) <= MAXIMUM_RAW_BYTES:
        raise ValueError("bounded raw Python code block required")
    if "\r" in answer or "\x00" in answer:
        raise ValueError("only LF Python source without NUL is admitted")
    outer = answer[:-1] if answer.endswith("\n") else answer
    if not outer.startswith("```python\n") or not outer.endswith("\n```"):
        raise ValueError(
            "exactly one closed python code block with no surrounding prose required"
        )
    body = outer[len("```python\n") : -len("```")]
    if "```" in body:
        raise ValueError("additional code fences are not admitted")
    tree = ast.parse(body)
    _, name, extra = native.TARGETS[project]
    functions = [
        row
        for row in tree.body
        if isinstance(row, ast.FunctionDef) and row.name == name
    ]
    constants = [
        row for row in tree.body if extra and native.constant_name(row) == extra
    ]
    if len(functions) != 1 or len(constants) > 1:
        raise ValueError(
            "exactly one permitted function and at most one permitted constant required"
        )
    permitted = functions + constants
    if len(permitted) != len(tree.body):
        raise ValueError(
            "content outside the permitted function/constant is not admitted"
        )
    spans = sorted(node_span(body, row) for row in permitted)
    cursor = 0
    for start, end, _ in spans:
        if body[cursor:start].strip():
            raise ValueError("unassigned code or comments outside permitted spans")
        cursor = end
    if body[cursor:].strip():
        raise ValueError("unassigned trailing code or comments")
    fn_text = node_span(body, functions[0])[2]
    constant_text = node_span(body, constants[0])[2] if constants else None
    return fn_text, constant_text


def action_from_bound_before(project, answer, before, binding):
    """Pure conversion; this path never obtains replacement text from AFTER."""
    native = native_module()
    if (
        project != binding["project_id"]
        or sha(before) != binding["original_source_sha256"]
    ):
        raise ValueError("input bytes do not match the frozen BEFORE binding")
    if binding["path"] != native.TARGETS[project][0]:
        raise ValueError("bound allowed path differs")
    fn_text, constant_text = parse_payload(project, answer, native)
    text = before.decode("utf-8")
    old = binding["function_old"]
    if sha(old.encode()) != binding["function_old_sha256"] or text.count(old) != 1:
        raise ValueError("trusted original function text changed or is not unique")
    if text.index(old) != binding["function_start_character"]:
        raise ValueError("trusted original function position changed")
    edits = [{"old": old, "new": fn_text}]
    if constant_text is not None:
        slot = binding["constant_slot"]
        if slot is None:
            raise ValueError("no optional constant slot was frozen")
        anchor = slot["anchor_old"]
        if sha(anchor.encode()) != slot["anchor_sha256"] or text.count(anchor) != 1:
            raise ValueError(
                "trusted original constant anchor changed or is not unique"
            )
        if text.index(anchor) != slot["start_character"]:
            raise ValueError("trusted original constant anchor position changed")
        edits.append({"old": anchor, "new": constant_text + anchor})
    action = native.canonical({"edits": edits}).decode()
    receipt = {
        "schema": "hepta.complete-function-conversion.v1",
        "format": FORMAT,
        "raw_answer_sha256": sha(answer.encode()),
        "converted_action_sha256": sha(action.encode()),
        "binding_sha256": sha(canonical(binding)),
        "function_new_sha256": sha(fn_text.encode()),
        "optional_constant_new_sha256": sha(constant_text.encode())
        if constant_text is not None
        else None,
        "generated_new_text_from_model_only": True,
    }
    return action, receipt


def convert(project, answer):
    before, binding = source_binding(project)
    action, receipt = action_from_bound_before(project, answer, before, binding)
    return action, receipt, binding


def verify(project, answer, output):
    output = Path(output)
    output.mkdir(exist_ok=False)
    started = time.perf_counter()
    write(output / "RAW_ANSWER.txt", answer.encode())
    try:
        action, conversion, binding = convert(project, answer)
    except (ValueError, SyntaxError, TypeError, KeyError) as error:
        result = {
            "success": False,
            "stage": "replacement_admission",
            "reason": str(error),
            "error_type": type(error).__name__,
            "raw_answer_sha256": sha(answer.encode()),
            "converted_action_sha256": None,
            "actual_native_child": False,
        }
    else:
        write(output / "BINDING.json", binding)
        write(output / "CONVERSION.json", conversion)
        write(output / "CONVERTED_ACTION.json", action.encode())
        native = native_module()
        original = native.verify(project, action, output / "original-verifier")
        result = {
            "success": original["success"],
            "stage": original["stage"],
            "raw_answer_sha256": sha(answer.encode()),
            "converted_action_sha256": sha(action.encode()),
            "conversion_sha256": sha(canonical(conversion)),
            "original_verification_sha256": sha(canonical(original)),
            "original_verification": original,
            "actual_native_child": original["actual_native_child"],
        }
    result.update(
        wall_seconds=time.perf_counter() - started,
        wrapper_source_sha256=sha(Path(__file__).read_bytes()),
        original_verifier_sha256=NATIVE_SHA256,
        new_model_calls=0,
        new_training_updates=0,
    )
    write(output / "VERIFICATION.json", result)
    return result


def feedback(result):
    if "original_verification" in result:
        return native_module().feedback(result["original_verification"])
    return canonical(
        {
            "success": False,
            "stage": result["stage"],
            "reason": result["reason"][:400],
            "verification_digest": sha(canonical(result)),
        }
    ).decode()
