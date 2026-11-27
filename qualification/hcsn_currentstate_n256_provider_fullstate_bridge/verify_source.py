"""Verify the exact original numerical qualification source closure."""

from pathlib import Path
import runpy


REPOSITORY = Path(__file__).resolve().parents[2]
FREEZE = 'qualification/hcsn_currentstate_n256_provider_fullstate_bridge/SOURCE_FREEZE.json'
FREEZE_SHA256 = '54ebf975f5b00deffd071a517320c3b48a7b0a79211eb0eea7a2be15b2023222'


def main():
    restore = runpy.run_path(
        str(REPOSITORY / "qa/repository-consolidation/20261115/restore_raw_evidence.py")
    )
    restore["replay_source_freeze"](REPOSITORY, FREEZE, FREEZE_SHA256)


if __name__ == "__main__":
    main()
