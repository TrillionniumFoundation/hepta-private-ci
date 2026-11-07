"""Read only exact source/closure bytes and Python AST; never execute a runner."""
from pathlib import Path
import ast
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent
BIND = ROOT / "source53-r31-binding"
E = ROOT / "native-validation-results/r30-closed-input/evidence"
APPLY = ROOT / "native-validation-results/source53-apply-v2-closed/evidence"


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def nodes(raw):
    tree = ast.parse(raw.decode())
    assignments = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            name = n.targets[0].id
            assert name not in assignments
            assignments[name] = n
    return tree, assignments


def span(raw, node):
    lines = raw.splitlines(keepends=True)
    start = sum(map(len, lines[:node.lineno - 1])) + node.col_offset
    end = sum(map(len, lines[:node.end_lineno - 1])) + node.end_col_offset
    return start, end


def replace_values(raw, assignment_map, replacements):
    patches = []
    for name, replacement in replacements.items():
        start, end = span(raw, assignment_map[name].value)
        patches.append((start, end, replacement))
    for start, end, replacement in sorted(patches, reverse=True):
        raw = raw[:start] + replacement + raw[end:]
    return raw


def fixed_file(root, name, expected):
    raw = (root / name).read_bytes()
    actual = pin(raw)
    assert all(actual[k] == v for k, v in expected.items()), name
    return raw, {"path": str((root / name).relative_to(ROOT)), **actual}


