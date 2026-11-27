"""Verify exact parent identities for the source-only receipt publisher."""

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from qualification.hcsn_currentstate_n256_execution_receipt_publisher_intent import (
    static_inspector,
)


ROOT = Path(__file__).parent
EXPECTED = {
    "qualification/hcsn_currentstate_n256_execution_receipt_contract/receipt_contract.py": "de570dd7fd9f82edd547b5e483f585553ea76e64fbcae543e745f7d3521cbf2a",
    "qualification/hcsn_currentstate_n256_execution_receipt_contract/REQUEST.json": "1a2fd322e3b78b9ff68db5f3980d52fe14c336d9bab27bc0a3937afd57772a7c",
    "qualification/hcsn_currentstate_n256_execution_admission_bridge/admission_bridge.py": "90f766fe0f847c471c82731be402a6961a2e72644da1d876dcaaca25b122b887",
    "qualification/hcsn_currentstate_n256_execution_freeze_protocol/execution_freeze.py": "a458a4be1468333408a709830b4e876afbe503cac255c577b4e8328268114f10",
    "qualification/hcsn_currentstate_n256_provider_fullstate_bridge/bridge.py": "ae3528df120e60ff8ce13fa8a259a3fadcfff3e9fb8a04a786b0ab1ced5e0183",
}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    request = json.loads((ROOT / "REQUEST.json").read_text())
    freeze = json.loads((ROOT / "SOURCE_FREEZE.json").read_text())
    for relative, expected in EXPECTED.items():
        if _sha(REPO / relative) != expected:
            raise SystemExit(f"parent identity mismatch: {relative}")
    for relative, expected in freeze["files"].items():
        if _sha(REPO / relative) != expected:
            raise SystemExit(f"frozen source mismatch: {relative}")
    report = static_inspector.inspect(ROOT / "publisher.py", ROOT / "REQUEST.json")
    if report["status"] != "PASS_EXECUTION_RECEIPT_PUBLISHER_SOURCE_HOLD":
        raise SystemExit("static source inspection failed")
    if request["base_commit"] != "ca307ce5f1e1856b8da5a36e301a1dbc30b24666":
        raise SystemExit("base commit mismatch")
    if freeze["status"] != "PASS_SOURCE_ONLY_HOLD_EXTERNAL_ORIGINALS":
        raise SystemExit("source freeze status mismatch")
    if freeze["all_closed"] is not False or freeze["largegrid_qualification"] is not False:
        raise SystemExit("source freeze grants closure or qualification")
    print("PASS_N256_EXECUTION_RECEIPT_PUBLISHER_SOURCE_HOLD")


if __name__ == "__main__":
    main()
