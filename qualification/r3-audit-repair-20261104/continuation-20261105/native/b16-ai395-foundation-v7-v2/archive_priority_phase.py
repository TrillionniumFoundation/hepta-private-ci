#!/usr/bin/env python3
"""Freeze already-read native phase originals; this never invokes native commands."""
import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def identity(data):
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "git_blob": hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest(),
    }


def preserve(path, data):
    if path.exists():
        assert path.read_bytes() == data, f"immutable local original changed: {path}"
    else:
        path.write_bytes(data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase")
    ap.add_argument("--negative", action="store_true")
    a = ap.parse_args()
    root = Path(__file__).resolve().parent
    directory = root / (a.phase.split("_", 1)[0] + "-originals")
    captures = sorted(directory.glob("captured-native-files*.json"))
    assert captures
    originals = {}
    for capture in captures:
        for item in json.loads(capture.read_text())["files"]:
            name = Path(item["path"]).name
            data = item["text"].encode("utf-8")
            assert len(data) == item["size"]
            assert hashlib.sha256(data).hexdigest() == item["sha256"]
            assert item["eof"] is True
            if name in originals:
                assert originals[name][1] == data
            else:
                originals[name] = (item, data)
    files, pins = [], []
    for name, (item, data) in sorted(originals.items()):
        preserve(directory / name, data)
        pin = {"path": name, "original_native_path": item["path"],
               **identity(data), "version": item["version"]}
        pins.append(pin)
        packed = gzip.compress(data, mtime=0)
        assert gzip.decompress(packed) == data
        files.append({**pin, "encoding": "gzip+base64",
                      "compressed_bytes": len(packed),
                      "compressed_sha256": hashlib.sha256(packed).hexdigest(),
                      "data": base64.b64encode(packed).decode("ascii")})
    preserve(directory / "original-pins.json",
             (json.dumps(pins, indent=2, sort_keys=True) + "\n").encode())
    review = json.loads(originals[a.phase + "-review.json"][1])
    terminal = json.loads(originals[a.phase + "-command-terminal.json"][1])
    xml = ET.fromstring(originals[a.phase + ".junit.xml"][1])
    cases = xml.findall(".//testcase")
    assert review["selection_valid"] and review["retries"] == 0
    assert not review["early_return_observations"]
    assert review["source_unchanged"] and review["full_graph_equal"]
    assert review["programs_before"] == review["programs_after"]
    assert review["helpers_before"] == review["helpers_after"]
    assert len(cases) == sum(review["counts"].values())
    assert xml.attrib["uuid"] == review["run_id"]
    case_rows = [{"classname": c.attrib["classname"], "name": c.attrib["name"],
                  "status": "FAIL" if c.find("failure") is not None else
                            "ERROR" if c.find("error") is not None else
                            "SKIP" if c.find("skipped") is not None else "PASS"}
                 for c in cases]
    assert len({(r["classname"], r["name"]) for r in case_rows}) == len(case_rows)
    negative = None
    if a.negative:
        proof = json.loads(originals[a.phase + "-physical-proof.json"][1])
        restoration = json.loads(originals[a.phase + "-finally-receipt.json"][1])
        assert proof["source"] == review["source"]
        assert all(r["qualified"] for r in proof["cases"])
        assert sorted(r["name"] for r in proof["cases"]) == sorted(r["name"] for r in case_rows)
        assert all(r["status"] == "FAIL" for r in case_rows)
        assert restoration["causal_gate_passed"] is True
        assert restoration["primary_error"] is None and restoration["restore_error"] is None
        assert restoration["next_phase_permitted"] is True
        assert terminal["exit_code"] == 100
        negative = {"proof": proof, "finally": restoration}
    else:
        assert all(r["status"] == "PASS" for r in case_rows)
        assert terminal["exit_code"] == 0
    result = {
        "schema": "hepta-native-priority-evidence-v1",
        "host": "ai395", "job_id": "1a1ab493f2b-fc05-4bfe", "phase": a.phase,
        "source_tree": review["source"],
        "classification": "VALID_CAUSAL_NEGATIVE_WITH_EXACT_FINALLY_RESTORE" if a.negative else "SELECTED_CASES_PASS",
        "cases": case_rows, "counts": review["counts"], "test_retries": 0,
        "run_id": review["run_id"], "just_exit_code": terminal["exit_code"],
        "just_duration_seconds": terminal["duration_seconds"],
        "filtered_count": review["filtered_count"], "ignored_count": review["ignored_count"],
        "early_return_observations": [], "programs_stable": True, "helpers_stable": True,
        "negative": negative,
        "limits": ["Qualification is limited to the exact selected cases and original source.",
                   "Expected negative failures are causal evidence, not positive product PASS.",
                   "Original logs retain filtered/skipped tests and binaries outside the selected scope."],
        "archiver_identity": identity(Path(__file__).read_bytes()),
        "original_bytes": sum(p["bytes"] for p in pins), "files": files,
    }
    data = (json.dumps(result, indent=2, sort_keys=True) + "\n").encode()
    assert len(data) <= 512000
    output = root / (a.phase.split("_", 1)[0] + "-priority-bundle.json")
    preserve(output, data)
    info = {"path": str(output), **identity(data), "original_files": len(files),
            "original_bytes": result["original_bytes"]}
    preserve(output.with_suffix(".identity.json"),
             (json.dumps(info, indent=2, sort_keys=True) + "\n").encode())
    print(json.dumps(info))


if __name__ == "__main__":
    main()
