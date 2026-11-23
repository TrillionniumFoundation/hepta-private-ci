"""Bound all six-prefix terminal decisions using the two published, hash-checked input packages."""
import argparse
from collections import Counter
from fractions import Fraction
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from qualification.hcsn_blocker_followup.experiment import panel
from qualification.hcsn_intervention_value.independent import opportunity, outcome
from qualification.hcsn_intervention_value.replay import unpack


def sign_bound(deltas):
    nonzero = [v for v in deltas if abs(v) > 1e-12]
    wins = sum(v > 0 for v in nonzero)
    return str(Fraction(sum(math.comb(len(nonzero), j) for j in range(wins, len(nonzero) + 1)), 2 ** len(nonzero)))


def measure(data):
    target = data["target"][:, None]
    free = data["scores"].argmax(-1) == target
    paid = data["read_scores"].argmax(-1) == target
    durations = data["dt"][:, 1:]
    assert np.allclose(durations, .48, atol=1e-12, rtol=0)
    elapsed = np.c_[np.zeros(len(free)), np.cumsum(durations, axis=1)]
    discount = np.exp(-.20 * elapsed)
    terminal = np.stack([free, paid.astype(float) - .30], axis=2)
    values = discount[:, :, None] * terminal + 2 * np.expm1(-.20 * elapsed[:, :, None])
    best_flat = values.reshape(len(free), 12).argmax(axis=1)
    joint = values.reshape(len(free), 12).max(axis=1)
    direct = outcome(data, best_flat // 2, best_flat % 2)
    assert np.allclose(joint, direct["episode_utility"], atol=1e-12, rtol=0)
    # Independent backward induction in local time via the one-step discounted continuation.
    backward = terminal[:, -1, :].max(axis=1)
    for prefix in range(4, -1, -1):
        duration = durations[:, prefix]
        continuation = np.exp(-.20 * duration) * backward + 2 * np.expm1(-.20 * duration)
        backward = np.maximum(terminal[:, prefix, :].max(axis=1), continuation)
    assert np.allclose(joint, backward, atol=1e-12, rtol=0)
    source = {}
    immediate = values[:, 0, :].max(axis=1)
    for group in sorted(set(data["group"])):
        ix = data["group"] == group
        source[str(group)] = {"queries": int(ix.sum()), "joint": float(joint[ix].mean()),
            "gain_vs_free_now": float((joint[ix]-values[ix, 0, 0]).mean()),
            "gain_vs_paid_now": float((joint[ix]-values[ix, 0, 1]).mean()),
            "wait_gain_vs_best_now": float((joint[ix]-immediate[ix]).mean())}
    expected = opportunity(data)
    gains = {key: float(np.mean([row[key] for row in source.values()])) for key in next(iter(source.values())) if key != "queries"}
    assert abs(gains["joint"] - expected["oracle_joint_macro"]) <= 1e-12
    assert abs(gains["wait_gain_vs_best_now"] - expected["wait_gain_mean"]) <= 1e-12
    p = [sign_bound(row[key] for row in source.values()) for key in ("gain_vs_free_now", "gain_vs_paid_now")]
    a, b = sorted(map(Fraction, p))
    by_start = Counter()
    for i, best in enumerate(best_flat):
        if best >= 2:
            start = "both_initially_wrong" if immediate[i] == 0 else "only_paid_initially_correct"
            assert not free[i, 0]
            by_start[(start, int(best // 2), ("free", "paid")[best % 2])] += 1
    return {"queries":len(free), "sources":source, "source_macro":gains,
        "number_of_joint_terminal_assignments":str(12**len(free)),
        "minimum_sign_p_vs_immediate_free_then_paid":p, "dual_holm_statistically_possible":a<=Fraction(1,40) and b<=Fraction(1,20),
        "original_wait_opportunity_gate":expected["wait_gate_pass"],
        "waiting_queries":int((joint-immediate>1e-12).sum()),
        "optimal_waits_by_initial_status_elapsed_steps_and_terminal_action":[[*key,value] for key,value in sorted(by_start.items())]}


def main(qualification):
    with TemporaryDirectory() as temp:
        root = Path(temp)
        unpack(qualification/"hcsn_intervention_value/evidence", root/"old")
        unpack(qualification/"hcsn_blocker_followup/evidence", root/"new")
        result = {}
        for split in ["train", "dev", "test"]:
            data, bindings = panel(root/"new/media", root/"old/primary/discovery", split)
            result[split] = {"input_sha256":bindings, **measure(data)}
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("qualification", type=Path)
    print(json.dumps(main(parser.parse_args().qualification), indent=2, sort_keys=True))
