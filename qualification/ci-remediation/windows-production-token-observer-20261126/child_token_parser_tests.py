"""Synthetic controls for the child-token evidence parser; no native execution."""

from copy import deepcopy
import json
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parent
NATIVE = runpy.run_path(str(ROOT / "run_native.py"), run_name="parser_controls")
VERIFY = NATIVE["verify_child_token"]
RECORD = NATIVE["record_child_token"]
PREFIX = "HEPTA_LEGACY_SPAWN_TOKEN "


def sample():
    facts = {
        "token_type": 1, "user_roles": ["token_user"], "user_attributes": 0,
        "owner_roles": ["token_default_owner", "administrators"],
        "group_count": 1, "groups": [{"roles": ["administrators"], "attributes": 16}],
        "restricting_count": 1, "restricting": [{"roles": ["other"], "attributes": 0}],
        "privilege_count": 1, "privileges_luid_and_raw_attributes": [[0, 23, 3]],
        "integrity_rid": 8192, "integrity_attributes": 96, "mandatory_policy": 1,
    }
    return {
        "status": "observed", "poll_count": 1, "hook_count": 1, "overlapping_scope": False,
        "launch_input": {"status": "observed", "facts": facts},
        "actual_child_primary": {"status": "observed", "facts": deepcopy(facts)},
        "comparison": {key: True for key in (
            "raw_observed_fields_equal", "user_equal", "owner_equal", "groups_equal",
            "restricting_equal", "raw_privileges_equal", "integrity_equal",
            "mandatory_policy_equal", "token_type_equal")},
    }


def stream(value):
    return PREFIX + json.dumps(value, separators=(",", ":")) + "\n"


