"""Local closure/binding only. No runner imports, remote calls or execution."""
from pathlib import Path
import ast
import difflib
import hashlib
import json
import pprint
import re

ROOT = Path("/workspace/scratch/08f5efd48967")
D = ROOT / "native-validation-results/r31-closed-input"
P = "native-workspace-r31"


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def put(path, raw):
    with path.open("xb") as stream:
        stream.write(raw)


def save_json(path, value):
    raw = (json.dumps(value, indent=2) + "\n").encode()
    put(path, raw)
    return pin(raw)


def evidence(suffix):
    return json.loads((D / "evidence" / (P + suffix)).read_bytes())


pins = json.loads((D / "R31-INPUT-PINS.json").read_bytes())
terminal_raw = (D / "evidence" / (P + "-terminal-process-status.json")).read_bytes()
terminal = json.loads(terminal_raw)
terminal_pin = pin(terminal_raw)
controller_pins = json.loads((D / "CONTROLLER-PINS.json").read_bytes())
assert len(pins) == 18 and terminal["exit_code"] == 0 and terminal["state"] == "succeeded"
assert len(controller_pins) == 4
for name, expected in pins.items():
    path = D / "evidence" / name
    if path.exists():
        observed = pin(path.read_bytes())
        assert all(observed[key] == expected[key] for key in expected)
    else:
        assert name in (P + "-tests.log", P + "-test-results.json")
for path in (D / "controller-publication").glob("*.info-original.json"):
    value = json.loads(path.read_bytes())
    name = Path(value["path"]).name
    expected = terminal_pin if name == P + "-terminal-process-status.json" else controller_pins[name]
    assert value["size"] == expected["bytes"] and value["sha256"] == expected["sha256"]

raw = evidence("-tests-raw-process-result.json")
receipt = evidence("-tests-receipt.json")
complete = evidence("-complete.json")
review = evidence("-result-review.json")
post = evidence("-source-post-test-verification.json")
assert raw["exit_code"] == receipt["exit_code"] == receipt["effective_exit_code"] == terminal["exit_code"] == 0
assert raw["command"] == receipt["command"] == ["just", "test", "--locked", "--retries", "0"]
assert receipt["phase_pass"] is True and receipt["issues"] == []
assert receipt["source_guards_pass"] is True and post["pass"] is True and post["gate_exit_code"] == 0
assert post["changed_file_count"] == 197 and post["changed_path_set_matches"] is True
assert post["actual_tree"] == post["expected_tree"] == "440d4a8e09af4009e4d9ea067388826308da8803"
assert post["native_head"] == "bef6fa7645df9df12b69fda499e97eed25de6c75"
assert post["file_mismatches"] == post["unstaged_paths"] == post["untracked_paths"] == []
assert post["cargo_lock_sha256"] == "4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c"
assert post["bazel_lock_sha256"] == "e80ef06b6f824a19cdcedd6010738b316ccca96b83ad8730fafb52153a2634fb"
assert re.findall(rb"^\s*Exit status: ([0-9]+)\s*$", (D / "evidence" / (P + "-tests-resources.txt")).read_bytes(), re.M) == [b"0"]
assert raw["start_unix"] <= raw["end_unix"] <= terminal["at_unix_ms"] / 1000
assert receipt["elapsed_seconds"] == raw["end_unix"] - raw["start_unix"]
assert review["pass"] is True and review["complete_execution_accounting"] is True
assert review["terminal_unique_test_count"] == complete["unique_test_count"] == 20228
assert review["terminal_counts"] == complete["counts"] == {"PASS": 20228, "FAIL": 0, "TIMEOUT": 0}
assert review["reported_skipped"] == complete["reported_skipped"] == 130
assert review["baseline_missing"] == review["additional_test_ids"] == review["baseline_not_pass"] == []
assert review["footer_rows_excluded"] == [] and review["duplicate_execution_ids"] is False
assert review["diagnostic_only"] is True and review["behavior_repair_claimed"] is False
assert receipt["log_sha256"] == review["log"]["sha256"] == pins[P + "-tests.log"]["sha256"]
assert receipt["resources_sha256"] == pins[P + "-tests-resources.txt"]["sha256"]
events = [json.loads(line) for line in (D / "controller/original-stdout.log").read_text().splitlines()]
assert len(events) == 3 and events[0]["phase"] == "original-default-workspace-start"
announced_raw = dict(events[1])
assert announced_raw.pop("event") == "workspace-raw-process-return"
assert announced_raw == raw and events[2] == receipt
assert terminal["log_bytes"]["stdout"]["seen"] == terminal["log_bytes"]["stdout"]["stored"] == 4875
assert terminal["log_bytes"]["stderr"]["seen"] == terminal["log_bytes"]["stderr"]["stored"] == 0

