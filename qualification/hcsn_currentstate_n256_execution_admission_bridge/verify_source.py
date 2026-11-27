"""Verify the exact original numerical qualification source closure."""

from pathlib import Path
import runpy


REPOSITORY = Path(__file__).resolve().parents[2]
FREEZE = 'qualification/hcsn_currentstate_n256_execution_admission_bridge/SOURCE_FREEZE.json'
FREEZE_SHA256 = '7202a17774288cfe3b9bfc6afe8eabd94d705b42756fd9f2b319bac1dc6f4750'
VERIFIER_SHA256 = 'c4ad7bd0ef55e5d5e5e0d82775c852eff9343130f21ecbde14d343468c3b4dcf'


def main():
    restore = runpy.run_path(
        str(REPOSITORY / "qa/repository-consolidation/20261115/restore_raw_evidence.py")
    )
    restore["replay_source_freeze"](REPOSITORY, FREEZE, FREEZE_SHA256, VERIFIER_SHA256)


if __name__ == "__main__":
    main()
