from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ZIP = ROOT / "originals" / "hcsn-n256-firststep-candidate-listrow-repair-001.zip"
EXPECTED_ZIP_SHA256 = "6323e8494359b42e11639afd3033d90c7fa86bbb057b824aefae49799ecb4ef5"
EXPECTED_MEMBERS = {
    "ADMISSION.json", "CHILD.stderr", "CHILD.stdout", "COST.json",
    "END_CGROUP.json", "LAUNCH.json", "MANIFEST.json",
    "N256_CANDIDATE_WARM1.bin", "PREFLIGHT.json", "RESULT.json",
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
        result = json.loads(archive.read("RESULT.json"))
        cost = json.loads(archive.read("COST.json"))
        terminal = json.loads(archive.read("TERMINAL.json"))
        cgroup = json.loads(archive.read("END_CGROUP.json"))
        capsule = archive.read("N256_CANDIDATE_WARM1.bin")
    assert hashlib.sha256(capsule).hexdigest() == result["candidate_capsule_sha256"]
    assert result["candidate_dynamic_steps"] == 1
    assert result["candidate_sparse_exponential_actions"] == 2
    assert result["oracle_reexecutions"] == 0
    assert result["coordinate_comparisons"] == 69728
    assert result["coordinate_identity_equal"] is True
    assert result["bitwise_mismatch_coordinates"] == 1291
    assert result["candidate_oracle_bitwise_equal"] is False
    assert result["max_abs_error_hex"] == "0x1.0600000000000p-50"
    assert result["max_ulp_distance"] == 335
    assert result["qualification"] is False
    assert cost["returncode"] == 0 and cost["timed_out"] is False
    assert terminal["status"] == "RED" and terminal["child_started"] is True
    for level in cgroup["ancestor_cgroup_chain"][:2]:
        assert "oom 0" in level["fields"]["memory.events"]
        assert "oom_kill 0" in level["fields"]["memory.events"]
    review = json.loads((ROOT / "REVIEW.json").read_text())
    assert review["candidate_dynamic_steps_executed"] == 1
    assert review["candidate_sparse_exponential_actions_executed"] == 2
    assert review["qualification"] is False and review["all_closed"] is False
    print("PASS: N256 list-row strict bitwise RED originals preserved")


if __name__ == "__main__":
    main()
