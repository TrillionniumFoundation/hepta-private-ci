"""Verify exact source-only inputs and replay the original frozen checks."""

from pathlib import Path
import runpy


REPOSITORY = Path(__file__).resolve().parents[2]
FREEZE = "qualification/hcsn_currentstate_n256_uniformization_provider_intent/SOURCE_FREEZE.json"
FREEZE_SHA256 = "27ad5b29b87c9bfae91b812b23e4b9fe191ae4f649c96fed43fe5f24ba1543e3"
VERIFIER_SHA256 = "af4fb0a283c446e19e940d71c038e55e92c73f60465c07cb98f14ff1c5dc2554"
RESTORER = "qa/repository-consolidation/20261115/restore_raw_evidence.py"


def main():
    restore = runpy.run_path(str(REPOSITORY / RESTORER))
    restore["replay_source_freeze"](REPOSITORY, FREEZE, FREEZE_SHA256, VERIFIER_SHA256)


if __name__ == "__main__":
    main()
