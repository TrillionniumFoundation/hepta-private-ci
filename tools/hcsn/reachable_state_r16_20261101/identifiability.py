"""Check operator equivalence and the achievable paired sign-flip resolution."""

import gzip
import itertools
import json
from pathlib import Path

import numpy as np

from ..addressed_decision_r15_20261101.law import Law


HERE = Path(__file__).parent
PRIOR = HERE.parent / "addressed_decision_r15_20261101/run_01"


def run():
    frozen = json.loads((PRIOR / "FREEZE.json").read_text())
    rows = []
    for seed, selected in frozen["selections"].items():
        calibration = json.loads(gzip.decompress((PRIOR / "calibration" / f"{seed}.json.gz").read_bytes()))
        hx = Law.from_payload(calibration["models"]["hx"]["payload"])
        ordinary = Law.from_payload(calibration["models"][selected["ordinary"]]["payload"])
        fields = ("Q", "prior", "E_read", "E_refresh", "reward")
        exact = all(np.array_equal(getattr(hx, name), getattr(ordinary, name)) for name in fields)
        rows.append(dict(seed=int(seed), ordinary=selected["ordinary"],
                         operator_equal=exact, hx_operator=hx.operator_identity,
                         ordinary_operator=ordinary.operator_identity))
    n = len(rows)
    possible = sum(not row["operator_equal"] for row in rows)
    lower = min(1., 2. ** (1 - possible))
    # Positive equal magnitudes attain the mathematical lower bound. Zeros
    # generate duplicate sign assignments, exactly as the registered test.
    extreme = np.r_[np.ones(possible), np.zeros(n - possible)]
    signs = np.array(list(itertools.product((-1, 1), repeat=n)))
    observed = abs(float(extreme.mean()))
    brute = float(np.mean(abs((signs * extreme).mean(1)) >= observed - 1e-14))
    if brute != lower:
        raise AssertionError("Sign-flip resolution derivation disagrees with exhaustive enumeration")
    return dict(schema="hcsn-r16-identifiability-v1", inherited_fit_count=n,
                operators=rows, guaranteed_zero_differences=n - possible,
                maximum_nonzero_differences=possible, minimum_possible_two_sided_p=lower,
                exhaustive_extreme_example_p=brute,
                positive_primary_significance_attainable=lower < .05,
                no_future_outcomes_used=True,
                consequence="More episodes cannot pass the positive D-B significance gate under this inherited operator selection; HX estimation/representation/implementation hypotheses must be assessed separately without removing the same-Q control.")


if __name__ == "__main__":
    result = run()
    output = HERE / "results/IDENTIFIABILITY.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "operators"}))
