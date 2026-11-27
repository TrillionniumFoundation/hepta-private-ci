"""Verify current and original bytes against the frozen qualification inputs."""

from pathlib import Path
import runpy


REPOSITORY = Path(__file__).resolve().parents[2]
FREEZE = "qualification/hcsn_currentstate_n256_uniformization_fp64_input_bridge/SOURCE_FREEZE.json"
FREEZE_SHA256 = "9480748a23d20ba2e9b7d624f28abc4ab70c10c7630aa5e40f19896dd59bb56c"
RESTORER = "qa/repository-consolidation/20261115/restore_raw_evidence.py"


def main():
    restore = runpy.run_path(str(REPOSITORY / RESTORER))
    restore["replay_source_freeze"](REPOSITORY, FREEZE, FREEZE_SHA256)


if __name__ == "__main__":
    main()
