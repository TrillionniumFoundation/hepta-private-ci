from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ZIP = ROOT / "originals" / "hcsn-n256-firststep-candidate-oracle-compare-001.zip"
EXPECTED_ZIP_SHA256 = "a922989c369eddf6685f273334fcad5d02b464a1cec21607f98d9f1f400ccf0a"
EXPECTED_MEMBERS = {
    "ADMISSION.json",
    "CHILD.stderr",
    "CHILD.stdout",
    "COST.json",
    "END_CGROUP.json",
    "LAUNCH.json",
    "MANIFEST.json",
    "PREFLIGHT.json",
    "TERMINAL.json",
}


def main() -> None:
    manifest = json.loads((ROOT / "MANIFEST.json").read_text())
    for relative, expected in manifest["files"].items():
        path = ROOT / relative
        raw = path.read_bytes()
        assert len(raw) == expected["bytes"], relative
        assert hashlib.sha256(raw).hexdigest() == expected["sha256"], relative
    raw = ZIP.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == EXPECTED_ZIP_SHA256
    assert hashlib.sha256(raw).hexdigest() == EXPECTED_ZIP_SHA256
    with zipfile.ZipFile(ZIP) as archive:
        assert set(archive.namelist()) == EXPECTED_MEMBERS
        assert archive.testzip() is None
        terminal = json.loads(archive.read("TERMINAL.json"))
        cost = json.loads(archive.read("COST.json"))
        stderr = archive.read("CHILD.stderr").decode("utf-8")
        end_cgroup = json.loads(archive.read("END_CGROUP.json"))
    assert terminal["status"] == "RED"
    assert terminal["child_started"] is True
    assert terminal["all_closed"] is False
    assert cost["returncode"] == 1
    assert cost["timed_out"] is False
    assert "ValueError: unrecognized csr_matrix constructor input" in stderr
    assert "sparse_dynamic.py" in stderr
    for level in end_cgroup["ancestor_cgroup_chain"][:2]:
        events = level["fields"]["memory.events"]
        assert "oom 0" in events
        assert "oom_kill 0" in events
    review = json.loads((ROOT / "REVIEW.json").read_text())
    assert review["candidate_dynamic_steps_executed"] is None
    assert review["candidate_sparse_exponential_actions_executed"] is None
    assert review["qualification"] is False
    assert review["all_closed"] is False
    print("PASS: exact RED originals and UNKNOWN executed counters preserved")


if __name__ == "__main__":
    main()
