"""Bounded synthetic consumer controls; no subprocess, Windows API or native test."""

from copy import deepcopy
import json

from parent_sd_parser import MARKER
from parent_sd_parser import ORIGINAL_MARKER
from parent_sd_parser import SUMMARY_GATES
from parent_sd_parser import VARIANTS
from parent_sd_parser import record_parent_sd_observation
from parent_sd_parser import verify_parent_sd


def sample():
    def result(allowed):
        return {"api_success": True, "allowed": allowed, "granted": 64 if allowed else 0,
                "win32_error": None if allowed else 5, "privilege_count": 0}

    summary = {name: True for name in SUMMARY_GATES}
    summary.update(status="observed", selected_capability_index=0,
                   selected_capability_is_restricting_only=True,
                   selected_restricting_attributes=0, restricting_count=2, parent_sd_bytes=208)
    observation = {
        "kind": "parent_delete_child_memory", "phase": "before_original_outside_actions",
        "requested": 64, "descriptor_source": "pre_action_memory",
        "rows": [{"variant": name, "result": result(allowed)}
                 for name, allowed in zip(VARIANTS, (True, True, False))],
        "summary": summary,
    }
    original = []
    for phase in ("before", "after"):
        original.append({"kind": "token", "phase": phase, "token_type": 2, "restricting_count": 2,
                         "exact_expected_capabilities": True, "sd_memory_unchanged": True,
                         "same_semantic_token_as_before": None if phase == "before" else True})
        for obj, mask in (("target", 0x10000), ("parent", 64), ("target", 0x10002),
                          ("parent", 66), ("target", 2), ("target", 1)):
            allowed = mask in (64, 1)
            access = result(allowed)
            access["granted"] = mask if allowed else 0
            original.append({"kind": "access", "phase": phase, "object": obj, "requested": mask,
                             "descriptor_source": "pre_action_memory", "result": access})
    original.append({"kind": "fresh_post_impersonation_readback", "parent_sd_same": True,
                     "target_exists": False, "target_sd_same_if_present": None,
                     "missing_target_does_not_refresh_pre_action_sd": True})
    return observation, original


def line(marker, row):
    return marker + " " + json.dumps(row, separators=(",", ":")) + "\n"


def stream(observation, original):
    lines = [line(ORIGINAL_MARKER, row) for row in original]
    lines.insert(7, line(MARKER, observation))
    return "".join(lines)


