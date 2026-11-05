import base64
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import struct
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
CI = ROOT.parent / "ci-audit/recovered-20261105"
FOLDER = CI / "app-parent-liveness-v2-complete-archive"
manifest = json.loads((FOLDER / "export-manifest.json").read_bytes())
author = json.loads((FOLDER / "strict-decoding-validation-v1.json").read_bytes())


def identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


def check(data, reference):
    actual = identity(data)
    for key in ("bytes", "sha256"):
        assert actual[key] == reference[key], (key, actual, reference)
    return actual


originals, checks = {}, []
for asset in manifest["assets"]:
    transport = json.loads((FOLDER / "transport" / (asset["name"] + ".transport.json")).read_bytes())
    assert transport["name"] == asset["name"]
    encoded = transport["base64"].encode("ascii")
    assert len(encoded) == asset["base64_bytes"]
    assert hashlib.sha256(encoded).hexdigest() == asset["base64_sha256"]
    offset = 0
    for part in asset["parts"]:
        assert part["offset"] == offset
        check(encoded[offset:offset + part["bytes"]], part)
        offset += part["bytes"]
    assert offset == len(encoded)
    compressed = base64.b64decode(encoded, validate=True)
    check(compressed, asset["gzip"])
    assert compressed[:2] == b"\x1f\x8b" and struct.unpack("<I", compressed[4:8])[0] == 0
    data = gzip.decompress(compressed)
    check(data, asset["original"])
    assert (FOLDER / "decoded-verified-v1" / asset["name"]).read_bytes() == data
    originals[asset["name"]] = data
    checks.append({"name": asset["name"], "native_encoded_parts": len(asset["parts"]),
                   "gzip": identity(compressed), "original": identity(data),
                   "strict_base64_gzip_crc_and_reopened_full_bytes": True})
wrapper = originals.pop("complete-small-originals.json")
for item in json.loads(wrapper)["files"]:
    data = item["content"].encode()
    check(data, item)
    if item["name"] in originals:
        assert originals[item["name"]] == data
    originals[item["name"]] = data
    decoded = FOLDER / "decoded-verified-v1" / item["name"]
    if not decoded.exists():
        decoded = FOLDER / "decoded-verified-v1/small" / item["name"]
    assert decoded.read_bytes() == data
assert len(originals) == manifest["original_unique_files_count"] == 156
assert {x["name"] for x in author["originals"]} == set(originals)
for item in author["originals"]:
    check(originals[item["name"]], item)

trace_reference = author["additional_owned_observer_original"]
trace = Path(trace_reference["path"]).read_bytes()
check(trace, trace_reference)
assert identity(trace)["blob"] == trace_reference["git_blob"]
events = [json.loads(line) for line in trace.splitlines()]
assert len(events) == trace_reference["jsonl_records"] == 169

phases = []
full_roster = None
for phase in manifest["tested_phase_sources"]:
    label = phase["label"]
    review = json.loads(originals[label + "-review.json"])
    catalog = json.loads(originals[label + "-catalog.stdout"])
    metadata = json.loads(originals[label + "-metadata.stdout"])
    assert len(metadata["workspace_members"]) == 193
    assert len(metadata["resolve"]["nodes"]) == 1501
    assert identity(originals[label + "-metadata.stdout"])["sha256"] == "3a53323eae920e2e53dcb3e334128a4aff63cfb51840793e9150d617d2c9ba18"
    roster = Counter((sid, name, case["ignored"]) for sid, suite in catalog["rust-suites"].items()
                     for name, case in suite["testcases"].items())
    eligible = sum(count for (_, _, ignored), count in roster.items() if not ignored)
    ignored = sum(count for (_, _, ignored), count in roster.items() if ignored)
    assert eligible == 19506 and ignored == 57 and len(catalog["rust-suites"]) == 363
    if full_roster is None:
        full_roster = roster
    assert roster == full_roster
    selected = Counter((sid, name) for sid, suite in catalog["rust-suites"].items()
                       for name, case in suite["testcases"].items()
                       if not case["ignored"] and case["filter-match"]["status"] == "matches")
    xml = ET.fromstring(originals[label + ".junit.xml"])
    actual = Counter((case.attrib["classname"], case.attrib["name"]) for case in xml.iter("testcase"))
    assert selected == actual == Counter((case["classname"], case["name"]) for case in review["cases"])
    assert review["source"] == phase["source"]
    assert review["helpers_before"] == review["helpers_after"] and len(review["helpers_before"]) == 33
    assert review["programs_before"] == review["programs_after"]
    assert review["retries"] == 0 and review["source_unchanged"] and review["full_workspace_graph_equal"]
    assert review["counts"] == phase["counts"]
    if label == "parent-liveness-final-eight":
        assert review["counts"] == {"PASS": 8} and review["exit_code"] == 0
        assert review["selection_valid"] is False
        assert review["early_return_notices"] == ["    skipping capability test: unprivileged user namespaces are unavailable"]
    else:
        assert review["counts"] == {"FAIL": 1} and review["exit_code"] == 100
    phases.append({"label": label, "source": review["source"], "counts": review["counts"],
                   "exit_code": review["exit_code"], "exact_selected_catalog_junit_review": True,
                   "stable_programs": len(review["programs_before"]), "stable_helpers": 33,
                   "full_metadata_members": 193, "full_metadata_nodes": 1501,
                   "full_catalog_eligible": eligible, "full_catalog_ignored": ignored,
                   "full_catalog_cases_identical_across_all_four_sources": True})
assert len(phases) == 4
assert manifest["terminal_source"] == "c6fbcfa0d1ba3b1556f601dc4ca3a7734328b9f7"
result = {"schema": "hepta-root-app-parent-liveness-v2-complete-original-review-v1",
          "job_id": manifest["original_job"], "source": manifest["terminal_source"],
          "native_export_manifest": identity((FOLDER / "export-manifest.json").read_bytes()),
          "author_validation": identity((FOLDER / "strict-decoding-validation-v1.json").read_bytes()),
          "original_export_files": 156, "additional_observer_file": 1, "total_original_files": 157,
          "total_original_bytes": sum(map(len, originals.values())) + len(trace),
          "small_originals_transport_wrapper": identity(wrapper), "strict_asset_checks": checks,
          "originals": [{"name": name, **identity(data)} for name, data in sorted(originals.items())],
          "owned_process_trace": {**identity(trace), "jsonl_records": len(events)}, "phases": phases,
          "causal_endpoint_review": "4a280b840e655c2a0f66c904a7cf6016b2c4a3a7",
          "positive_scope_review": "e409fcdd2d634fdfbb4697cec151286c30bc7c4c",
          "valid_counterfactuals": 3, "positive_junit_pass": 8, "positive_behavior_pass": 7,
          "capability_original_early_return": 1, "original_controller_exit_code_preserved": 1,
          "limits": ["Every byte was independently reconstructed and reopened; counts are original files, not independent runs.",
                     "Ignored owned support is not a standalone PASS; three negatives use two distinct parent case names.",
                     "The retained-capability original behavior is unqualified. Complete transport does not change the strict failure.",
                     "The actual narrow PF_EXITING-before-zombie interval is not claimed observed. Final platform and product gates remain open."]}
output = ROOT / "deliverables/fourth-app-parent-liveness-v2-complete-root-review.json"
output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"output": str(output), "review_identity": identity(output.read_bytes()),
                  "originals": 157, "original_bytes": result["total_original_bytes"], "phases": phases}, ensure_ascii=False))
