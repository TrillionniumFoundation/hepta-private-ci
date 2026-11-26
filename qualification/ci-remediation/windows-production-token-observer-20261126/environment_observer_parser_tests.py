"""Synthetic artifact consistency controls; no module load, subprocess or native test."""

from copy import deepcopy
import json

from environment_observer_parser import record_environment_observations
from environment_observer_parser import verify_fixture_acl
from environment_observer_parser import verify_psec_support


def psec_sample():
    return {
        "schema": 1, "actor": "parent_test_process", "module_loaded": True,
        "module_load_win32_error": None,
        "exports": {"query_support": True, "query_version": True,
                    "create_presence_only": True, "close_presence_only": True},
        "query_support": {"hresult": 0, "flags_raw": 15, "outputs_valid": True},
        "query_version": {"hresult": 0, "major_requested": 1, "available_raw": 1,
                          "minor_raw": 1, "outputs_valid": True},
        "module_release": {"success": True, "win32_error": None},
        "environment_create_calls": 0, "environment_close_calls": 0, "child_launch_calls": 0,
    }


def acl_sample():
    before = {
        "state": "present", "attributes": 16, "sd_bytes": 144, "sd_control": 0x8004,
        "dacl_null_pointer": False, "acl_bytes": 32,
        "aces": [{"type": 0, "flags": 3, "bytes": 24, "mask": 0x1F01FF, "sid_class": "system"}],
        "owner_class": "administrators", "group_class": "other",
        "owner_is_parent_process_user": False, "owner_is_parent_process_default_owner": True,
        "identity_reference": "parent_process_only_not_child_token",
    }
    after = deepcopy(before)
    after.update(sd_bytes=172, acl_bytes=60)
    after["aces"].insert(0, {"type": 0, "flags": 3, "bytes": 28,
                           "mask": 0x1F01FF, "sid_class": "parent_process_user"})
    return [{"phase": "before_owned_fixture_grant", "snapshot": before},
            {"phase": "after_owned_fixture_grant", "snapshot": after,
             "same_owner_group": True, "exact_dacl_readback": True, "changed": True,
             "grant_subject": "parent_process_token_user", "grant_mask": 0x1F01FF,
             "grant_inheritance": 3, "scope": "fresh_owned_empty_fixture_only"}]


def stream(marker, rows):
    return "".join(marker + " " + json.dumps(row, separators=(",", ":")) + "\n" for row in rows)


