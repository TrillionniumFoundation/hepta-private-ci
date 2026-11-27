#!/usr/bin/env python3
"""Check archived bytes and reported local qualification boundaries."""

import hashlib
import json
from pathlib import Path
import zipfile


def main():
    root = Path(__file__).resolve().parent
    receipt = json.loads((root / "receipt.json").read_text())
    archive = receipt["archive"]
    data = (root / archive["file"]).read_bytes()
    assert len(data) == archive["bytes"]
    assert hashlib.sha256(data).hexdigest() == archive["sha256"]
    with zipfile.ZipFile(root / archive["file"]) as zf:
        names = [member["name"] for member in archive["members"]]
        assert sorted(zf.namelist()) == sorted(names)
        logs = {name: zf.read(name) for name in names}
    for member in archive["members"]:
        content = logs[member["name"]]
        assert len(content) == member["bytes"]
        assert hashlib.sha256(content).hexdigest() == member["sha256"]
    final = logs["state-index-tests-final.log"].decode()
    assert "2 tests run: 2 passed, 214 skipped" in final
    for case in receipt["tests"]["final_cases"]:
        assert case in final
    assert b"could not compile" in logs["state-index-tests.log"]
    assert b"database is locked" in logs["state-index-tests-corrected.log"]
    for name in ("state-index-fix.log", "state-index-clippy.log"):
        assert b"Finished `dev` profile" in logs[name]
    summary = None
    for line in logs["cargo-deny-resumed.stderr"].decode().splitlines():
        item = json.loads(line)
        if item.get("type") == "summary":
            summary = item["fields"]
    assert summary == receipt["cargo_deny"]["summary"]
    assert all(section["errors"] == 0 for section in summary.values())
    print("PASS: archived attempts, 2 selected state cases, lint completions, four audit classes")


if __name__ == "__main__":
    main()
