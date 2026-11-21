"""V2 comparator-only runner: compare two containers before propagation."""

from pathlib import Path

from qualification.hcsn_currentstate_n256_boundary_container_contract.compare_boundary import (
    compare_exact,
)


EXECUTION_ALLOWED = False


def compare_published(oracle_path, candidate_path):
    oracle = Path(oracle_path).read_bytes()
    candidate = Path(candidate_path).read_bytes()
    return compare_exact(oracle, candidate)