def main():
    passed = []

    def accepts(name, texts, expected):
        assert VERIFY(texts) == expected, name
        passed.append({"name": name, "expected": "accepted", "result": "PASS"})

    def rejects(name, texts):
        try:
            VERIFY(texts)
        except (ValueError, KeyError, TypeError, RecursionError):
            passed.append({"name": name, "expected": "rejected", "result": "PASS"})
        else:
            raise AssertionError(name + " was unexpectedly accepted")

    equal = sample()
    accepts("complete_equal_facts", [stream(equal), ""], equal)
    unequal = deepcopy(equal)
    unequal["actual_child_primary"]["facts"]["groups"][0]["attributes"] = 4
    unequal["comparison"].update({"raw_observed_fields_equal": False, "groups_equal": False})
    accepts("observed_group_disagreement_is_not_unknown", ["", stream(unequal)], unequal)
    accepts("indented_ansi_record", ["  \x1b[32m" + stream(equal).rstrip() + "\x1b[0m\n"], equal)
    accepts("summary_recap_is_not_a_second_record",
            [stream(equal) + "Summary [0.1s] 2 tests run: 2 failed\n" + stream(equal)], equal)
    rejects("missing", [""])
    rejects("only_after_summary", ["Summary [0.1s] 2 tests run: 2 failed\n" + stream(equal)])
    rejects("duplicate_across_streams", [stream(equal), stream(equal)])
    rejects("malformed_json", [PREFIX + "{bad}\n"])
    rejects("duplicate_json_key", [stream(equal).replace('"status":"observed"',
            '"status":"observed","status":"observed"', 1)])
    rejects("oversized", [PREFIX + " " * 16384 + "{}\n"])
    rejects("non_marker_prefix", ["unexpected " + stream(equal)])
    changes = (
        ("unknown_top", lambda row: row.update(status="unknown")),
        ("overlap", lambda row: row.update(overlapping_scope=True)),
        ("zero_poll", lambda row: row.update(poll_count=0)),
        ("multiple_hooks", lambda row: row.update(hook_count=2)),
        ("boolean_hook_is_not_integer", lambda row: row.update(hook_count=True)),
        ("missing_child", lambda row: row.pop("actual_child_primary")),
        ("unknown_child", lambda row: row["actual_child_primary"].update(status="unknown")),
        ("non_primary", lambda row: row["actual_child_primary"]["facts"].update(token_type=2)),
        ("raw_sid_field", lambda row: row["actual_child_primary"]["facts"].update(sid="S-1-0-0")),
        ("group_count_mismatch", lambda row: row["launch_input"]["facts"].update(group_count=2)),
        ("array_bound", lambda row: row["launch_input"]["facts"].update(group_count=65)),
        ("unknown_role", lambda row: row["launch_input"]["facts"].update(owner_roles=["private_sid"])),
        ("duplicate_role", lambda row: row["launch_input"]["facts"].update(owner_roles=["token_default_owner"] * 2)),
        ("invalid_privilege", lambda row: row["launch_input"]["facts"].update(privileges_luid_and_raw_attributes=[[0, -1, 3]])),
        ("untyped_comparison", lambda row: row["comparison"].update(groups_equal=1)),
        ("aggregate_mismatch", lambda row: row["comparison"].update(raw_observed_fields_equal=False)),
    )
    for name, change in changes:
        value = deepcopy(equal)
        change(value)
        rejects(name, [stream(value)])

    for comparison in ("token_type_equal", "integrity_equal", "mandatory_policy_equal", "raw_privileges_equal"):
        value = deepcopy(equal)
        value["comparison"].update({"raw_observed_fields_equal": False, comparison: False})
        rejects("visible_identical_but_" + comparison + "_false", [stream(value)])
    for field, replacement, comparison in (
        ("integrity_rid", 4096, "integrity_equal"),
        ("integrity_attributes", 32, "integrity_equal"),
        ("mandatory_policy", 2, "mandatory_policy_equal"),
        ("privileges_luid_and_raw_attributes", [[0, 23, 0]], "raw_privileges_equal"),
    ):
        value = deepcopy(equal)
        value["actual_child_primary"]["facts"][field] = replacement
        rejects("visible_" + field + "_differs_but_comparison_true", [stream(value)])
        value["comparison"].update({"raw_observed_fields_equal": False, comparison: False})
        accepts("visible_" + field + "_disagreement_is_observed", [stream(value)], value)
    for comparison in ("user_equal", "owner_equal", "groups_equal", "restricting_equal"):
        value = deepcopy(equal)
        value["comparison"].update({"raw_observed_fields_equal": False, comparison: False})
        accepts("same_lossy_summaries_allow_hidden_" + comparison + "_false", [stream(value)], value)
    for entries, count, comparison in (("groups", "group_count", "groups_equal"),
                                        ("restricting", "restricting_count", "restricting_equal")):
        value = deepcopy(equal)
        value["actual_child_primary"]["facts"][entries][0]["attributes"] += 1
        rejects(entries + "_attributes_differ_but_raw_equal", [stream(value)])
        value = deepcopy(equal)
        value["actual_child_primary"]["facts"][entries] = []
        value["actual_child_primary"]["facts"][count] = 0
        rejects(entries + "_count_differs_but_raw_equal", [stream(value)])
        value["comparison"].update({"raw_observed_fields_equal": False, comparison: False})
        accepts(entries + "_count_disagreement_is_observed", [stream(value)], value)
        value = deepcopy(equal)
        for token in ("launch_input", "actual_child_primary"):
            value[token]["facts"][entries] = []
            value[token]["facts"][count] = 0
        accepts(entries + "_both_empty_equal_is_observed", [stream(value)], value)
        value["comparison"].update({"raw_observed_fields_equal": False, comparison: False})
        rejects(entries + "_both_empty_cannot_compare_unequal", [stream(value)])
    value = deepcopy(equal)
    value["actual_child_primary"]["facts"]["user_attributes"] = 1
    rejects("user_attributes_differ_but_raw_user_equal", [stream(value)])
    value["comparison"].update({"raw_observed_fields_equal": False, "user_equal": False})
    accepts("user_attributes_disagreement_is_observed", [stream(value)], value)

    report = {"native": {"exit": 1}, "errors": [], "commands": [{"exit": 101}, {"exit": 1}]}
    RECORD(report, [stream(equal)])
    assert report["native"]["child_token_observation"]["observation_complete"] is True
    assert report["native"]["exit"] == 1 and [c["exit"] for c in report["commands"]] == [101, 1]
    passed.append({"name": "observation_preserves_original_nonzero_exits", "result": "PASS"})
    RECORD(report, [""])
    assert report["native"]["child_token_observation"]["status"] == "unknown"
    assert report["native"]["child_token_observation"]["observation_complete"] is False
    assert len(report["errors"]) == 1 and report["native"]["exit"] == 1
    passed.append({"name": "unknown_is_recorded_without_replacing_original_failure", "result": "PASS"})

    original = ROOT / "controls-original-e127"
    if original.is_dir():
        texts = [(original / f"native.{name}.log").read_text() for name in ("stdout", "stderr")]
        listing = json.loads((original / "selected-and-excluded.json").read_text())
        old = NATIVE["verify_native"](texts, listing)
        assert old["observation_complete"] is True and all(row[0] == "FAIL" for row in old["attempts"])
        rejects("original_e127_has_no_child_observation", texts)
        passed.append({"name": "original_e127_verifier_still_records_two_failures", "result": "PASS"})

    result = {"scope": "synthetic parser controls and optional archived-log parsing only",
              "native_runs": 0, "controls": passed, "passed": len(passed)}
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
