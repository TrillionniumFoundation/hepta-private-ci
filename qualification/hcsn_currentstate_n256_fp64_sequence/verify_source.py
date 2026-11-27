"""Replay the exact frozen arithmetic source checks and their approved inputs."""

from pathlib import Path
import runpy


REPOSITORY = Path(__file__).resolve().parents[2]
FREEZE = "qualification/hcsn_currentstate_n256_fp64_sequence/SOURCE_FREEZE.json"
FREEZE_SHA256 = "8893bebfa9d5c0cd20d64448ea3a25102a46fdec49ab5ab4a124c518f66736da"
RESTORER = "qa/repository-consolidation/20261115/restore_raw_evidence.py"


def main():
    restore = runpy.run_path(str(REPOSITORY / RESTORER))
    restore["replay_source_freeze"](REPOSITORY, FREEZE, FREEZE_SHA256)


if __name__ == "__main__":
    main()
