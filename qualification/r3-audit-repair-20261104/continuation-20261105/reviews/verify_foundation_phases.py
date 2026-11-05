#!/usr/bin/env python3
"""Verify complete delivered phase originals against the frozen Foundation plan."""
import argparse
import base64
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
NATIVE = ROOT / "ci-audit/recovered-20261105/b16-ai395-foundation-v7-v2"
FROZEN = ROOT / "architecture-audit/b16-guarded-native-runner-20261105/original-ignored-catalog-v7/v7-candidate"


def identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "blob": hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()}


def clear_color(text):
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def originals(path):
    bundle = json.loads(path.read_bytes())
    result = {}
    for row in bundle["files"]:
        packed = base64.b64decode(row["data"], validate=True)
        assert len(packed) == row["compressed_bytes"]
        assert hashlib.sha256(packed).hexdigest() == row["compressed_sha256"]
        raw = gzip.decompress(packed)
        assert identity(raw) == {"bytes": row["bytes"], "sha256": row["sha256"], "blob": row["git_blob"]}
        assert row["path"] not in result
        result[row["path"]] = raw
    if "original_bytes" in bundle:
        assert sum(map(len, result.values())) == bundle["original_bytes"]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--through", type=int, required=True, choices=range(1, 11))
    args = parser.parse_args()
    epoch_bytes = (FROZEN / "epoch-foundation.json").read_bytes()
    assert identity(epoch_bytes)["blob"] == "6cc71ef831549fbe54f26c9bbe080e53effc59fa"
    epoch = json.loads(epoch_bytes)
    manifest = json.loads((FROZEN / "payload-manifest.json").read_bytes())
    operations = {op["id"]: op for op in epoch["operations"] if "id" in op}
    positives, negatives = Counter(), Counter()
    rows, restorations = [], []
    expected_previous_restore = None
    for number in range(1, args.through + 1):
        prefix = f"B{number:02}"
        labels = [label for label in operations if label.startswith(prefix + "_")]
        assert len(labels) == 1
        label = labels[0]
        operation = operations[label]
        bundle_path = NATIVE / (prefix + "-priority-bundle.json")
        files = originals(bundle_path)
        review = json.loads(files[label + "-review.json"])
        command = json.loads(files[label + "-command-terminal.json"])
        xml_bytes, raw = files[label + ".junit.xml"], files[label + ".log"]
        xml = ET.fromstring(xml_bytes)
        cases = xml.findall(".//testcase")
        expected = Counter((scope["package"], name) for scope in operation["scopes"] for name in scope["exact_names"])
        observed = Counter((case.attrib["classname"], case.attrib["name"]) for case in cases)
        assert observed == expected
        statuses = Counter("FAIL" if case.find("failure") is not None else
                           "ERROR" if case.find("error") is not None else
                           "SKIP" if case.find("skipped") is not None else "PASS" for case in cases)
        negative = operation["kind"] == "negative"
        assert statuses == {"FAIL" if negative else "PASS": sum(expected.values())}
        assert review["scope"] == operation["scopes"][0]
        assert review["source"] == command["source_before"]
        assert review["exit_code"] == command["exit_code"] == (100 if negative else 0)
        assert review["run_id"] == xml.attrib["uuid"] and review["selection_valid"]
        assert review["retries"] == 0 and review["early_return_observations"] == []
        assert review["source_unchanged"] and review["full_graph_equal"]
        assert review["programs_before"] == review["programs_after"]
        assert review["helpers_before"] == review["helpers_after"]
        assert len(review["programs_before"]) == 1 and len(review["helpers_before"]) == 33
        assert identity(raw)["sha256"] == review["raw"]["sha256"]
        assert identity(xml_bytes)["sha256"] == review["fresh_junit"]["sha256"]
        assert command["argv"][:2] == ["just", "test"]
        assert command["argv"].count("--retries") == 1
        assert command["argv"][command["argv"].index("--retries") + 1] == "0"
        assert "--run-ignored" not in command["argv"]
        if expected_previous_restore is not None and not operation["before"]:
            assert review["source"] == expected_previous_restore
        expected_previous_restore = None
        physical = None
        if negative:
            negatives.update(expected)
            proof = json.loads(files[label + "-physical-proof.json"])
            finally_receipt = json.loads(files[label + "-finally-receipt.json"])
            assert proof["source"] == review["source"]
            assert Counter(case["name"] for case in proof["cases"]) == Counter(name for _, name in expected)
            assert all(case["qualified"] for case in proof["cases"])
            assert finally_receipt["negative_tree"] == review["source"]
            assert finally_receipt["restoration"] == operation["restore"]
            assert finally_receipt["causal_gate_passed"] and finally_receipt["next_phase_permitted"]
            assert finally_receipt["primary_error"] is None and finally_receipt["restore_error"] is None
            applied = json.loads(files[operation["restore"] + "-applied.json"])
            assert applied["before_tree"] == review["source"]
            assert applied["after_tree"] == finally_receipt["restored_tree"]
            assert applied["delta"] == manifest["deltas"][operation["restore"]]
            by_name = {case["name"]: case for case in review["cases"]}
            for case in proof["cases"]:
                observed_case = by_name[case["name"]]
                captured = clear_color(observed_case["captured"])
                anchor = case["actual_panic_anchor"]
                suffix = anchor["path"].removeprefix("codex-rs/") + ":" + str(anchor["line"]) + ":"
                panic = captured.rfind(suffix)
                assert panic >= 0 and "assertion failed" in captured
                for marker in case["physical_markers"]:
                    assert marker in captured and captured.index(marker) < panic
                assert all("timeout" not in e["attributes"].get("type", "").lower() for e in observed_case["terminal_elements"])
                if case["kind"] == "barrier":
                    marker = "cancelled barrier: SQLite callback entered; replacement query_only=0, busy_timeout=7"
                    assert marker in captured and captured.index(marker) < panic
                    assert "intermediate query_only=OFF must not return to the pool" in captured
                if case["kind"] == "interlock":
                    assert "commit_interlock: commit_succeeded=true sqlite_code=None" in captured
                    assert '"531"' in captured and "<None" in captured
            expected_previous_restore = finally_receipt["restored_tree"]
            restorations.append(finally_receipt)
            physical = {"oracle": operation["scopes"][0]["oracle"], "case_count": len(proof["cases"]), "exact_restore": True}
        else:
            positives.update(expected)
            passed = Counter(re.findall(r"PASS\s+\[\s*[\d.]+s\]\s+(\S+)\s+(\S+)", clear_color(raw.decode())))
            assert passed == expected
            if label == "B03_R2d_final":
                assert b"replacement query_only=1, busy_timeout=5000" in raw
            if label == "B05_R2e1_final":
                assert b'commit_interlock: commit_succeeded=false sqlite_code=Some("531")' in raw
        rows.append({"phase": label, "source": review["source"], "uuid": review["run_id"],
                     "counts": dict(statuses), "negative": negative, "physical": physical,
                     "filtered": review["filtered_count"], "ignored": review["ignored_count"],
                     "raw": identity(raw), "junit": identity(xml_bytes), "bundle": identity(bundle_path.read_bytes()),
                     "original_files": len(files), "original_bytes": sum(map(len, files.values())),
                     "originals_verified": True, "programs_helpers_source_graph_stable": True})
    if args.through == 10:
        assert (len(positives), sum(positives.values()), len(negatives), sum(negatives.values()), len(restorations)) == (24, 27, 9, 10, 4)
    result = {"schema": "hepta-root-original-foundation-phase-review-v1", "recorded_utc": datetime.now(timezone.utc).isoformat(),
              "frozen_epoch": identity(epoch_bytes), "completed_phase_count": args.through,
              "positive_unique": len(positives), "positive_occurrences": sum(positives.values()),
              "negative_unique": len(negatives), "negative_occurrences": sum(negatives.values()),
              "exact_finally_restorations": len(restorations), "phases": rows, "restorations": restorations,
              "epoch_terminal_and_all_source_guards_required_separately": True,
              "foundation_qualified_by_this_partial_review": False, "B16_closed": False,
              "project_commands_executed": False}
    out = ROOT / "hepta-audit-fifth/inputs" / f"foundation-phase-review-through-{args.through:02}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(out), "identity": identity(out.read_bytes()),
                      "positive_occurrences": sum(positives.values()), "negative_occurrences": sum(negatives.values()),
                      "exact_restorations": len(restorations)}))


if __name__ == "__main__":
    main()