def main():
    passed = []

    def accepts(name, verify, texts, value):
        assert verify(texts) == value, name
        passed.append({"name": name, "expected": "accepted", "result": "PASS"})

    def rejects(name, verify, texts):
        try:
            verify(texts)
        except (ValueError, KeyError, TypeError, RecursionError):
            passed.append({"name": name, "expected": "rejected", "result": "PASS"})
        else:
            raise AssertionError(name + " was incorrectly accepted")

    marker = "HEPTA_PSEC_SUPPORT"
    row = psec_sample()
    accepts("psec_complete_queries", verify_psec_support, [stream(marker, [row])], row)
    failed_load = deepcopy(row)
    failed_load.update(module_loaded=False, module_load_win32_error=126, exports=None,
                       query_support=None, query_version=None, module_release=None)
    accepts("psec_missing_dll_is_observed_unavailable", verify_psec_support,
            [stream(marker, [failed_load])], failed_load)
    missing_exports = deepcopy(row)
    missing_exports["exports"].update(query_support=False, query_version=False)
    missing_exports.update(query_support=None, query_version=None)
    accepts("psec_missing_queries_are_observed_unknown", verify_psec_support,
            [stream(marker, [missing_exports])], missing_exports)
    for name in ("query_support", "query_version"):
        value = deepcopy(row)
        value[name].update(hresult=-2147467259, outputs_valid=False)
        accepts(name + "_failure_keeps_raw_outputs_unknown", verify_psec_support,
                [stream(marker, [value])], value)
        value[name]["outputs_valid"] = True
        rejects(name + "_failure_cannot_be_valid", verify_psec_support, [stream(marker, [value])])
        value = deepcopy(row)
        value[name]["outputs_valid"] = False
        rejects(name + "_success_cannot_be_invalid", verify_psec_support, [stream(marker, [value])])
    unavailable = deepcopy(row)
    unavailable["query_version"]["available_raw"] = 0
    accepts("version_unavailable_is_not_an_error", verify_psec_support,
            [stream(marker, [unavailable])], unavailable)
    value = deepcopy(row)
    value["query_version"].update(available_raw=2, outputs_valid=False)
    accepts("invalid_boolean_output_remains_unknown", verify_psec_support, [stream(marker, [value])], value)
    value["query_version"]["outputs_valid"] = True
    rejects("invalid_boolean_cannot_be_known", verify_psec_support, [stream(marker, [value])])
    value = deepcopy(row)
    value["query_support"]["flags_raw"] = 2**63
    accepts("unknown_support_bits_retained_without_interpretation", verify_psec_support,
            [stream(marker, [value])], value)
    value = deepcopy(row)
    value["module_release"].update(success=False, win32_error=6)
    accepts("failed_module_release_is_preserved", verify_psec_support, [stream(marker, [value])], value)
    for name, mutate in (
        ("wrong_actor", lambda v: v.update(actor="restricted_child")),
        ("module_loaded_boolean_type", lambda v: v.update(module_loaded=1)),
        ("created_environment", lambda v: v.update(environment_create_calls=1)),
        ("closed_environment", lambda v: v.update(environment_close_calls=1)),
        ("launched_child", lambda v: v.update(child_launch_calls=1)),
        ("negative_flags", lambda v: v["query_support"].update(flags_raw=-1)),
        ("u64_overflow", lambda v: v["query_support"].update(flags_raw=2**64)),
        ("boolean_hresult", lambda v: v["query_support"].update(hresult=False)),
        ("symbol_query_mismatch", lambda v: v["exports"].update(query_support=False)),
        ("missing_successful_query", lambda v: v.update(query_version=None)),
        ("release_success_error", lambda v: v["module_release"].update(win32_error=6)),
        ("missing_release", lambda v: v.update(module_release=None)),
        ("load_success_error", lambda v: v.update(module_load_win32_error=5)),
        ("unknown_extra_field", lambda v: v.update(raw_sid="not collected")),
    ):
        value = deepcopy(row); mutate(value)
        rejects("psec_" + name, verify_psec_support, [stream(marker, [value])])
    value = deepcopy(failed_load); value["exports"] = row["exports"]
    rejects("unloaded_module_cannot_have_exports", verify_psec_support, [stream(marker, [value])])

    acl_marker = "HEPTA_LEGACY_FIXTURE_ACL"
    acl = acl_sample()
    accepts("acl_complete_original_and_new_snapshot", verify_fixture_acl, [stream(acl_marker, acl)], acl)
    same = deepcopy(acl); same[0]["snapshot"] = deepcopy(same[1]["snapshot"]); same[1]["changed"] = False
    accepts("already_present_grant_with_equal_descriptor", verify_fixture_acl, [stream(acl_marker, same)], same)
    for name, mutate in (
        ("wrong_phase_order", lambda v: v.reverse()),
        ("wrong_subject", lambda v: v[1].update(grant_subject="world")),
        ("wrong_scope", lambda v: v[1].update(scope="existing_root")),
        ("wrong_mask", lambda v: v[1].update(grant_mask=0x1200A9)),
        ("not_inheritable", lambda v: v[1].update(grant_inheritance=0)),
        ("no_exact_readback", lambda v: v[1].update(exact_dacl_readback=False)),
        ("owner_raw_changed", lambda v: v[1].update(same_owner_group=False)),
        ("owner_visible_changed", lambda v: v[1]["snapshot"].update(owner_class="system")),
        ("group_visible_changed", lambda v: v[1]["snapshot"].update(group_class="system")),
        ("attributes_visible_changed", lambda v: v[1]["snapshot"].update(attributes=48)),
        ("false_unchanged_raw_claim", lambda v: v[1].update(changed=False)),
        ("reparse_root", lambda v: v[0]["snapshot"].update(attributes=0x410)),
        ("null_dacl", lambda v: v[0]["snapshot"].update(dacl_null_pointer=True)),
        ("deny_ace", lambda v: v[0]["snapshot"]["aces"][0].update(type=1)),
        ("before_dacl_present_bit_absent", lambda v: v[0]["snapshot"].update(sd_control=0x8000)),
        ("after_dacl_present_bit_absent", lambda v: v[1]["snapshot"].update(sd_control=0x8000)),
        ("before_acl_excludes_sd_header", lambda v: v[0]["snapshot"].update(sd_bytes=v[0]["snapshot"]["acl_bytes"])),
        ("after_acl_excludes_sd_header", lambda v: v[1]["snapshot"].update(sd_bytes=v[1]["snapshot"]["acl_bytes"])),
        ("missing_user_grant", lambda v: v[1]["snapshot"]["aces"][0].update(sid_class="authenticated_users")),
        ("user_grant_not_inherited", lambda v: v[1]["snapshot"]["aces"][0].update(flags=0)),
        ("user_grant_missing_delete", lambda v: v[1]["snapshot"]["aces"][0].update(mask=0x1E01FF)),
        ("ace_extent_overflow", lambda v: v[1]["snapshot"].update(acl_bytes=59)),
        ("owner_comparison_contradiction", lambda v: v[0]["snapshot"].update(owner_is_parent_process_user=True)),
    ):
        value = deepcopy(acl); mutate(value)
        rejects("acl_" + name, verify_fixture_acl, [stream(acl_marker, value)])

    for prefix, verify, sample, limit in ((marker, verify_psec_support, [row], 4096),
                                         (acl_marker, verify_fixture_acl, acl, 16384)):
        raw = stream(prefix, sample)
        rejects(prefix + "_missing", verify, [""])
        rejects(prefix + "_duplicate_streams", verify, [raw, raw])
        rejects(prefix + "_malformed", verify, [prefix + " {broken}\n"])
        rejects(prefix + "_oversized", verify, [prefix + " " * limit + "{}\n"])
        rejects(prefix + "_duplicate_key", verify, [raw.replace('"', '"duplicate":0,"duplicate":1,"', 1)])
        rejects(prefix + "_foreign_prefix", verify, ["unexpected " + raw])
        value = sample[0] if verify == verify_psec_support else sample
        accepts(prefix + "_summary_recap_ignored", verify,
                [raw + "Summary [0.1s] 2 tests run: 2 failed\n" + raw], value)
        rejects(prefix + "_only_recap", verify, ["Summary [0.1s] 2 tests run: 2 failed\n" + raw])

    report = {"native": {"exit": 1}, "errors": [], "commands": [{"exit": 101}, {"exit": 1}]}
    record_environment_observations(report, [stream(acl_marker, acl), stream(marker, [failed_load])])
    psec = report["native"]["psec_support_observation"]
    assert psec["record_complete"] is True and psec["status"] == "unavailable_or_unknown"
    assert psec["support_flags_known"] is False and psec["version_available"] is None
    assert not report["errors"] and report["native"]["exit"] == 1
    assert [command["exit"] for command in report["commands"]] == [101, 1]
    assert report["native"]["fixture_acl_observation"]["production_confinement_qualified"] is False
    passed.append({"name": "unavailable_support_preserves_original_failure", "result": "PASS"})
    record_environment_observations(report, [""])
    assert len(report["errors"]) == 2 and report["native"]["exit"] == 1
    assert all(not report["native"][name]["record_complete"]
               for name in ("fixture_acl_observation", "psec_support_observation"))
    passed.append({"name": "missing_records_keep_unknown_and_original_exit", "result": "PASS"})
    print(json.dumps({"scope": "synthetic artifact parser controls only", "native_runs": 0,
                      "passed": len(passed), "controls": passed}, indent=2))


if __name__ == "__main__":
    main()
