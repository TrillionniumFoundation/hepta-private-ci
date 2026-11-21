from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ZIP = ROOT / "originals" / "hcsn-n256-firststep-candidate-scipy17-repair-001.zip"
EXPECTED_ZIP_SHA256 = "6866e32f050cdd5e1b7cef7e4b60d771d325de48bd21582d3e61f20ed9209eb1"
EXPECTED_MEMBERS = {
    "ADMISSION.json", "CHILD.stderr", "CHILD.stdout", "COST.json",
    "END_CGROUP.json", "LAUNCH.json", "MANIFEST.json", "PREFLIGHT.json",
    "TERMINAL.json",
}


def main() -> None:
    manifest = json.loads((ROOT / "MANIFEST.json").read_text())
    for relative, expected in manifest["files"].items():
        payload = (ROOT / relative).read_bytes()
        assert len(payload) == expected["bytes"], relative
        assert hashlib.sha256(payload).hexdigest() == expected["sha256"], relative
    raw = ZIP.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == EXPECTED_ZIP_SHA256
    with zipfile.ZipFile(ZIP) as archive:
        assert set(archive.namelist()) == EXPECTED_MEMBERS
        assert archive.testzip() is None
        stderr = archive.read("CHILD.stderr").decode()
        cost = json.loads(archive.read("COST.json"))
        terminal = json.loads(archive.read("TERMINAL.json"))
        cgroup = json.loads(archive.read("END_CGROUP.json"))
    assert "ValueError: unrecognized csr_matrix constructor input" in stderr
    assert "((0.0," in stderr
    assert cost["returncode"] == 1 and cost["timed_out"] is False
    assert terminal["status"] == "RED" and terminal["child_started"] is True
    for level in cgroup["ancestor_cgroup_chain"][:2]:
        assert "oom 0" in level["fields"]["memory.events"]
        assert "oom_kill 0" in level["fields"]["memory.events"]
    review = json.loads((ROOT / "REVIEW.json").read_text())
    assert review["candidate_dynamic_steps_executed"] is None
    assert review["candidate_sparse_exponential_actions_executed"] is None
    assert review["qualification"] is False and review["all_closed"] is False
    print("PASS: SciPy 1.17 repair RED and UNKNOWN counters preserved")


if __name__ == "__main__":
    main()
