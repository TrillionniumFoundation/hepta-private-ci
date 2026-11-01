"""Record the tolerance cutoff limitation and check an exact-sum boundary."""

from fractions import Fraction
import hashlib
import json
from pathlib import Path

import numpy as np

from candidate import resolve_action

ROOT = Path(__file__).resolve().parent
TOL = 1e-12


def main():
    below = np.array([0., TOL])
    above = np.array([0., np.nextafter(TOL, np.inf)])
    cutoff_actions = [resolve_action(q, TOL) for q in (below, above)]
    assert cutoff_actions == [0, 1]
    tiny = np.nextafter(0., 1.)
    rounded_gap = np.array([-tiny, TOL])
    assert TOL - rounded_gap[0] == TOL
    assert Fraction.from_float(TOL) - Fraction.from_float(-tiny) > Fraction.from_float(TOL)
    assert resolve_action(rounded_gap, TOL) == 1
    assert resolve_action([tiny, TOL], TOL) == 0
    actual = json.loads((ROOT / "ACTUAL_Q_PAIRS.json").read_text())
    margins = []
    for row in actual["rows"]:
        last = row["steps"][-1]
        qd = np.array(last["D"]["qvalues"][:2])
        qh = np.array(last["HMM"]["qvalues"][:2])
        delta = float(np.max(np.abs(qd-qh)))
        cutoff_margin = float(np.min(np.abs(TOL - (qd.max()-qd))))
        assert cutoff_margin > 2*delta
        margins.append(dict(seed=row["seed"], domain=row["domain"],
            episode_index_zero_based=row["episode_index_zero_based"],
            maximum_Q_difference=delta, cutoff_margin_D=cutoff_margin,
            sufficient_same_eligibility_margin=True))
    path = ROOT / "STABILITY_LIMIT.json"
    if path.exists():
        raise ValueError(f"Refusing to overwrite {path}")
    payload = dict(tolerance=TOL,
        cutoff_counterexample=dict(q1=below.tolist(), q2=above.tolist(), actions=cutoff_actions,
            maximum_Q_difference=float(np.max(np.abs(below-above)))),
        rounded_gap_boundary=dict(q=rounded_gap.tolist(), rounded_subtraction=TOL,
            exact_gap_above_tolerance=True, selected_action=1),
        formal_terminal_margins=margins,
        candidate_sha256=hashlib.sha256((ROOT / "candidate.py").read_bytes()).hexdigest(),
        qualification="Observed ties unify; arbitrarily close Q arrays need not always have equal actions")
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
