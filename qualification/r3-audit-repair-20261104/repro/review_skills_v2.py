import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent
CI = ROOT.parent / "ci-audit/recovered-20261105"


def identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "blob": hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()}


def unpack(path, expected):
    data = path.read_bytes()
    assert identity(data)["blob"] == expected
    bundle = json.loads(data)
    files = {}
    records = []
    for entry in bundle["files"]:
        name = entry.get("name", Path(entry["path"]).name)
        body = entry["content"].encode()
        record = identity(body)
        assert record["bytes"] == entry["bytes"] and record["sha256"] == entry["sha256"]
        assert name not in files
        files[name] = body
        records.append({"name": name, **record})
    return bundle, files, records, identity(data)


invalid, old, old_records, old_identity = unpack(CI / "skills-invalid-negative-original.json", "92b497559c315c0cc48db5a8d7f3de89470a2158")
valid, files, records, bundle_identity = unpack(CI / "skills-v2-causal-original-nine-phase.json", "df61b67369e67f7f697dd80cb9810f476c01829b")
assert len(old) == 5 and len(files) == 8
invalid_proof = json.loads(old["skills-causal-negative.json"])
assert not invalid_proof["qualified"] and "425:11" in invalid_proof["case"]["failure"]
assert "index not found" in invalid_proof["case"]["failure"]
assert json.loads(old["skills-negative-finally-restore.json"])["restored_exact_positive"]
proof = json.loads(files["skills-causal-negative.json"])
restore = json.loads(files["skills-negative-finally-restore.json"])
negative = json.loads(files["skills-marker-negative-review.json"])
positive = json.loads(files["skills-original-nine-review.json"])
assert negative["source"] == "59fa1100c2ad24328e7841611092132ca08942ad"
assert positive["source"] == "51673d30d34674faeac6bb17e565fc9d04aec8f1"
assert negative["exit_code"] == 100 and len(negative["cases"]) == 1
assert positive["exit_code"] == 0 and len(positive["cases"]) == 9
assert all(c["result"] == "PASS" for c in positive["cases"])
for prefix, review in (("skills-marker-negative", negative), ("skills-original-nine", positive)):
    assert review["retries"] == 0 and review["original_ignored_count"] == 0
    assert review["early_return_notices"] == [] and review["exact_roster"]
    assert review["programs_before"] == review["programs_after"] and len(review["programs_before"]) == 1
    assert review["helpers_before"] == review["helpers_after"] == []
    assert identity(files[prefix + ".log"])["sha256"] == review["raw"]["sha256"]
    assert identity(files[prefix + ".junit.xml"])["sha256"] == review["fresh_junit"]["sha256"]
    xml = ElementTree.fromstring(files[prefix + ".junit.xml"])
    observed = [(x.attrib["classname"], x.attrib["name"], "FAIL" if x.find("failure") is not None else "ERROR" if x.find("error") is not None else "SKIP" if x.find("skipped") is not None else "PASS") for x in xml.iter("testcase")]
    assert sorted(observed) == sorted((c["classname"], c["name"], c["result"]) for c in review["cases"])
    raw = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", files[prefix + ".log"].decode())
    assert not re.search(r"\bskipping\b", raw, re.I)
    for case in review["cases"]:
        assert case["name"] in raw
manifest = json.loads((CI / "full18-three-repairs-manifest-v3.json").read_bytes())
expected = manifest["scopes"][1]["expected_cases"]
expected_pairs = sorted((x["classname"], x["name"]) for x in expected)
assert expected_pairs == sorted((x["classname"], x["name"]) for x in positive["cases"])
failure = negative["cases"][0]["failure"]
assert "ext/skills/src/host_roots_tests.rs:446:5:" in failure
diff = failure.split("Diff < left / right >", 1)[1].split("\n\n", 1)[0]
left = [line for line in diff.splitlines() if not line.lstrip().startswith(">")]
paths = re.findall(r'"([^"\n]+/\.agents/skills)"', "\n".join(left))
added = re.findall(r'"([^"\n]+/\.agents/skills)"', "\n".join(line for line in left if line.lstrip().startswith("<")))
assert len(paths) == 2 and paths[0].endswith("/outer/.agents/skills")
outer = paths[0][:-len("/.agents/skills")]
assert paths == [outer + "/.agents/skills", outer + "/nested/inner/.agents/skills"]
assert added == [paths[0]]
assert proof["qualified"] and proof["actual_left_vector_paths"] == paths and proof["added_left_paths"] == added
assert restore["restored_exact_positive"] and restore["original_exception"] is None and restore["restoration_exception"] is None
assert restore["actual_source_at_return"] == positive["source"]
report = {
    "schema": "hepta.root.skills-fixture-v2-causal-original-nine-review.v1",
    "observed_at_utc": datetime.now(timezone.utc).isoformat(),
    "status": "VALID_REAL_MARKER_NEGATIVE_AND_NINE_ORIGINAL_TESTS_PASS",
    "invalid_first_fixture_attempt": {"bundle": old_identity, "all_five_files_verified": old_records,
        "actual_failure": invalid_proof["case"], "qualified": False,
        "cause": "New test fixture indexed a missing key in an empty toml::Value. Both positive and negative variants needed Table.insert; the preparation panic never counted as causal evidence."},
    "valid_second_source_epoch": {"bundle": bundle_identity, "all_eight_files_verified": records,
        "native_job": valid["native_job"], "negative_tree": negative["source"], "positive_tree": positive["source"],
        "negative_case": negative["cases"][0], "actual_left_paths": paths, "added_left_paths": added,
        "restore": restore, "original_nine_cases": positive["cases"], "original_nine_names_match_frozen_roster": True,
        "raw_and_fresh_junit_agree": True, "retries": 0, "ignored": 0,
        "filter_unmatched_negative": 144, "filter_unmatched_positive": 136,
        "one_program_stable_in_each_source_epoch": True, "catalog_helpers_in_this_unit_scope": 0,
        "early_return_notices": []},
    "limits_zh": "仅原host_roots九项与真实marker负控的同源范围通过，不是整个145项package、最终完整workspace或跨平台通过。整体三修复job仍继续迁移和V8；首次无效准备失败不删除，也不计为有效负控。",
    "all_original_blockers_closed": False,
}
destination = ROOT / "deliverables/fourth-skills-v2-root-review.json"
destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"path": str(destination), **identity(destination.read_bytes()), "valid_negative": True, "original_passes": 9}))
