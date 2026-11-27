#!/usr/bin/env python3
"""Cross-bind three original JUnit files to raw nextest UUIDs and package identities."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

EXPECTED_ZIP_SHA = "b1787753805af121986af7e99be7c09e99aea1ef613ddb8c965de2bdd9a355ff"
PAIRS = [
    ("agentd-tests.json", "agentd-nextest.junit.xml", "codex-hepta-agentd", 6),
    ("agentd-qualification-profile-tests.json", "agentd-qualification-profile.junit.xml", "codex-hepta-agentd", 1),
    ("protocol-tests.json", "last-nextest.junit.xml", "codex-hepta-agent-protocol", 16),
]
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


def audit(path):
    raw_zip = path.read_bytes()
    assert len(raw_zip) == 1413095 and hashlib.sha256(raw_zip).hexdigest() == EXPECTED_ZIP_SHA
    rows, seen = [], set()
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None and len(archive.infolist()) == 42
        for receipt_name, xml_name, package, count in PAIRS:
            receipt_raw = archive.read(receipt_name)
            receipt = json.loads(receipt_raw)
            assert receipt["source_sha"] == receipt["tested_sha"] == "d0f6507e08f7f5c5855f5164d07c049a34d1a6d9"
            assert receipt["before"]["tree"] == receipt["after"]["tree"] == "658fa040046285116b1fd81b94ff8c96444072ad"
            assert receipt["status"] == "passed" and receipt["command_exit_code"] == 0
            command = receipt["command"]
            assert command.count("-p") == 1 and command[command.index("-p") + 1] == package
            raw = archive.read(receipt["log_file"])
            assert len(raw) == receipt["log_bytes"] and hashlib.sha256(raw).hexdigest() == receipt["log_sha256"]
            clean = ANSI.sub("", raw.decode())
            ids = re.findall(r"^\s*Nextest run ID ([0-9a-f-]{36}) with nextest profile: (\S+)\s*$", clean, re.M)
            assert len(ids) == 1 and ids[0][1] == "local"
            xml_raw = archive.read(xml_name)
            root = ET.fromstring(xml_raw)
            assert root.attrib["uuid"] == ids[0][0] and ids[0][0] not in seen
            seen.add(ids[0][0])
            assert int(root.attrib["tests"]) == count and root.attrib["failures"] == root.attrib["errors"] == "0"
            suites = root.findall("testsuite")
            assert len(suites) == 1 and suites[0].attrib["name"] == package
            assert int(suites[0].attrib["tests"]) == count
            assert all(suites[0].attrib[key] == "0" for key in ("disabled", "errors", "failures"))
            cases = suites[0].findall("testcase")
            assert len(cases) == count and all(case.attrib["classname"] == package for case in cases)
            raw_cases = re.findall(r"^\s*PASS\s+\[[^\]\n]+\]\s+(\S+)\s+(\S+)\s*$", clean, re.M)
            assert len(raw_cases) == count and all(binary == package for binary, _ in raw_cases)
            assert sorted(name for _, name in raw_cases) == sorted(case.attrib["name"] for case in cases)
            rows.append({"receipt": receipt_name, "receipt_identity": identity(receipt_raw), "raw_log": receipt["log_file"],
                         "raw_identity": identity(raw), "junit": xml_name, "junit_identity": identity(xml_raw),
                         "raw_and_junit_nextest_uuid": ids[0][0], "profile": ids[0][1],
                         "command_package_raw_binary_suite_and_classname": package, "matching_case_ids": count})
    return {"schema": "mem8.d0f.native-junit-crossbinding.addendum.v1",
            "status": "PASS_ORIGINAL_UUID_AND_BINARY_CROSSBINDING", "original_artifact": identity(raw_zip),
            "run_id": 43062473099, "job_id": 130668437204, "attempt": 1, "rows": rows,
            "new_native_execution": 0, "original_package_modified": False,
            "boundary": "Additive offline checks on the original three JUnit/raw pairs. No result or source byte changes."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.artifact), indent=2, sort_keys=True))
