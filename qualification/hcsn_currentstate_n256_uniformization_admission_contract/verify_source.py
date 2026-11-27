"""Verify the exact original numerical qualification source closure."""

from pathlib import Path
import runpy


REPOSITORY = Path(__file__).resolve().parents[2]
FREEZE = 'qualification/hcsn_currentstate_n256_uniformization_admission_contract/SOURCE_FREEZE.json'
FREEZE_SHA256 = '2db178d56576f2a65481dab88092414035079de94915b4d3877970687d40f10b'
VERIFIER_SHA256 = 'e19ec152ded35e7b3d762458f3931e6cf2ebae5398d832c110756beabe2b459f'


def main():
    restore = runpy.run_path(
        str(REPOSITORY / "qa/repository-consolidation/20261115/restore_raw_evidence.py")
    )
    restore["replay_source_freeze"](REPOSITORY, FREEZE, FREEZE_SHA256, VERIFIER_SHA256)


if __name__ == "__main__":
    main()
