"""Replay the exact frozen arithmetic source checks and their approved inputs."""

from pathlib import Path
import runpy


REPOSITORY = Path(__file__).resolve().parents[2]
FREEZE = "qualification/hcsn_currentstate_n256_fp64_add_sub/SOURCE_FREEZE.json"
FREEZE_SHA256 = "e2ef36a84c0309898970a71f08974ac84205b806245504b7a6ec4be44c0cd8bd"
RESTORER = "qa/repository-consolidation/20261115/restore_raw_evidence.py"


def main():
    restore = runpy.run_path(str(REPOSITORY / RESTORER))
    restore["replay_source_freeze"](REPOSITORY, FREEZE, FREEZE_SHA256)


if __name__ == "__main__":
    main()
