"""Replay the exact frozen arithmetic source checks and their approved inputs."""

from pathlib import Path
import runpy


REPOSITORY = Path(__file__).resolve().parents[2]
FREEZE = "qualification/hcsn_currentstate_n256_fp64_mul_div/SOURCE_FREEZE.json"
FREEZE_SHA256 = "be2f9defd2fb1ca791198a2931b4887173db85c7448d6bb9f89bde4ecfd69a7c"
RESTORER = "qa/repository-consolidation/20261115/restore_raw_evidence.py"


def main():
    restore = runpy.run_path(str(REPOSITORY / RESTORER))
    restore["replay_source_freeze"](REPOSITORY, FREEZE, FREEZE_SHA256)


if __name__ == "__main__":
    main()
