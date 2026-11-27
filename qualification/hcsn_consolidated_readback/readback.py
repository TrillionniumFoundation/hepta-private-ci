"""Read consumed HCSN attempts and their exact historical source without rerunning them."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
MANIFEST_SHA256 = "6e57a51e175173692e651afb6e1fd924d647a05c494b7859f9e4ffc8f3e4f859"
CURRENT_WORKFLOWS = {
    ".github/workflows/hcsn-currentstate-n256-firststep-dense-oracle-hosted.yml": "8d790013287d07fc986a44de62a4d9c194c1b4efdfacf1854587c301b34d8e1e",
    ".github/workflows/hcsn-currentstate-n256-warm1-sparse.yml": "e5eef5ba21845c9ecab9781fa977e70ecd4f5f45144d4cd608239e8b6b0b9803",
    ".github/workflows/hcsn-currentstate-n256-corrected-t0-contract.yml": "12c9550e3177d22ba0c4522d4c88a0d8ba7d9996dea6776a0f9a1d1be1772f56",
}
CURRENT_REQUEST = (
    "qualification/hcsn_currentstate_n256_terminal_publication_intent/REQUEST.json"
)
CURRENT_REQUEST_SHA256 = (
    "b874cb88e587e388f669f5f4da11e93cd7fda1c8369966a6035782b05f2f36bc"
)
CASES = ("dense", "warm", "corrected-contract")
MODULES = {
    "dense": "qualification.hcsn_currentstate_n256_firststep_dense_oracle_hosted",
    "warm": "qualification.hcsn_currentstate_n256_warm1_sparse",
    "corrected-contract": "qualification.hcsn_currentstate_n256_corrected_t0_contract",
}
TEST_MODULES = {
    "dense": (MODULES["dense"] + ".test_launcher",),
    "warm": (MODULES["warm"] + ".test_candidate", MODULES["warm"] + ".test_runner"),
    "corrected-contract": (MODULES["corrected-contract"] + ".test_contract",),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_regular(root, relative, expected_bytes=None):
    path = PurePosixPath(relative)
    require(
        not path.is_absolute()
        and path.parts
        and all(x not in (".", "..") for x in path.parts),
        "unsafe source path",
    )
    target = root.joinpath(*path.parts)
    require(
        not any(parent.is_symlink() for parent in (target, *target.parents)),
        "source link",
    )
    with target.open("rb") as source:
        metadata = os.fstat(source.fileno())
        require(stat.S_ISREG(metadata.st_mode), "source is not a regular file")
        require(metadata.st_size <= 8 * 1024 * 1024, "source exceeds read bound")
        if expected_bytes is not None:
            require(
                metadata.st_size == expected_bytes, "source size drift: " + relative
            )
        raw = source.read(8 * 1024 * 1024 + 1)
    require(len(raw) == metadata.st_size, "source size changed during read")
    return raw


def load_manifest(root):
    relative = "qualification/hcsn_consolidated_readback/SNAPSHOT.json"
    raw = read_regular(root, relative)
    require(digest(raw) == MANIFEST_SHA256, "snapshot manifest drift")
    manifest = json.loads(raw)
    require(manifest["schema"] == "hcsn-consumed-source-snapshot-v1", "snapshot schema")
    require(len(manifest["files"]) == 190, "snapshot file denominator")
    require(
        len({row["path"] for row in manifest["files"]}) == 190,
        "duplicate snapshot path",
    )
    require(
        sum(row["bytes"] for row in manifest["files"]) < 4 * 1024 * 1024,
        "snapshot bound",
    )
    return manifest


def prepare_snapshot(root, destination):
    manifest = load_manifest(root)
    for path, expected in CURRENT_WORKFLOWS.items():
        require(
            digest(read_regular(root, path)) == expected,
            "current readback workflow drift: " + path,
        )
    require(
        digest(read_regular(root, CURRENT_REQUEST)) == CURRENT_REQUEST_SHA256,
        "current coupling repair request drift",
    )
    for row in manifest["files"]:
        raw = read_regular(root, row["source"], row["bytes"])
        require(
            digest(raw) == row["sha256"], "historical source drift: " + row["source"]
        )
        target = destination / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as output:
            output.write(raw)
    return manifest


def verify_unchanged_snapshot(destination, manifest):
    for row in manifest["files"]:
        raw = read_regular(destination, row["path"], row["bytes"])
        require(digest(raw) == row["sha256"], "readback modified historical source")
    require(
        not list(destination.rglob("RUN_OUTPUT")), "consumed execution was relaunched"
    )


# Only these reviewed read-only functions run in the child. The original launchers
# and runners remain importable for their unchanged tests, but no execution entry
# point is called. All input bytes are checked before building this temporary view.
WORKER = r"""
import hashlib
import importlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

