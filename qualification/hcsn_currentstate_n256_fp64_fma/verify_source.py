"""Replay the exact frozen arithmetic source checks and their approved inputs."""

from pathlib import Path
import runpy


REPOSITORY = Path(__file__).resolve().parents[2]
FREEZE = "qualification/hcsn_currentstate_n256_fp64_fma/SOURCE_FREEZE.json"
FREEZE_SHA256 = "2d56c7c4fc05d482ec751f5bab60700e6a2ef35e9d32d0133edd0e4a83bf21bb"
RESTORER = "qa/repository-consolidation/20261115/restore_raw_evidence.py"


def main():
    restore = runpy.run_path(str(REPOSITORY / RESTORER))
    restore["replay_source_freeze"](REPOSITORY, FREEZE, FREEZE_SHA256)


if __name__ == "__main__":
    main()
