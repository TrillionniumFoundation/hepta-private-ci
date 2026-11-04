#!/usr/bin/env python3
"""Execute the committed candidate reader on the exact previously read XML/log."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import runpy
import xml.etree.ElementTree as ET

CANDIDATE_SHA = "cb977cd617c1426d2694c6fd4825dcabf860b7613a616b089521a582eab0cf0e"
SOURCE = "d6e18bbecd78e061785283eb3171729aded28367"

def require(value, message):
    if not value:
        raise RuntimeError(message)

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def main():
    require(__debug__, "optimized Python is not accepted")
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    candidate = Path(__file__).with_name("run_negative_candidate.py")
    candidate_raw = candidate.read_bytes()
    require(sha(candidate_raw) == CANDIDATE_SHA, "candidate source differs")
    raw_report = (args.evidence / "READBACK.json").read_bytes()
    require(len(raw_report) <= 128 * 1024, "original report exceeds bound")
    observed = json.loads(raw_report)
    require(observed["source"] == SOURCE and observed["artifact_id"] == 13298389026
            and observed["archive_sha256"] == "f2ecef472cb37e5909849330d7e72e317c7713d7aad8a34e148b1198e75c349a"
            and observed["original_receipt_status"] == "failed"
            and observed["all_six_members_crc_verified"] is True,
            "not the fixed original failed artifact")
    files = {}
    for name, expected in {
        "mutant-test.log": ("e05159953dd97ffeca2a5082937a056e8a32f7e1139bbb688f0935e02fd6e6f0", 1349),
        "mutant-test.xml": ("81a29987e3a11dff3b4288c6378ecd38936ac12b4c7e7113d7a1b33ac6a31abd", 1723),
    }.items():
        value = base64.b64decode(observed["exact_safe_files_base64"][name], validate=True)
        require((sha(value), len(value)) == expected, "original member identity differs")
        files[name] = value
    # This is our committed candidate reader, never source from the archived artifact.
    module = runpy.run_path(str(candidate), run_name="candidate_reader_replay")
    controls = module["reader_controls"]()
    xml_controls = module["xml_reader_controls"]()
    raw_rejection = module["validate_rejection"](files["mutant-test.log"])
    wrapper = module["validate_mutant_wrapper_xml"](files["mutant-test.xml"], files["mutant-test.log"])
    old_xml = ET.fromstring(files["mutant-test.xml"])
    old_suites = old_xml.findall("testsuite")
    old_cases = old_xml.findall(".//testcase")
    old_predicate = (len(old_suites) == 1 and len(old_cases) == 1
                    and old_suites[0].get("tests") == "1" and old_suites[0].get("failures") == "1"
                    and old_suites[0].get("errors") == "0" and old_cases[0].find("failure") is not None
                    and old_cases[0].find("skipped") is None and old_cases[0].find("error") is None)
    require(old_predicate is False, "old counter predicate unexpectedly accepts actual XML")
    result = {
        "schema": "hepta.env.original-xml.candidate-reader-replay.v1",
        "candidate_sha256": CANDIDATE_SHA, "original_source": SOURCE,
        "original_artifact_id": 13298389026,
        "original_job_and_receipt_still_failed": True,
        "actual_original_xml_old_predicate_accepted": False,
        "actual_original_xml_new_reader_accepted": True,
        "raw_rejection": raw_rejection, "wrapper": wrapper,
        "raw_reader_controls": controls, "xml_reader_controls": xml_controls,
        "native_rerun": False, "artifact_source_or_binaries_executed": False,
        "candidate_product_qualification": False,
        "native_full_original_suites_and_negative_control_still_required": True,
    }
    raw = (json.dumps(result, indent=2, sort_keys=True) + "\n").encode()
    require(len(raw) <= 32 * 1024, "replay output bound")
    (args.evidence / "CANDIDATE_XML_REPLAY.json").write_bytes(raw)
    print("CANDIDATE_XML_REPLAY_JSON=" + json.dumps(result, sort_keys=True), flush=True)

if __name__ == "__main__":
    main()
