"""Verify exact parent and source identities for the terminal bridge."""

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from qualification.hcsn_currentstate_n256_terminal_publication_intent import (
    static_inspector,
)


ROOT = Path(__file__).parent
PARENTS = {
    "qualification/hcsn_currentstate_n256_execution_receipt_publisher_intent/publisher.py": "237f34ca7bc8e82d8c5b44e37ae294bf9c9d7ca19bf7f9d0f0275de4a880ef85",
    "qualification/hcsn_currentstate_n256_execution_receipt_publisher_intent/REQUEST.json": "c1f05542d19e83ec8561d303fa825c02e6c71c665e20fd547bd8bdfc945dec42",
    "qualification/hcsn_currentstate_n256_execution_receipt_contract/receipt_contract.py": "6f6f28ab504f1789c526439b321fc091a14390a51455635d1ba9732d368c64a2",
    "qualification/hcsn_currentstate_n256_execution_admission_bridge/admission_bridge.py": "90f766fe0f847c471c82731be402a6961a2e72644da1d876dcaaca25b122b887",
}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    request = json.loads((ROOT / "REQUEST.json").read_text())
    freeze = json.loads((ROOT / "SOURCE_FREEZE.json").read_text())
    for relative, expected in PARENTS.items():
        if _sha(REPO / relative) != expected:
            raise SystemExit(f"parent identity mismatch: {relative}")
    for relative, expected in freeze["files"].items():
        if _sha(REPO / relative) != expected:
            raise SystemExit(f"frozen source mismatch: {relative}")
    report = static_inspector.inspect(
        ROOT / "terminal_publication.py", ROOT / "REQUEST.json"
    )
    if report["status"] != "PASS_TERMINAL_PUBLICATION_SOURCE_HOLD":
        raise SystemExit("static source inspection failed")
    if request["base_commit"] != "8825b4738095ecbb1fb40747e5af94f5db33814d":
        raise SystemExit("base commit mismatch")
    if (
        freeze["all_closed"] is not False
        or freeze["largegrid_qualification"] is not False
    ):
        raise SystemExit("source freeze grants closure or qualification")
    print("PASS_N256_TERMINAL_PUBLICATION_SOURCE_HOLD")


if __name__ == "__main__":
    main()
