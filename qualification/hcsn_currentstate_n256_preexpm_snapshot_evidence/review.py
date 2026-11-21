"""Independently review both immutable artifacts without numerical imports."""

import hashlib
import io
import json
import zipfile
from pathlib import Path


HERE = Path(__file__).parent
ARTIFACTS = (
    HERE / "run44916753930-artifact14711463209.zip",
    HERE / "run44916786884-artifact14711278907.zip",
)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _files(path):
    raw = path.read_bytes()
    with zipfile.ZipFile(io.BytesIO(raw)) as outer:
        if outer.testzip() is not None:
            raise ValueError("outer CRC")
        prefix = "hcsn-n256-preexpm-snapshot-output/"
        files = {
            name[len(prefix) :]: outer.read(name)
            for name in outer.namelist()
            if name.startswith(prefix) and not name.endswith("/")
        }
    return raw, files


def review():
    expected = json.loads((HERE / "REVIEW.json").read_text())
    loaded = [_files(path) for path in ARTIFACTS]
    for index, (raw, files) in enumerate(loaded):
        if _sha(raw) != expected["runs"][index]["zip_sha256"]:
            raise ValueError("artifact identity")
        result = json.loads(files["RESULT.json"])
        if not result["scope"]["current_source_preexpm_inputs_byte_equal"]:
            raise ValueError("within-run input mismatch")
        if any(result["counters"][name] for name in (
            "dynamic_steps",
            "dense_exponential_actions",
            "sparse_exponential_actions",
            "scipy_imports",
            "torch_calls",
            "optimizer_steps",
        )):
            raise ValueError("scope widened")
    left, right = loaded[0][1], loaded[1][1]
    binaries = sorted(name for name in left if name.endswith(".bin"))
    if len(binaries) != 12 or binaries != sorted(name for name in right if name.endswith(".bin")):
        raise ValueError("binary denominator")
    if any(left[name] != right[name] for name in binaries):
        raise ValueError("cross-run binary mismatch")
    if left["RESULT.json"] != right["RESULT.json"]:
        raise ValueError("cross-run result mismatch")
    if expected["protocol"] != {
        "single_execution_required": True,
        "observed_executions": 2,
        "single_execution_gate": False,
        "status": "RED_DUPLICATE_KEY",
        "cause": "run branch creation triggered push run before one explicit activation fast-forward triggered a second push run",
        "cancelled": 0,
        "rerun": 0,
        "replacement_key": False,
    }:
        raise ValueError("protocol history")
    if expected["scope"]["cause_of_6901_red"] != "UNKNOWN":
        raise ValueError("historical UNKNOWN changed")
    if expected["scope"]["all_closed"] is not False:
        raise ValueError("all_closed")
    return {
        "status": "RED_DUPLICATE_KEY",
        "artifact_crc_ok": 2,
        "binary_files_compared": 12,
        "cross_run_binary_mismatches": 0,
        "single_execution_gate": False,
        "all_closed": False,
    }


if __name__ == "__main__":
    print(json.dumps(review(), sort_keys=True))
