#!/usr/bin/env python3
"""Independently verify delivered native/CI evidence; never run project code."""
import base64
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parent.parent
CI = ROOT / "research-audit/published-5b633-ci-20261105"
NATIVE = ROOT / "ci-audit/recovered-20261105/b16-ai395-foundation-v7-v2"


def identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "blob": hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()}


def junit(data):
    xml = ET.fromstring(data)
    rows = xml.findall(".//testcase")
    assert not any(row.find(tag) is not None for row in rows for tag in ("failure", "error", "skipped"))
    return Counter((row.attrib.get("classname", ""), row.attrib["name"]) for row in rows), xml


def terminal_text(data):
    # Preserve original bytes; remove only terminal SGR color markup for matching.
    return re.sub(r"\x1b\[[0-9;]*m", "", data.decode())


def log_cases(data):
    return Counter(re.findall(r"PASS\s+\[\s*[\d.]+s\]\s+(\S+)\s+(\S+)", terminal_text(data)))


def zip_members(path, expected):
    raw = path.read_bytes()
    assert len(raw) == expected["bytes"] and hashlib.sha256(raw).hexdigest() == expected["sha256"]
    rows = expected["members"]
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == len(rows) == len(set(archive.namelist()))
        assert set(archive.namelist()) == {row["name"] for row in rows}
        result = {name: archive.read(name) for name in archive.namelist()}
        for row in rows:
            data = result[row["name"]]
            assert len(data) == row["bytes"] and hashlib.sha256(data).hexdigest() == row["sha256"]
    return result