case, module = sys.argv[1:]

def require(condition, message):
    if not condition:
        raise ValueError(message)

def refuse_execution(*args, **kwargs):
    raise RuntimeError("consumed execution cannot launch a process")

with patch("subprocess.Popen", side_effect=refuse_execution):
    if case == "corrected-contract":
        importlib.import_module(module + ".verify_source").main()
        result = {"status": "PASS_HISTORICAL_CONTRACT_SOURCE_ONLY_HOLD", "dynamic_steps": 0}
    else:
        package = Path(*module.split("."))
        evidence = package / "evidence/attempt001-20261119"
        admission = json.loads((evidence / "originals/ADMISSION.json").read_text())
        terminal = json.loads((evidence / "originals/TERMINAL.json").read_text())
        if case == "dense":
            key = "hcsn-n256-firststep-dense-oracle-hosted-20261118-c06d-001"
            require(admission["unique_execution_key"] == terminal["unique_execution_key"] == key, "dense consumed key")
            run = json.loads((evidence / "RUN_METADATA.json").read_text())
            artifact = json.loads((evidence / "ARTIFACT_METADATA.json").read_text())["artifacts"][0]
            require((run["id"], run["run_attempt"], run["head_sha"], run["status"], run["conclusion"])
                    == (44462874515, 1, "c8e36e8579153761adee4ed84d44b40ec6d36000", "completed", "success"), "dense original run")
            require(artifact["workflow_run"]["id"] == run["id"] and artifact["workflow_run"]["head_sha"] == run["head_sha"], "dense artifact source")
            importlib.import_module(module + ".verify_source").main()
        else:
            key = "hcsn-n256-independent-warm1-sparse-20261119-001"
            require(admission["identity"] == terminal["identity"] == key, "warm consumed key")
            identity = json.loads((evidence / "HOSTED_IDENTITY.json").read_text())
            require((identity["run_id"], identity["job_id"], identity["artifact_id"], identity["head_sha"])
                    == (44466138035, 135364262211, 14501927547, "2ae4e8639b7529ac0ad7288d834c8ceecca1915d"), "warm original source")
            require(terminal["status"] == "COMPARISON_COMPLETED" and terminal["original_bitwise_gate"] == "RED", "original RED must remain RED")
            importlib.import_module(module + ".runner").check_freeze()
        reviewer = importlib.import_module(module + ".review_actual")
        result = reviewer.review()
        if case == "warm":
            result["review_source_sha256"] = hashlib.sha256(Path(reviewer.__file__).read_bytes()).hexdigest()
            require(result["bitwise_mismatches"] == 1291 and result["coordinate_counts"]["total"] == 69728, "original comparison denominator")
        require(result == json.loads((evidence / "INDEPENDENT_REVIEW.json").read_text()), "original independent readback changed")
        require(not ({"numpy", "scipy", "torch"} & set(sys.modules)), "readback imported numerical execution packages")
        require(terminal["all_closed"] is False and terminal["largegrid_qualification"] is False and terminal["production_adoption"] is False, "original scope widened")
print(json.dumps({"case": case, "mode": "consumed_original_readback", "new_execution_allowed": False, "new_dynamic_steps": 0, "readback": result}, sort_keys=True, allow_nan=False))
"""


def run_case(snapshot, case):
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    for optimized in (False, True):
        prefix = [sys.executable, "-B"] + (["-O"] if optimized else [])
        subprocess.run(
            prefix + ["-c", WORKER, case, MODULES[case]],
            cwd=snapshot,
            env=environment,
            check=True,
            timeout=180,
        )
        subprocess.run(
            prefix + ["-m", "unittest", *TEST_MODULES[case], "-v"],
            cwd=snapshot,
            env=environment,
            check=True,
            timeout=180,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=(*CASES, "all"), default="all")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="hcsn-consumed-readback-") as directory:
        snapshot = Path(directory)
        manifest = prepare_snapshot(ROOT, snapshot)
        for case in CASES if args.case == "all" else (args.case,):
            run_case(snapshot, case)
        verify_unchanged_snapshot(snapshot, manifest)
    print("PASS_CONSUMED_ORIGINAL_READBACK_NO_NEW_EXECUTION")


if __name__ == "__main__":
    main()
