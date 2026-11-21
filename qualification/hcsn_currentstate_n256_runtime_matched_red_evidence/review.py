"""Zero-numerical-call verification of the immutable RED artifact."""

import hashlib
import json
import sys
import zipfile
from pathlib import Path


EXPECTED_ZIP_SHA256 = "f771fd19571843efed7e99583122f2f5ca4288b7f2f93d62d1d8318f14f00666"
EXPECTED_MEMBERS = {
    "ADMISSION.json": (3785, "eaff5dcb0bfe1742f870e93f1ab34a5c18320e1d090837b4960fefa9c85e127a"),
    "CANDIDATE.bin": (560358, "33ee695bfc001ca9bb5555befe384e0dee60e49be32832170ceabfeebee9c6bc"),
    "CHILD_ERROR.json": (363, "ccf0840dd98c22bdec32fd8f71221cd808a1fa19ce59127ce0883ec4baca6ac5"),
    "CHILD_STDERR.bin": (601, "a0870adae55b3ee34b26aaee655f173fa8ca734e31064a18d0c34229b2a2efda"),
    "CHILD_STDOUT.bin": (0, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
    "COUNTERS.json": (445, "da2afcac527b1dcd159d666412909caacbd73205102731dfd2fa343505808350"),
    "PARENT_ERROR.json": (349, "0e1f8a5c4b4e15c3da785ee0cc9ab2a5c2c9d5ac5eb7f6261aaf23f054183903"),
    "POST_RESOURCE.json": (3268, "67db587aa54e8ce7dae9cd9edd674eae8e74fe09c5c00b995368b968b89b3f71"),
    "PRE_RESOURCE.json": (3268, "8fab8804eb760ed7c68508cd6a82e35ddcbb22ae3b4ba0a4001b96ecd39b712a"),
    "REBUILT_BOUNDARY.bin": (545171, "e580e44a679ecf9e2588c989cd4d026e326e7364331c46d1927b00ccada78fd4"),
    "RESULT.json": (403, "1015478b43bc67b279e05c26e24a0141c7482e81efc67d0f5c3f0b14f70d538c"),
    "START.json": (245, "cf6eee90e381cee105f0061bcc612f7ce219aefeb2901218ea14dbdfbc4e7c90"),
    "TERMINAL.json": (356, "61d4b20cb484681b97d4321e5de6045a0d09916f384a5245471837f59b03cc24"),
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_json(members, name):
    return json.loads(members[name].decode("utf-8"))


def review(path):
    raw = Path(path).read_bytes()
    if len(raw) != 54648 or sha256(raw) != EXPECTED_ZIP_SHA256:
        raise ValueError("artifact identity")
    with zipfile.ZipFile(path) as archive:
        if set(archive.namelist()) != set(EXPECTED_MEMBERS):
            raise ValueError("artifact member roster")
        members = {name: archive.read(name) for name in archive.namelist()}
    for name, (size, digest) in EXPECTED_MEMBERS.items():
        if len(members[name]) != size or sha256(members[name]) != digest:
            raise ValueError(f"member identity: {name}")

    admission = read_json(members, "ADMISSION.json")
    counters = read_json(members, "COUNTERS.json")
    result = read_json(members, "RESULT.json")
    terminal = read_json(members, "TERMINAL.json")
    if admission["admitted"] is not True:
        raise ValueError("resource admission")
    expected_counters = {
        "authentic_distinct_input_file_accesses": 4,
        "boundary_container_encodes": 1,
        "boundary_exact_comparisons": 68105,
        "candidate_boundary_builds": 1,
        "candidate_canonical_encodes": 1,
        "candidate_dense_expm_actions": 2,
        "candidate_sparse_expm_actions": 0,
        "canonical_decodes": 2,
        "dynamic_steps": 1,
        "final_exact_comparisons": 69728,
        "npz_decodes": 1,
        "optimizer_steps": 0,
        "oracle_reexecutions": 0,
        "torch_calls": 0,
    }
    if counters != expected_counters:
        raise ValueError("counter ledger")
    if result != {
        "all_closed": False,
        "bitwise_mismatch_coordinates": 665,
        "candidate_capsule_sha256": EXPECTED_MEMBERS["CANDIDATE.bin"][1],
        "candidate_oracle_bitwise_equal": False,
        "coordinate_comparisons": 69728,
        "max_abs_error_hex": "0x1.e000000000000p-54",
        "max_ulp_distance": 98,
        "qualification": False,
        "schema": "hcsn-n256-dense-compatible-firststep-result-v1",
    }:
        raise ValueError("RED result")
    if terminal["status"] != "RED" or terminal["child_exit_code"] != 1:
        raise ValueError("terminal state")
    return {
        "artifact_sha256": EXPECTED_ZIP_SHA256,
        "members": len(members),
        "comparisons": 69728,
        "mismatches": 665,
        "numerical_calls": 0,
        "status": "RED",
    }


if __name__ == "__main__":
    print(json.dumps(review(sys.argv[1]), sort_keys=True))