def bind(directory, template_path, expected_sha, mapping, bound_name, final_name):
    directory.mkdir(exist_ok=False)
    original = template_path.read_bytes()
    assert pin(original)["sha256"] == expected_sha
    text = original.decode()
    replacements = []
    for name, value in mapping.items():
        before = name + " = None\n"
        after = name + " = " + pprint.pformat(value, sort_dicts=True, width=100) + "\n"
        assert text.count("\n" + before) == 1
        text = text.replace("\n" + before, "\n" + after, 1)
        replacements.append((before, after))
    bound = text.encode()
    inverse = text
    for before, after in reversed(replacements):
        assert inverse.count("\n" + after) == 1
        inverse = inverse.replace("\n" + after, "\n" + before, 1)
    assert inverse.encode() == original
    assert text.count("FROZEN = False\n") == 1
    final = text.replace("FROZEN = False\n", "FROZEN = True\n", 1).encode()
    assert final.replace(b"FROZEN = True\n", b"FROZEN = False\n", 1) == bound
    for candidate in (bound, final):
        parsed = ast.parse(candidate.decode())
        values = {}
        for node in parsed.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                if node.targets[0].id in mapping:
                    values[node.targets[0].id] = ast.literal_eval(node.value)
        assert values == mapping
    put(directory / bound_name, bound)
    put(directory / final_name, final)
    first_diff = "".join(difflib.unified_diff(original.decode().splitlines(True), bound.decode().splitlines(True),
                         fromfile=template_path.name, tofile=bound_name)).encode()
    second_diff = "".join(difflib.unified_diff(bound.decode().splitlines(True), final.decode().splitlines(True),
                          fromfile=bound_name, tofile=final_name)).encode()
    put(directory / "template-to-bound.patch", first_diff)
    put(directory / "bound-to-final.patch", second_diff)
    save_json(directory / "BINDINGS.json", mapping)
    result = {
        "schema": "hepta.exact-local-closure-binding.v1",
        "template": {"path": str(template_path.relative_to(ROOT)), **pin(original)},
        "bound": {"path": str((directory / bound_name).relative_to(ROOT)), **pin(bound)},
        "final": {"path": str((directory / final_name).relative_to(ROOT)), **pin(final)},
        "literal_bindings_changed": len(mapping),
        "inverse_rebuilt_exact_template": True, "ast_literals_equal_actual_inputs": True,
        "final_change_only_frozen_boolean": True,
        "template_to_bound_patch": pin(first_diff), "bound_to_final_patch": pin(second_diff),
        "actual_terminal": terminal_pin,
        "executed_or_uploaded": False, "execution_requires_exact_root_authorization": True,
        "full_original_log_and_rows_local_readback": False,
        "large_log_rows_available_as_fixed_originals_in_native_and_immutable_pins": True,
        "root_unique_full_archive_download_pending": True,
    }
    result["readback_pin"] = save_json(directory / "BINDING-READBACK.json", result)
    return result

inventory = bind(
    ROOT / "source53-formatter-inventory-binding",
    ROOT / "source53-formatter-tool-inventory-preparation/inventory-template.py",
    "d641eed6fd28a2a42fb2d773ba95370d9e44d7cebbdfe5d68ab781c72ea55daa",
    {"R31_TERMINAL_BYTES": terminal_pin["bytes"], "R31_TERMINAL_SHA256": terminal_pin["sha256"]},
    "inventory-bound.py", "inventory.py",
)
exporter = bind(
    ROOT / "source53-r31-export-binding",
    ROOT / "source53-r31-export-preparation/export-r31-closed-template.py",
    "0a0b60ec209527b03cf54a7d7566409c9714aca13c4423fc8ef9dd0cc88be910",
    {"TERMINAL_PIN": terminal_pin, "CLOSED_ORIGINAL_PINS": pins, "CONTROLLER_ORIGINAL_PINS": controller_pins},
    "export-r31-closed-bound.py", "export-r31-closed.py",
)
rows = []
for path in sorted(D.rglob("*")):
    if path.is_file():
        rows.append({"path": str(path.relative_to(D)), **pin(path.read_bytes())})
local = {
    "schema": "hepta.r31-closed-small-original-readback.v1",
    "job_id": terminal["job_id"], "source_commit": raw["source_commit"], "source_tree": raw["source_tree"],
    "original_raw_exit": raw["exit_code"], "effective_exit": receipt["effective_exit_code"],
    "natural_outer_exit": terminal["exit_code"], "elapsed_seconds": receipt["elapsed_seconds"],
    "original_review_counts": review["terminal_counts"], "original_review_unique_ids": 20228,
    "reported_skipped": review["reported_skipped"], "source197_head_dual_lock_guard_pass": True,
    "originals_pinned": 18, "raw_originals_local": 16, "controller_raw_originals": 4,
    "controller_stdout_bytes": 4875, "controller_stderr_bytes": 0,
    "full_log_rows_locally_reparsed": False,
    "large_log_rows_pending_root_unique_archive": [
        {"path": name, **pins[name]} for name in (P + "-tests.log", P + "-test-results.json")
    ],
    "metadata_scope_reused_from_exact_current_source_fresh_closed_observation": True,
    "terminal_pin": terminal_pin, "files": rows,
    "finalizer_authorized": False, "fix_fmt_executed": False,
    "diagnostic_only": True, "behavior_repair_claimed": False,
}
local_pin = save_json(D / "LOCAL-READBACK.json", local)
print(json.dumps({"local_readback": local_pin, "inventory": inventory, "exporter": exporter}))