def main():
    report = {"schema": "hepta-root-latest-original-scope-verification-v1",
              "recorded_utc": datetime.now(timezone.utc).isoformat(), "project_commands_executed": False}
    bundle = json.loads((NATIVE / "B01-priority-bundle.json").read_bytes())
    originals = {}
    for row in bundle["files"]:
        packed = base64.b64decode(row["data"], validate=True)
        assert len(packed) == row["compressed_bytes"]
        assert hashlib.sha256(packed).hexdigest() == row["compressed_sha256"]
        data = gzip.decompress(packed)
        assert identity(data) == {"bytes": row["bytes"], "sha256": row["sha256"], "blob": row["git_blob"]}
        assert data == (NATIVE / "B01-originals" / row["path"]).read_bytes()
        assert row["path"] not in originals
        originals[row["path"]] = data
    assert len(originals) == 5 and sum(map(len, originals.values())) == 47911
    review = json.loads(originals["B01_R2c_V3-review.json"])
    selected, xml = junit(originals["B01_R2c_V3.junit.xml"])
    expected = Counter(("codex-state", name) for name in review["scope"]["exact_names"])
    assert selected == expected == log_cases(originals["B01_R2c_V3.log"])
    assert sum(selected.values()) == 4 and xml.attrib["uuid"] == review["run_id"]
    assert review["programs_before"] == review["programs_after"] and len(review["programs_before"]) == 1
    assert review["helpers_before"] == review["helpers_after"] and len(review["helpers_before"]) == 33
    assert review["exit_code"] == review["retries"] == 0 and review["early_return_observations"] == []
    assert review["source_unchanged"] and review["full_graph_equal"]
    assert b"216 tests and 362 binaries skipped" in originals["B01_R2c_V3.log"]
    assert b"commit_gate_runtime: sqlite_version=3.51.3" in originals["B01_R2c_V3.log"]
    report["native_first_foundation_scope"] = {
        "bundle": identity((NATIVE / "B01-priority-bundle.json").read_bytes()),
        "originals": len(originals), "original_bytes": sum(map(len, originals.values())),
        "source": review["source"], "run_id": review["run_id"], "passed": 4, "retries": 0,
        "filtered_cases": 216, "unselected_binaries": 362, "programs_and_helpers_stable": True,
        "source_and_graph_unchanged": True, "foundation_complete": False, "B16_closed": False}

    ci_review_path = CI / "immutable-v5-business-retained/business-retained-original-review.json"
    ci_review = json.loads(ci_review_path.read_bytes())
    business_review = json.loads((CI / "snapshot-0017/windows-business-artifact-review.json").read_bytes())
    business = zip_members(CI / "snapshot-0017/windows-business-artifact-13406786835.zip", business_review)
    business_names = Counter()
    target_counts = {}
    for name, data in business.items():
        if name.endswith("/test.log"):
            names = re.findall(r"^test (\S+) \.\.\. ok\r?$", data.decode(), flags=re.M)
            business_names.update(names)
            target_counts[name] = len(names)
        elif name.endswith("/test.xml"):
            wrappers, _ = junit(data)
            assert sum(wrappers.values()) == 1
    assert sorted(target_counts.values()) == [19, 21, 78]
    assert sum(business_names.values()) == 118
    business_source = json.loads(business["ordinary-consumers/source.json"])
    assert business_source["head"] == "9063c52a063b6f26c48e9418f6d8dbd14e9e06ff"
    assert business_source["parents"] == ["63652be658ebed8d3052eb789b951793384fd5e4", "5b6331250ff459033bd44d1a95daec70131277cc"]
    assert business_source["tree"] == "b26598d0d97d8d51e723bb5582137315f2174d35"
    retained_review = json.loads((CI / "retained-artifact-review.json").read_bytes())
    retained = zip_members(CI / "retained-artifact-13406928365.zip", retained_review)
    retained_names, retained_xml = junit(retained["junit-0.xml"])
    assert retained_names == log_cases(retained["native-library.log"])
    assert sum(retained_names.values()) == 532
    class_counts = Counter()
    for (classname, _), count in retained_names.items():
        class_counts[classname] += count
    assert class_counts == {"codex-hepta-memory": 299, "codex-state": 209, "codex-utils-path": 24}
    assert "7 skipped" in terminal_text(retained["native-library.log"])
    retained_source = json.loads(retained["source.json"])
    assert retained_source["source_head"] == "5b6331250ff459033bd44d1a95daec70131277cc"
    assert retained_source["source_tree"] == business_source["tree"]
    original_catalog = json.loads((ROOT / "research-audit/next-head-ci-plan-20261105/named-exit-cases.json").read_bytes())
    old_names = {row["test"] for row in original_catalog["cases"]}
    assert len(original_catalog["cases"]) == 142
    assert not (old_names & set(business_names))
    assert not (old_names & {name for _, name in retained_names})
    private = ["private_state_windows::directory::tests::rejects_ancestor_substitution_at_retained_open",
               "private_state_windows::directory::tests::rejects_junction_before_creating_private_leaf"]
    assert all(retained_names[("codex-utils-path", name)] == 1 for name in private)
    report["windows_ci_scopes"] = {
        "full_projection": identity(ci_review_path.read_bytes()), "business_zip": identity((CI / "snapshot-0017/windows-business-artifact-13406786835.zip").read_bytes()),
        "retained_zip": identity((CI / "retained-artifact-13406928365.zip").read_bytes()),
        "zip_members_verified": [10, 4], "business_named_log_passes": 118, "business_wrapper_xml_nodes": 3,
        "retained_executed_xml_and_log_passes": 532, "retained_class_counts": dict(class_counts),
        "retained_additional_unnamed_skips": 7, "original_142_new_matches": 0,
        "same_head_private_directory_controls": private, "original_23_status_changed": False}
    report["limits"] = ["Native foundation first scope is a distinct B source from the GitHub A product head.",
                        "No native epoch or original blocker closure is inferred from partial positives.",
                        "Windows working-tree lock byte encodings require their own identity comparison; tree equality is not an unqualified byte-equality claim."]
    out = ROOT / "hepta-audit-fifth/inputs/latest-scopes-root-review.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"report": str(out), "identity": identity(out.read_bytes()), "native_first_passes": 4, "windows_passes_by_distinct_scope": [118, 532], "original_142_matches": 0}))


if __name__ == "__main__":
    main()
