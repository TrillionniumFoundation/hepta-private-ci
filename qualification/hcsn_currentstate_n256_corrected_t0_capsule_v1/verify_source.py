"""Fail-closed source, admission, input, and workflow verifier."""

import ast
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
FORBIDDEN = {"jax", "numpy", "scipy", "tensorflow", "torch"}
EXPECTED_KEY = "hcsn-n256-corrected-t0-capsule-20261117-c06d-002"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    admission = json.loads((HERE / "ADMISSION.json").read_text())
    if admission["execution_key"] != EXPECTED_KEY or admission["execution_allowed"] is not True:
        raise ValueError("exact execution admission")
    if admission["single_execution"] is not True:
        raise ValueError("single execution admission")
    if admission["historical_negative_and_unknown_preserved"] is not True:
        raise ValueError("historical RED/UNKNOWN preservation")
    negative_path = HERE / "evidence/precommit_attempt001/PRECOMMIT_ATTEMPT001.json"
    negative = json.loads(negative_path.read_text())
    if (
        negative["execution_key"]
        != "hcsn-n256-corrected-t0-capsule-20261117-c06d-001"
        or negative["source_precommitted"] is not False
        or negative["qualification"] is not False
        or negative["same_key_rerun_allowed"] is not False
        or negative["status"] != "REJECT_PRECOMMIT_PROTOCOL_FAILURE"
    ):
        raise ValueError("precommit attempt001 negative preservation")
    if admission["precommit_attempt001"]["metadata_sha256"] != sha(negative_path):
        raise ValueError("precommit attempt001 metadata binding")
    for flag in ("cold_load_qualified", "largegrid_qualification", "production_adoption", "all_closed"):
        if admission[flag] is not False:
            raise ValueError(f"admission grants {flag}")

    freeze = json.loads((HERE / "SOURCE_FREEZE.json").read_text())
    observed = {path: sha(ROOT / path) for path in freeze["files"]}
    if observed != freeze["files"]:
        raise ValueError("source freeze mismatch")
    inherited = freeze["inherited_source_sha256"]
    if {path: sha(ROOT / path) for path in inherited} != inherited:
        raise ValueError("inherited corrected source mismatch")
    originals = freeze["authentic_input_sha256"]
    if {path: sha(ROOT / path) for path in originals} != originals:
        raise ValueError("authentic input mismatch")
    expected_sources = {
        "builder": observed[
            "qualification/hcsn_currentstate_n256_corrected_t0_capsule_v1/builder.py"
        ],
        "cold_audit": observed[
            "qualification/hcsn_currentstate_n256_corrected_t0_capsule_v1/cold_audit.py"
        ],
        "contract": inherited[
            "qualification/hcsn_currentstate_n256_corrected_t0_contract/contract.py"
        ],
        "contract_request": inherited[
            "qualification/hcsn_currentstate_n256_corrected_t0_contract/REQUEST.json"
        ],
        "verify_source": observed[
            "qualification/hcsn_currentstate_n256_corrected_t0_capsule_v1/verify_source.py"
        ],
        "workflow": observed[
            ".github/workflows/hcsn-n256-corrected-authentic-t0-capsule.yml"
        ],
    }
    if admission["source_sha256"] != expected_sources:
        raise ValueError("admission source cross-binding")
    contract_request = json.loads(
        (
            ROOT
            / "qualification/hcsn_currentstate_n256_corrected_t0_contract/REQUEST.json"
        ).read_text()
    )
    if admission["bindings"] != contract_request["bindings"]:
        raise ValueError("admission corrected-lineage binding")
    if admission["budget"] != contract_request["future_execution_budget"]:
        raise ValueError("admission execution budget")

    for name in ("builder.py", "cold_audit.py"):
        tree = ast.parse((HERE / name).read_text())
        imports = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports |= {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        if imports & FORBIDDEN:
            raise ValueError("new lane imports numerical or model dependency")

    workflow = (
        ROOT / ".github/workflows/hcsn-n256-corrected-authentic-t0-capsule.yml"
    ).read_text()
    if workflow.count("hcsn_currentstate_n256_corrected_t0_capsule_v1.builder ") != 1:
        raise ValueError("builder execution denominator")
    if workflow.count("hcsn_currentstate_n256_corrected_t0_capsule_v1.cold_audit ") != 1:
        raise ValueError("cold audit execution denominator")
    if workflow.count(EXPECTED_KEY) != 1:
        raise ValueError("workflow execution key denominator")
    if "hcsn-n256-corrected-t0-capsule-20261117-c06d-001" in workflow:
        raise ValueError("consumed precommit key readmitted")
    print(
        json.dumps(
            {
                "status": "PASS_CORRECTED_T0_AUTHENTIC_SOURCE_FREEZE",
                "files": len(observed),
                "execution_key": EXPECTED_KEY,
                "authentic_capsules": 0,
                "dynamic_runs": 0,
                "torch_calls": 0,
                "optimizer_steps": 0,
                "largegrid_qualification": False,
                "all_closed": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
