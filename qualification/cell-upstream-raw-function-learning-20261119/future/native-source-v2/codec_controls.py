"""Actual CPU admission controls; no upstream code, models or tests are run."""

import ast
import json
from pathlib import Path
import sys
import time

import future_native as native


def main():
    spec_path, output = Path(sys.argv[1]), Path(sys.argv[2])
    output.mkdir(exist_ok=False)
    started = time.perf_counter()
    spec = native.bound(spec_path)
    before, after = native.before_oracle(spec)
    parser = native.load_module(
        "control_original_parser", native.CODEC, native.CODEC_SHA
    )
    gate = native.load_module(
        "control_original_gate", native.ANCESTOR, native.ANCESTOR_SHA
    )
    project = spec["project_id"]
    gate.TARGETS[project] = (
        spec["source_path"],
        spec["function"],
        spec["optional_constant"],
    )
    if spec["optional_constant"] is not None:
        raise ValueError(
            "this control fixture is the first no-constant original source"
        )
    after_text = after.decode()
    node = gate.function(ast.parse(after_text), spec["function"])
    fn = parser.node_span(after_text, node)[2]
    answer = "```python\n" + fn + "```"
    candidate, admission = native.convert(spec, answer)
    if candidate != after:
        raise AssertionError("reference does not reconstruct exact original AFTER")
    before_text = before.decode()
    old = parser.node_span(
        before_text, gate.function(ast.parse(before_text), spec["function"])
    )[2]
    compatibility = output / "original-admit-inputs"
    for variant, raw in [("before", before), ("after", after)]:
        path = compatibility / variant / spec["source_path"]
        path.parent.mkdir(parents=True)
        native.write(path, raw)

    def source(requested):
        if requested != project:
            raise ValueError("wrong original project")
        return {}, compatibility

    gate.source = source
    action = gate.canonical({"edits": [{"old": old, "new": fn}]}).decode()
    original_candidate, original_admission = gate.admit(project, action)
    if original_candidate != candidate:
        raise AssertionError("generic conversion differs from original admit")
    # These are concrete parser/capability boundaries, not task scoring changes.
    cases = {
        "missing_fence": fn,
        "unclosed_fence": answer[:-3],
        "leading_prose": "Here is a fix\n" + answer,
        "trailing_prose": answer + "\nDone",
        "second_code_block": answer + "\n" + answer,
        "duplicate_function": "```python\n" + fn + "\n" + fn + "```",
        "wrong_function": answer.replace(
            "def " + spec["function"] + "(", "def unrelated(", 1
        ),
        "new_decorator": answer.replace("def ", "@untrusted\ndef ", 1),
        "async_change": answer.replace("def ", "async def ", 1),
        "top_level_import": "```python\nimport os\n" + fn + "```",
        "top_level_assignment": "```python\nnew_global = 1\n" + fn + "```",
        "embedded_fence": answer.replace("```python\n", "```python\n# ```\n", 1),
        "carriage_return": answer.replace("\n", "\r\n"),
        "nul_character": answer + "\x00",
    }
    signature_end = fn.index("\n") + 1
    cases["forbidden_import_in_body"] = (
        "```python\n"
        + fn[:signature_end]
        + "    import os\n"
        + fn[signature_end:]
        + "```"
    )
    oversized = fn[:signature_end] + "    #" + "x" * 17000 + "\n" + fn[signature_end:]
    cases["original_old_plus_new_limit"] = "```python\n" + oversized + "```"
    rows = []
    for label, raw in cases.items():
        folder = output / label
        folder.mkdir()
        native.write(folder / "ANSWER.txt", raw.encode())
        try:
            native.convert(spec, raw)
        except (ValueError, SyntaxError, TypeError, KeyError) as error:
            result = {
                "label": label,
                "rejected": True,
                "error_type": type(error).__name__,
                "reason": str(error),
                "raw_sha256": native.sha(raw.encode()),
                "native_children": 0,
                "model_calls": 0,
            }
        else:
            raise AssertionError("negative control admitted: " + label)
        native.write(folder / "RESULT.json", result)
        rows.append(result)
    try:
        gate.admit(
            project,
            gate.canonical({"edits": [{"old": old, "new": oversized}]}).decode(),
        )
    except ValueError as error:
        original_large_error = str(error)
    else:
        raise AssertionError(
            "original admit unexpectedly accepted same oversized strings"
        )
    try:
        native.bound(spec_path, "0" * 64)
    except ValueError:
        binding_rejected = True
    else:
        raise AssertionError("modified task binding admitted")
    result = {
        "status": "PASS",
        "task_spec_sha256": spec["_spec_sha256"],
        "reference_exact_after": candidate == after,
        "reference_candidate_sha256": native.sha(candidate),
        "original_admit_candidate_same_bytes": original_candidate == candidate,
        "original_admission": original_admission,
        "admission": admission,
        "negative_controls": rows,
        "wrong_spec_hash_rejected": binding_rejected,
        "original_admit_same_large_input_rejection": original_large_error,
        "source_sha256": native.sha(Path(__file__).read_bytes()),
        "runner_sha256": native.sha(Path(native.__file__).read_bytes()),
        "wall_seconds": time.perf_counter() - started,
        "new_native_children": 0,
        "new_model_calls": 0,
        "new_training_updates": 0,
    }
    native.write(output / "RESULT.json", result)
    print(
        json.dumps(
            {
                "path": str(output / "RESULT.json"),
                "sha256": native.sha((output / "RESULT.json").read_bytes()),
                "status": "PASS",
                "negative_controls": len(rows),
                "new_native_children": 0,
                "new_model_calls": 0,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
