"""Verify exact source-only inputs and replay the original frozen checks."""

from pathlib import Path
import runpy


REPOSITORY = Path(__file__).resolve().parents[2]
FREEZE = "qualification/hcsn_currentstate_n256_uniformization_independence_review/SOURCE_FREEZE.json"
FREEZE_SHA256 = "6ff6e6ff41de05feb16b14d6be32117574fc0fe407de06d872c61e8bb29e33ec"
VERIFIER_SHA256 = "1ff8da4d32009f71f02e363b0b13ed4f86746589cc52450f69e913454407e1fe"
RESTORER = "qa/repository-consolidation/20261115/restore_raw_evidence.py"


def main():
    restore = runpy.run_path(str(REPOSITORY / RESTORER))
    restore["replay_source_freeze"](REPOSITORY, FREEZE, FREEZE_SHA256, VERIFIER_SHA256)


if __name__ == "__main__":
    main()
