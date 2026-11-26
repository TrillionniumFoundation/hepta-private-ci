"""Validate bounded fixture/PSEC observations without changing the native verdict."""

import json
import re

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def keys(value, names):
    require(type(value) is dict and set(value) == set(names.split()), "unexpected observation fields")


def integer(value, low=0, high=0xFFFFFFFF):
    require(type(value) is int and low <= value <= high, "integer outside observation bound")


def boolean(value):
    require(type(value) is bool, "observation boolean has wrong type")


def unique_object(pairs):
    result = {}
    for name, value in pairs:
        require(name not in result, "duplicate observation JSON key")
        result[name] = value
    return result


def records(texts, marker, limit, count):
    result, total = [], 0
    prefix = marker + " "
    for text in texts:
        before_summary = re.split(r"(?m)^\s*Summary\s+\[", ANSI.sub("", text), maxsplit=1)[0]
        for line in before_summary.splitlines():
            if marker not in line:
                continue
            line = line.lstrip()
            total += len(line.encode("utf-8")) + 1
            require(line.startswith(prefix) and total <= limit, "malformed or oversized observation")
            result.append(json.loads(line[len(prefix):], object_pairs_hook=unique_object))
    require(len(result) == count, "missing or duplicate observation")
    return result


def verify_psec_support(texts):
    row, = records(texts, "HEPTA_PSEC_SUPPORT", 4096, 1)
    keys(row, "schema actor module_loaded module_load_win32_error exports query_support "
         "query_version module_release environment_create_calls environment_close_calls child_launch_calls")
    integer(row["schema"], 1, 1)
    require(row["actor"] == "parent_test_process", "unexpected support-query actor")
    for name in ("environment_create_calls", "environment_close_calls", "child_launch_calls"):
        integer(row[name], 0, 0)
    boolean(row["module_loaded"])
    if row["module_load_win32_error"] is not None:
        integer(row["module_load_win32_error"], -(2**31), 2**31 - 1)
    if not row["module_loaded"]:
        require(all(row[name] is None for name in ("exports", "query_support", "query_version", "module_release")),
                "unloaded module has queried facts")
        return row
    require(row["module_load_win32_error"] is None, "successful load has a failure code")
    exports = row["exports"]
    keys(exports, "query_support query_version create_presence_only close_presence_only")
    for value in exports.values():
        boolean(value)
    for name in ("query_support", "query_version"):
        value = row[name]
        require((value is not None) == exports[name], "symbol/query presence mismatch")
        if value is None:
            continue
        if name == "query_support":
            keys(value, "hresult flags_raw outputs_valid")
            integer(value["flags_raw"], 0, 2**64 - 1)
        else:
            keys(value, "hresult major_requested available_raw minor_raw outputs_valid")
            integer(value["major_requested"], 1, 1)
            integer(value["available_raw"], 0, 255)
            integer(value["minor_raw"])
        integer(value["hresult"], -(2**31), 2**31 - 1)
        boolean(value["outputs_valid"])
        expected = value["hresult"] == 0 and (name == "query_support" or value["available_raw"] <= 1)
        require(value["outputs_valid"] == expected, "query validity contradicts the raw return")
    release = row["module_release"]
    keys(release, "success win32_error")
    boolean(release["success"])
    if release["win32_error"] is not None:
        integer(release["win32_error"], -(2**31), 2**31 - 1)
    require(not release["success"] or release["win32_error"] is None,
            "successful module release has a failure code")
    return row


