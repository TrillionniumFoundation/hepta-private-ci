"""Verify exact source-only inputs and replay the original frozen checks."""

from pathlib import Path
import runpy


REPOSITORY = Path(__file__).resolve().parents[2]
FREEZE = "qualification/hcsn_currentstate_n256_uniformization_precision_policy/SOURCE_FREEZE.json"
FREEZE_SHA256 = "bb68eee5c4115445ff5e26b5be243f66b10013148c4d6e702b23beda1d8c5fdc"
VERIFIER_SHA256 = "1e0d0b923f9d09cae7f5fa5bc9ade9f41839e0ee3f2dda1fd3f08d1e67385e3d"
RESTORER = "qa/repository-consolidation/20261115/restore_raw_evidence.py"


def main():
    restore = runpy.run_path(str(REPOSITORY / RESTORER))
    restore["replay_source_freeze"](REPOSITORY, FREEZE, FREEZE_SHA256, VERIFIER_SHA256)


if __name__ == "__main__":
    main()