def main():
    passed = []
    row, original = sample()

    def accepts(name, texts, expected):
        assert verify_parent_sd(texts) == expected, name
        passed.append({"name": name, "expected": "accepted", "result": "PASS"})

    def rejects(name, texts):
        try:
            verify_parent_sd(texts)
        except (ValueError, KeyError, TypeError, RecursionError):
            passed.append({"name": name, "expected": "rejected", "result": "PASS"})
        else:
            raise AssertionError(name + " was incorrectly accepted")

    def altered(name, path, value):
        changed = deepcopy(row)
        target = changed
        for part in path[:-1]:
            target = target[part]
        target[path[-1]] = value
        rejects(name, [stream(changed, original)])

    raw = stream(row, original)
    accepts("capability_deny_still_allows_is_complete_observation", [raw], row)
    denied = deepcopy(row)
    denied["rows"][1]["result"].update(allowed=False, granted=0, win32_error=5)
    accepts("capability_deny_blocks_is_complete_observation", [stream(denied, original)], denied)
    denied["rows"][1]["result"]["win32_error"] = 0
    accepts("denial_retains_raw_zero_error_without_inventing_os5", [stream(denied, original)], denied)
    accepts("ansi_and_nextest_indentation", ["".join("  \x1b[32m" + s + "\x1b[0m\n"
            for s in raw.splitlines())], row)
    accepts("empty_stdout_with_single_stderr_stream", ["", raw], row)
    accepts("summary_recap_ignored", [raw + "Summary [0.1s] 2 tests run: 2 failed\n" + raw], row)
    for name, path, value in (
        ("wrong_kind", ("kind",), "access"),
        ("wrong_phase", ("phase",), "after_original_outside_actions"),
        ("wrong_source", ("descriptor_source",), "fresh_parent"),
        ("wrong_requested_bit", ("requested",), 66),
        ("boolean_request", ("requested",), True),
        ("query_count_short", ("rows",), row["rows"][:2]),
        ("query_count_extra", ("rows",), row["rows"] + [row["rows"][0]]),
        ("query_order", ("rows",), list(reversed(row["rows"]))),
        ("summary_unknown", ("summary", "status"), "unknown"),
        ("wrong_capability_index", ("summary", "selected_capability_index"), 1),
        ("boolean_capability_index", ("summary", "selected_capability_index"), False),
        ("ordinary_authority_present", ("summary", "selected_capability_is_restricting_only"), False),
        ("numeric_restricting_only", ("summary", "selected_capability_is_restricting_only"), 1),
        ("attributes_negative", ("summary", "selected_restricting_attributes"), -1),
        ("attributes_overflow", ("summary", "selected_restricting_attributes"), 2**32),
        ("wrong_restricting_count", ("summary", "restricting_count"), 1),
        ("sd_too_short", ("summary", "parent_sd_bytes"), 27),
        ("sd_over_cap", ("summary", "parent_sd_bytes"), 65537),
        ("sd_float", ("summary", "parent_sd_bytes"), 208.0),
    ):
        altered(name, path, value)
    for gate in SUMMARY_GATES:
        altered(gate + "_false", ("summary", gate), False)
        altered(gate + "_numeric", ("summary", gate), 1)
    for index in range(3):
        altered(f"api_failure_{index}", ("rows", index, "result", "api_success"), False)
        altered(f"api_numeric_{index}", ("rows", index, "result", "api_success"), 1)
        altered(f"unknown_allowed_{index}", ("rows", index, "result", "allowed"), None)
        altered(f"numeric_allowed_{index}", ("rows", index, "result", "allowed"), 1)
        altered(f"contradictory_grant_{index}", ("rows", index, "result", "granted"),
                64 if index == 2 else 0)
        altered(f"boolean_grant_{index}", ("rows", index, "result", "granted"), False)
        altered(f"privilege_count_over_cap_{index}", ("rows", index, "result", "privilege_count"), 257)
    for index in (0, 1):
        altered(f"allowed_with_error_{index}", ("rows", index, "result", "win32_error"), 5)
    altered("denied_without_raw_error", ("rows", 2, "result", "win32_error"), None)
    altered("denied_error_overflow", ("rows", 2, "result", "win32_error"), 2**32)
    for index, allowed in ((0, False), (2, True)):
        changed = deepcopy(row)
        changed["rows"][index]["result"].update(allowed=allowed, granted=64 if allowed else 0,
                                               win32_error=None if allowed else 5)
        rejects(f"control_failure_{index}", [stream(changed, original)])

    for scope, path in (("record", ()), ("summary", ("summary",)),
                        ("entry", ("rows", 1)), ("result", ("rows", 1, "result"))):
        for operation in ("extra", "missing"):
            changed = deepcopy(row)
            target = changed
            for part in path:
                target = target[part]
            if operation == "extra":
                target["unexpected"] = True
            else:
                target.pop(next(iter(target)))
            rejects(scope + "_" + operation + "_field", [stream(changed, original)])
    for name, index, key, value in (
        ("token_wrong_phase", 0, "phase", "after"),
        ("token_wrong_type", 0, "token_type", 1),
        ("token_wrong_caps", 0, "exact_expected_capabilities", False),
        ("token_memory_changed", 0, "sd_memory_unchanged", False),
        ("token_count_changed", 0, "restricting_count", 3),
        ("anchor_wrong_phase", 2, "phase", "after"),
        ("anchor_wrong_object", 2, "object", "target"),
        ("anchor_wrong_source", 2, "descriptor_source", "fresh_parent"),
        ("anchor_wrong_request", 2, "requested", 66),
    ):
        changed = deepcopy(original)
        changed[index][key] = value
        rejects(name, [stream(row, changed)])
    for key, value in (("api_success", False), ("allowed", False), ("granted", 0)):
        changed = deepcopy(original)
        changed[2]["result"][key] = value
        rejects("anchor_" + key + "_contradicts_baseline", [stream(row, changed)])
    for index in (0, 2):
        changed = deepcopy(original)
        changed[index] = []
        rejects(f"anchor_not_object_{index}", [stream(row, changed)])

    marker_line = line(MARKER, row)
    original_lines = [line(ORIGINAL_MARKER, item) for item in original]
    for name, texts in (
        ("missing", [raw.replace(marker_line, "")]),
        ("duplicate", [raw + marker_line]),
        ("wrong_placement", [marker_line + "".join(original_lines)]),
        ("split_stream_order_unknown", ["".join(original_lines), marker_line]),
        ("original_missing", [raw.replace(original_lines[-1], "")]),
        ("original_duplicate", [raw + original_lines[-1]]),
        ("foreign_prefix", [raw.replace(marker_line, "unrelated " + marker_line)]),
        ("malformed_json", [raw.replace(marker_line, MARKER + " {\n")]),
        ("duplicate_json_key", [raw.replace(marker_line, marker_line.replace(
            '"requested":64', '"requested":64,"requested":64'))]),
        ("oversized_record", [raw.replace(marker_line, marker_line[:-1] + " " * 4096 + "\n")]),
        ("invalid_utf8_budget", [raw.replace(marker_line, marker_line.replace(
            '"observed"', json.dumps("é" * 4096, ensure_ascii=False)))]),
        ("only_summary_recap", ["Summary [0.1s] 2 tests run: 2 failed\n" + raw]),
        ("fixed_unknown_fallback", [raw.replace(marker_line, line(MARKER, {
            "kind": "parent_delete_child_memory", "summary": {
                "status": "unknown", "error": "serialization_or_log_limit"}}))]),
    ):
        rejects(name, texts)

    report = {"native": {"exit": 1, "attempts": [["FAIL", "factory"], ["FAIL", "legacy"]]},
              "errors": [], "commands": [{"exit": 101}, {"exit": 1}]}
    before = deepcopy(report)
    record_parent_sd_observation(report, [raw])
    observed = report["native"].pop("parent_sd_observation")
    assert report == before
    assert observed == {"record_complete": True, "status": "observed", "record": row,
                        "capability_deny_blocks_this_access_check": False,
                        "production_confinement_qualified": False}
    passed.append({"name": "complete_observation_preserves_all_original_failures", "result": "PASS"})
    record_parent_sd_observation(report, [stream(denied, original)])
    observed = report["native"].pop("parent_sd_observation")
    assert report == before and observed["capability_deny_blocks_this_access_check"] is True
    assert observed["production_confinement_qualified"] is False
    passed.append({"name": "capability_denial_is_not_production_qualification", "result": "PASS"})
    record_parent_sd_observation(report, [""])
    observed = report["native"].pop("parent_sd_observation")
    assert observed == {"record_complete": False, "status": "unknown",
                        "production_confinement_qualified": False}
    assert len(report["errors"]) == 1 and report["errors"][0].startswith("parent-SD-observation: ")
    report["errors"] = []
    assert report == before
    passed.append({"name": "missing_observation_keeps_unknown_and_original_exit", "result": "PASS"})
    assert len(passed) == len({item["name"] for item in passed})
    print(json.dumps({"scope": "synthetic parent-SD artifact consumer controls only", "native_runs": 0,
                      "passed": len(passed), "controls": passed}, indent=2))


if __name__ == "__main__":
    main()
