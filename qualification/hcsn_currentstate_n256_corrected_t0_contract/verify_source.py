"""Verify exact corrected sources and authentic input identities without execution."""

import base64
import hashlib
import json
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from qualification.hcsn_currentstate_n256_corrected_t0_contract import contract
from qualification.hcsn_currentstate_n256_corrected_t0_contract import static_inspector


ROOT = Path(__file__).parent


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _canonical(value):
    return json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()


def main():
    request = json.loads((ROOT / "REQUEST.json").read_text())
    freeze = json.loads((ROOT / "SOURCE_FREEZE.json").read_text())
    contract.validate_source_request(request)
    if freeze["base_commit"] != contract.BASE_COMMIT:
        raise SystemExit("base commit mismatch")
    for roster in ("files", "inherited_source_sha256", "authentic_input_sha256"):
        for relative, expected in freeze[roster].items():
            if _sha(REPO / relative) != expected:
                raise SystemExit(f"{roster} mismatch: {relative}")

    encoded = (REPO / "qualification/hcsn_n256_new_export/evidence/attempt001/N256_STATE.npz.b64").read_text()
    decoded = base64.b64decode(encoded.strip(), validate=True)
    if hashlib.sha256(decoded).hexdigest() != freeze["decoded_npz_sha256"]:
        raise SystemExit("decoded NPZ mismatch")
    input_hashes = {
        "metadata": freeze["authentic_input_sha256"]["qualification/hcsn_n256_new_export/evidence/attempt001/METADATA.json"],
        "npz": freeze["decoded_npz_sha256"],
        "npz_b64": freeze["authentic_input_sha256"]["qualification/hcsn_n256_new_export/evidence/attempt001/N256_STATE.npz.b64"],
        "phase": freeze["authentic_input_sha256"]["qualification/hcsn_n256_new_export/evidence/attempt001/N256_PHASE.json"],
        "state": freeze["authentic_input_sha256"]["qualification/hcsn_n256_new_export/evidence/attempt001/N256_STATE.json"],
    }
    if hashlib.sha256(_canonical(input_hashes)).hexdigest() != freeze["input_bundle_sha256"]:
        raise SystemExit("input bundle mismatch")

    historical = (REPO / "qualification/hcsn_currentstate_n256_t0_capsule_v1/builder.py").read_text()
    if contract.HISTORICAL_CANDIDATE_SHA256 not in historical or contract.HISTORICAL_ORACLE_SHA256 not in historical:
        raise SystemExit("historical capsule bindings changed")
    if contract.CORRECTED_CANDIDATE_SHA256 in historical or contract.CORRECTED_ORACLE_ADAPTER_SHA256 in historical:
        raise SystemExit("historical capsule was silently transferred")

    report = static_inspector.inspect(ROOT / "contract.py", ROOT / "REQUEST.json")
    if report["status"] != "PASS_CORRECTED_T0_CONTRACT_SOURCE_ONLY_HOLD":
        raise SystemExit("static source inspection failed")
    if any(freeze[field] != 0 for field in (
        "authentic_capsules",
        "authentic_coordinates",
        "authentic_serializer_calls",
        "dynamic_runs",
        "matrix_exponential_actions",
        "provider_calls",
        "torch_calls",
        "optimizer_steps",
    )):
        raise SystemExit("source freeze claims authentic execution")
    if freeze["historical_capsule_transfer_allowed"] is not False:
        raise SystemExit("historical capsule transfer enabled")
    if freeze["largegrid_qualification"] is not False or freeze["all_closed"] is not False:
        raise SystemExit("source freeze grants qualification or closure")
    print("PASS_N256_CORRECTED_T0_CONTRACT_SOURCE_ONLY_HOLD")


if __name__ == "__main__":
    main()