def main():
    template_raw = (ROOT / "source53-r31-preparation/native-run-r31-template.py").read_bytes()
    bound_raw = (BIND / "native-run-r31-bound.py").read_bytes()
    final_raw = (BIND / "native-run-r31.py").read_bytes()
    expected = [(template_raw, 124806, "83aa49f02eca55b409d7685f6719765a46de1ccf3bea84f357cd4d352c06fab6"),
                (bound_raw, 128292, "2eb27d24c207ecd851f75f73baf163efce17f7b111635545caffb39fb7d1cf5d"),
                (final_raw, 128291, "2dc7b84b7dad0d6e150817e0dfc4105c4bb4d343103aacef0fb932eab698a6f9")]
    for raw, size, sha in expected:
        assert len(raw) == size and pin(raw)["sha256"] == sha
    _, t = nodes(template_raw)
    _, b = nodes(bound_raw)
    _, f = nodes(final_raw)
    bindings_raw = (BIND / "BINDINGS.json").read_bytes()
    bindings = json.loads(bindings_raw)
    template_unknown = {name for name, n in t.items() if isinstance(n.value, ast.Constant) and n.value.value is None}
    assert set(bindings) == template_unknown and len(bindings) == 21
    assert set(t) == set(b) == set(f)
    replacements = {}
    for name, expected_value in bindings.items():
        assert ast.literal_eval(b[name].value) == expected_value
        assert ast.literal_eval(f[name].value) == expected_value
        start, end = span(template_raw, t[name].value)
        replacements[name] = template_raw[start:end]
    assert ast.literal_eval(t["FROZEN"].value) is False and ast.literal_eval(b["FROZEN"].value) is False
    assert ast.literal_eval(f["FROZEN"].value) is True
    restored = replace_values(bound_raw, b, replacements)
    assert restored == template_raw
    assert replace_values(final_raw, f, {"FROZEN": b"False"}) == bound_raw
    # Exact assignment-node matching protects historical names containing the same suffix.
    for name in ("HISTORICAL_APPLY_TERMINAL_BYTES", "HISTORICAL_APPLY_COMPLETE_BYTES", "HISTORICAL_DELTA_MANIFEST_BYTES"):
        assert ast.dump(t[name].value) == ast.dump(b[name].value) == ast.dump(f[name].value)
    assert bindings["EXPECTED_COMMIT"] == "f74be175de66a4b351cd239d39d98cd34fe9cc1b"
    assert bindings["EXPECTED_TREE"] == "440d4a8e09af4009e4d9ea067388826308da8803"
    assert bindings["EXPECTED_CHANGED_COUNT"] == 197
    assert bindings["R30_JOB_ID"] == "1a1b25b399f-fc05-7daa"
    assert bindings["APPLY_JOB_ID"] == "1a1b2552130-fc05-7d91"
    assert bindings["APPLY_TERMINAL_NAME"] == "native-source53-apply-v2-terminal-process-status.json"

    source_raw, source_pin = fixed_file(APPLY, bindings["SOURCE_MANIFEST_NAME"], {
        "bytes": bindings["SOURCE_MANIFEST_BYTES"], "sha256": bindings["SOURCE_MANIFEST_SHA256"]})
    source = json.loads(source_raw)
    assert source["source_commit"] == bindings["EXPECTED_COMMIT"] and source["source_tree"] == bindings["EXPECTED_TREE"]
    assert len(source["changed_files"]) == len({r["path"] for r in source["changed_files"]}) == 197
    assert source["diagnostic_only"] is True and source["behavior_repair_claimed"] is False
    apply_pins = []
    values = {}
    for field in ("APPLY_COMPLETE", "APPLY_TERMINAL", "DELTA_MANIFEST"):
        raw, p = fixed_file(APPLY, bindings[field + "_NAME"], {
            "bytes": bindings[field + "_BYTES"], "sha256": bindings[field + "_SHA256"]})
        apply_pins.append(p)
        values[field] = json.loads(raw)
    complete = values["APPLY_COMPLETE"]
    assert complete["source_commit"] == bindings["EXPECTED_COMMIT"] and complete["source_tree"] == bindings["EXPECTED_TREE"]
    assert complete["actual_changed_file_count"] == 197 and complete["source_guards_pass"] is True
    assert complete["diagnostic_only"] is True and complete["behavior_repair_claimed"] is False
    assert values["APPLY_TERMINAL"]["job_id"] == bindings["APPLY_JOB_ID"]
    assert values["APPLY_TERMINAL"]["state"] == "succeeded" and values["APPLY_TERMINAL"]["exit_code"] == 0

    prefix = "native-source53-project-r30"
    required = {prefix + suffix for suffix in ("-complete.json", "-environment.json", "-preconditions.json",
        "-source-pre-verification.json", "-source-final-verification.json", "-tests-result-review.json", "-tests-test-results.json")}
    required |= {prefix + "-" + phase + suffix for phase in ("strict", "tests")
                 for suffix in ("-source-pre-verification.json", ".log", "-resources.txt", "-raw-process-result.json",
                                "-source-post-verification.json", "-receipt.json")}
    assert set(bindings["R30_INPUT_PINS"]) == required and len(required) == 19
    originals = {}
    closure_pins = []
    for name, p in sorted(bindings["R30_INPUT_PINS"].items()):
        originals[name], actual = fixed_file(E, name, p)
        closure_pins.append(actual)
    terminal_raw, terminal_pin = fixed_file(E, bindings["R30_TERMINAL_NAME"], {
        "bytes": bindings["R30_TERMINAL_BYTES"], "sha256": bindings["R30_TERMINAL_SHA256"]})
    terminal = json.loads(terminal_raw)
    assert terminal["job_id"] == bindings["R30_JOB_ID"] and terminal["state"] == "succeeded" and terminal["exit_code"] == 0
    for name in ("output_complete", "output_durable", "terminal_publication_confirmed"):
        assert terminal[name] is True
    for name in ("timed_out", "cancelled", "automatic_retry"):
        assert terminal[name] is False
    phase_results = []
    for phase in ("strict", "tests"):
        stem = prefix + "-" + phase
        raw = json.loads(originals[stem + "-raw-process-result.json"])
        receipt = json.loads(originals[stem + "-receipt.json"])
        guard = json.loads(originals[stem + "-source-post-verification.json"])
        for value in (raw, receipt):
            assert value["source_commit"] == bindings["EXPECTED_COMMIT"] and value["source_tree"] == bindings["EXPECTED_TREE"]
            assert value["phase"] == phase and value["exit_code"] == 0
        assert receipt["effective_exit_code"] == 0 and receipt["source_guards_pass"] is True and receipt["phase_pass"] is True and receipt["issues"] == []
        assert receipt["raw_process_result"] == {"path": stem + "-raw-process-result.json", **pin(originals[stem + "-raw-process-result.json"])}
        assert guard["pass"] is True and guard["changed_file_count"] == 197 and guard["expected_tree"] == guard["actual_tree"] == bindings["EXPECTED_TREE"]
        assert guard["native_head"] == "bef6fa7645df9df12b69fda499e97eed25de6c75"
        assert guard["gate_exit_code"] == 0
        assert re.findall(rb"^\s*Exit status: ([0-9]+)\s*$", originals[stem + "-resources.txt"], re.M) == [b"0"]
        assert receipt["log_sha256"] == pin(originals[stem + ".log"])["sha256"]
        assert receipt["resources_sha256"] == pin(originals[stem + "-resources.txt"])["sha256"]
        assert terminal["at_unix_ms"] / 1000 >= receipt["end_unix"]
        phase_results.append({"phase": phase, "raw_exit": raw["exit_code"], "effective_exit": receipt["effective_exit_code"],
                              "elapsed_seconds": receipt["elapsed_seconds"], "source_guard_pass": guard["pass"]})
    review = json.loads(originals[prefix + "-tests-result-review.json"])
    rows = json.loads(originals[prefix + "-tests-test-results.json"])
    assert len(rows) == len({(r["binary"], r["name"]) for r in rows}) == review["unique_test_count"] == 1345
    assert all(row["status"] == "PASS" for row in rows)
    assert review["pass"] is True and review["counts"] == {"PASS": 1345, "FAIL": 0, "TIMEOUT": 0}
    assert review["reported_skipped"] == 2 and review["baseline_missing"] == review["baseline_not_pass"] == review["additional_test_ids"] == []
    finish = json.loads(originals[prefix + "-complete.json"])
    assert finish["strict_exit"] == finish["tests_exit"] == 0 and finish["source_guards_pass"] is True
    assert finish["required_old_ids"] == 1345 and finish["all_old_ids_observed_pass"] is True
    assert finish["diagnostic_only"] is True and finish["behavior_repair_claimed"] is False
    assert finish["whole_workspace_qualification"] == "PENDING_SEPARATE_ORIGINAL_GATE"
    result = {
        "schema": "hepta.source53-r31-binding-independent-review.v1", "classification": "STATIC_BINDING_CLEAR",
        "template": pin(template_raw), "bound": pin(bound_raw), "final": pin(final_raw),
        "bindings": pin(bindings_raw), "binding_count": 21, "binding_names": sorted(bindings),
        "ast_assignment_value_spans_used_not_substring_matching": True,
        "whole_file_bound_to_template_inverse_exact": True, "final_only_frozen_false_to_true": True,
        "historical_assignment_names_preserved": True, "ast_parse_pass": True,
        "actual_source_manifest": source_pin, "actual_apply_v2_inputs": apply_pins,
        "source_count": 197, "diagnostic_only": True, "behavior_repair_claimed": False,
        "r30_originals": closure_pins, "r30_original_count": 19, "r30_terminal": terminal_pin,
        "r30_phase_results": phase_results, "r30_original_outer_exit": 0,
        "r30_pinned_original_result_readback": {"unique_test_count": 1345, "counts": {"PASS": 1345, "FAIL": 0, "TIMEOUT": 0}, "reported_skipped": 2},
        "full_r30_archive_verification_claimed_here": False,
        "execution_scope": "Only local AST, JSON, hashes and closed original artifacts. No runner import or execution.",
        "r31_executed_by_reviewer": False, "workspace_pass_claimed": False,
        "command_filters_timeout_retries_profiles_or_shared_validation_logic_changed": False,
        "canonical_source_reports_index_ledger_or_native_modified": False,
        "blockers": [], "execution_requires_root_exact_authorization": True,
    }
    output = (json.dumps(result, indent=2, ensure_ascii=False) + "\n").encode()
    with (OUT / "INDEPENDENT-REVIEW.json").open("xb") as stream:
        stream.write(output)
    print(json.dumps({"path": "INDEPENDENT-REVIEW.json", **pin(output)}))


if __name__ == "__main__":
    main()
