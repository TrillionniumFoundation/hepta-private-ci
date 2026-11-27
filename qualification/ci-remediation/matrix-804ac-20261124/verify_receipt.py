#!/usr/bin/env python3
"""Verify archived original CI bytes and actual unique case counts."""

import hashlib
import json
from pathlib import Path
import re
import zipfile


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def main():
    root = Path(__file__).resolve().parent
    receipt = json.loads((root / "receipt.json").read_text())
    archive = root / receipt["artifact"]["file"]
    data = archive.read_bytes()
    assert len(data) == receipt["artifact"]["bytes"]
    assert sha256(data) == receipt["artifact"]["sha256"]
    with zipfile.ZipFile(archive) as zf:
        expected_names = [member["name"] for member in receipt["verified_members"]]
        assert sorted(zf.namelist()) == sorted(expected_names)
        members = {name: zf.read(name) for name in expected_names}
    for member in receipt["verified_members"]:
        content = members[member["name"]]
        assert len(content) == member["bytes"], member["name"]
        assert sha256(content) == member["sha256"], member["name"]
    assert members["current-head.txt"].decode().strip() == receipt["head"]
    assert members["baseline-head.txt"].decode().strip() == receipt["baseline"]
    for name in ("baseline-create.log", "baseline-reopen.log", "upgrade.log", "upgraded-reopen.log"):
        assert b"fixture_verified=true" in members[name], name
    assert b"wrong_passphrase_rejected=true" in members["wrong-passphrase.log"]

    output = re.sub(r"\x1b\[[0-9;]*m", "", members["consumer-tests.log"].decode())
    passed = re.findall(r"^\s*PASS\s+\[[^\]]+\]\s+(\S+\s+\S+)\s*$", output, re.M)
    expected = receipt["consumer_cases"]
    assert len(passed) == len(set(passed)) == expected["unique_run"] == 78
    assert sorted(passed) == sorted(expected["passed_identities"])
    assert "78 tests run: 78 passed, 0 skipped" in output
    assert "[  23.544s]" in output
    print("PASS: original artifact, 12 member hashes, exact heads, migration markers, 78/78 unique tests")


if __name__ == "__main__":
    main()