def verify_fixture_acl(texts):
    before, after = records(texts, "HEPTA_LEGACY_FIXTURE_ACL", 16 * 1024, 2)
    keys(before, "phase snapshot")
    keys(after, "phase snapshot same_owner_group exact_dacl_readback changed grant_subject "
         "grant_mask grant_inheritance scope")
    require(before["phase"] == "before_owned_fixture_grant"
            and after["phase"] == "after_owned_fixture_grant", "fixture grant phases changed")
    require(after["same_owner_group"] is True and after["exact_dacl_readback"] is True,
            "fixture byte/identity readback was not established")
    boolean(after["changed"])
    require(after["grant_subject"] == "parent_process_token_user"
            and after["scope"] == "fresh_owned_empty_fixture_only", "fixture authority scope changed")
    integer(after["grant_mask"], 0x1F01FF, 0x1F01FF)
    integer(after["grant_inheritance"], 3, 3)
    roles = {"parent_process_user", "world", "system", "administrators", "users",
             "authenticated_users", "creator_owner", "other"}
    for record in (before, after):
        value = record["snapshot"]
        keys(value, "state attributes sd_bytes sd_control dacl_null_pointer acl_bytes aces "
             "owner_class group_class owner_is_parent_process_user owner_is_parent_process_default_owner identity_reference")
        require(value["state"] == "present"
                and value["identity_reference"] == "parent_process_only_not_child_token",
                "fixture descriptor is unknown")
        integer(value["attributes"])
        require(value["attributes"] & 0x10 and not value["attributes"] & 0x400,
                "fixture is not a real directory")
        integer(value["sd_bytes"], 20, 65536)
        integer(value["sd_control"], 0, 65535)
        require(value["sd_control"] & 0x8004 == 0x8004 and value["dacl_null_pointer"] is False,
                "unexpected descriptor representation")
        integer(value["acl_bytes"], 8, min(value["sd_bytes"] - 20, 65535))
        for name in ("owner_class", "group_class"):
            require(type(value[name]) is str and value[name] in roles, "unknown identity role")
        for name in ("owner_is_parent_process_user", "owner_is_parent_process_default_owner"):
            boolean(value[name])
        require(value["owner_is_parent_process_user"] == (value["owner_class"] == "parent_process_user"),
                "owner role contradicts its exact-user comparison")
        aces = value["aces"]
        require(type(aces) is list and len(aces) <= 64, "invalid fixture ACE count")
        for ace in aces:
            keys(ace, "type flags bytes mask sid_class")
            integer(ace["type"], 0, 0)
            integer(ace["flags"], 0, 255)
            integer(ace["bytes"], 16, 65535)
            integer(ace["mask"])
            require(type(ace["sid_class"]) is str and ace["sid_class"] in roles, "unknown ACE identity")
        require(8 + sum(ace["bytes"] for ace in aces) <= value["acl_bytes"], "ACE bytes exceed DACL")
    for name in ("attributes", "owner_class", "group_class", "owner_is_parent_process_user",
                 "owner_is_parent_process_default_owner"):
        require(before["snapshot"][name] == after["snapshot"][name],
                "unchanged fixture identity contradicts visible facts")
    require(after["changed"] or before["snapshot"] == after["snapshot"],
            "unchanged raw descriptor contradicts visible fields")
    require(any(ace["sid_class"] == "parent_process_user" and ace["mask"] == 0x1F01FF
                and ace["flags"] == 3 for ace in after["snapshot"]["aces"]),
            "ordinary-user inheritable grant is absent")
    # Redacted roles cannot reconstruct raw SID bytes or full DACL equality.
    return [before, after]


def record_environment_observations(report, texts):
    for name, verify in (("fixture_acl", verify_fixture_acl), ("psec_support", verify_psec_support)):
        result = {"record_complete": False, "status": "unknown",
                  "production_confinement_qualified": False}
        report["native"][name + "_observation"] = result
        try:
            record = verify(texts)
            result.update({"record_complete": True, "status": "observed", "record": record})
            if name == "psec_support":
                support, version = record["query_support"], record["query_version"]
                result["support_flags_known"] = support is not None and support["outputs_valid"]
                result["version_result_known"] = version is not None and version["outputs_valid"]
                result["version_available"] = bool(version["available_raw"]) if result["version_result_known"] else None
                result["module_release_confirmed"] = record["module_release"] is not None and record["module_release"]["success"]
                result["module_file_identity_measured"] = False
                if not result["support_flags_known"] or not result["version_result_known"]:
                    result["status"] = "unavailable_or_unknown"
        except Exception as error:
            report["errors"].append(f"{name}-observation: {type(error).__name__}: {error}")
