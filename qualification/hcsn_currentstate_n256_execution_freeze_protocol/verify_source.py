"""Verify the exact original numerical qualification source closure."""

from pathlib import Path
import runpy


REPOSITORY = Path(__file__).resolve().parents[2]
FREEZE = 'qualification/hcsn_currentstate_n256_execution_freeze_protocol/SOURCE_FREEZE.json'
FREEZE_SHA256 = 'd5808672458682f8d66eaa0a356c66266a0c10c899ed702f34fda5f1188a13b8'
VERIFIER_SHA256 = '809c9717b8a6f16cb77b06d4514f1fa2a9456c098c270426b5cb10507371c31c'


def main():
    restore = runpy.run_path(
        str(REPOSITORY / "qa/repository-consolidation/20261115/restore_raw_evidence.py")
    )
    restore["replay_source_freeze"](REPOSITORY, FREEZE, FREEZE_SHA256, VERIFIER_SHA256)


if __name__ == "__main__":
    main()
