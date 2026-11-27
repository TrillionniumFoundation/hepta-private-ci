"""Verify current and original bytes against the frozen qualification inputs."""

from pathlib import Path
import runpy


REPOSITORY = Path(__file__).resolve().parents[2]
FREEZE = "qualification/hcsn_currentstate_n256_uniformization_output_interval/SOURCE_FREEZE.json"
FREEZE_SHA256 = "dc03024c7eb5b538a3198d3202f693687557555ece6f6bef4d24b329d6b8a562"
RESTORER = "qa/repository-consolidation/20261115/restore_raw_evidence.py"


def main():
    restore = runpy.run_path(str(REPOSITORY / RESTORER))
    restore["replay_source_freeze"](REPOSITORY, FREEZE, FREEZE_SHA256)


if __name__ == "__main__":
    main()
