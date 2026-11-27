"""Reproduce exact persistent-age vs original phase-only oracle comparisons."""

from fractions import Fraction as F
import hashlib
import json
from pathlib import Path
import sys

from qualification.hcsn_boundary_audit.refractory_transport import Packet, RefractoryState
from qualification.hcsn_boundary_audit.test_phase_delay_oracle import (
    CELLS, EDGES, TOTAL_TIME, project_every_substep, project_uniform_cell, total_variation,
)


def main():
    rows = []
    for count in (2, 4, 8, 16, 32):
        repaired_errors, projected_errors = [], []
        for source in range(CELLS):
            state = RefractoryState(F(0), (Packet(str(source), EDGES[source], EDGES[source + 1], F(1), (F(1),)),), 1)
            released = F(0)
            # Alternating 1:3 steps exercise a genuinely irregular schedule.
            increments = [1 + 2 * (i % 2) for i in range(count)]
            elapsed = F(0)
            for step in increments:
                elapsed += TOTAL_TIME * step / sum(increments)
                receipt = state.advance_to(elapsed)
                state = receipt.state
                released += sum((p.mass for p in receipt.released), F(0))
            bins, _ = state.project_remaining(EDGES)
            exact = project_uniform_cell(source, TOTAL_TIME)
            repaired_errors.append(total_variation(bins + (released,), exact))
            projected_errors.append(total_variation(project_every_substep(source, count), exact))
        rows.append({"substeps": count, "persistent_irregular_max_tv": str(max(repaired_errors)),
                     "original_equal_substep_max_tv": str(max(projected_errors)), "source_rows": CELLS})
    sources = (Path(__file__), Path(__file__).with_name("refractory_transport.py"),
               Path(__file__).with_name("test_phase_delay_oracle.py"))
    result = {"schema": "hcsn-exact-refractory-transport-probe-v1", "status": "HOLD_NO_GO",
              "scope": "phase-only external uniform/point packets; no active diffusion or training",
              "rows": rows,
              "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
              "full_hcsn_requalification_performed": False}
    if any(F(row["persistent_irregular_max_tv"]) != 0 for row in rows):
        raise ArithmeticError("persistent-age oracle disagreement")
    Path(sys.argv[1]).write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")


if __name__ == "__main__":
    main()
