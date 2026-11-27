"""Synthetic arithmetic/protocol controls. No Torch import, model, raw task data or fitting."""
import ast
from fractions import Fraction
import json
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

import numpy as np

from static_support import Ledger, choose, eligible, exact_norm2, flat_from_matrix, metrics, realized, role_ids, trust_region, write_json
from supervise import parse_limits, stop_child


def rejects(call, error=ValueError):
    try:
        call()
    except error:
        return
    raise AssertionError("frozen failure control was accepted")


def main():
    checks = []
    parent = np.linspace(-.5, .5, 40, dtype="float32")
    candidate, budget = realized(parent, np.ones(40))
    assert exact_norm2(candidate, parent) <= 1
    assert exact_norm2(candidate, parent) == Fraction(int(budget["norm2_numerator"]), int(budget["norm2_denominator"]))
    assert budget["norm"] > .99
    checks.append("actual F32 radius with exact dyadic witness")
    tiny = np.zeros(40, dtype="float32")
    tiny[0] = np.nextafter(np.float32(0), np.float32(1))
    assert exact_norm2(tiny, np.zeros(40, dtype="float32")) == Fraction(1, 2**298)
    checks.append("subnormal coordinate is not rounded to a zero real displacement")
    zero, _ = realized(parent, np.ones(40), Fraction(0))
    assert zero.tobytes() == parent.tobytes()
    rejects(lambda: realized(parent, np.full(40, np.nan)))
    rejects(lambda: exact_norm2(parent, np.full(40, np.inf)))
    rejects(lambda: realized(parent, np.ones(40), Fraction(-1)))
    checks.append("zero ball and nonfinite/negative budget rejection")
    identity = np.eye(10)
    target = np.zeros((10, 4))
    target[0, 0] = .2
    small, proof = trust_region(identity, target, identity)
    assert np.max(np.abs(small - target / 1.45)) < 1e-13
    assert proof["multiplier"] == 0
    checks.append("closed-form diagonal protected ridge solution")
    large, proof = trust_region(identity, target * 100, identity)
    assert np.linalg.norm(large) <= 1 + 1e-14 and np.linalg.norm(large) >= 1 - 1e-12
    assert proof["multiplier"] > 0 and proof["kkt_max_abs"] < 1e-11
    rejects(lambda: trust_region(identity, target[:, :3], identity))
    rejects(lambda: trust_region(identity, target, identity, 0.))
    checks.append("active trust-region boundary and KKT/dimension controls")
    assert np.array_equal(role_ids(np.array([0, 1])), [1, 0, 0, 1])
    assert np.array_equal(role_ids(np.array([1, 0])), [0, 1, 1, 0])
    assert np.array_equal(flat_from_matrix(np.arange(40).reshape(10, 4)),
                          np.concatenate((np.arange(40).reshape(10, 4)[:9].T.ravel(), np.arange(36, 40))))
    rejects(lambda: role_ids(np.array([2])))
    checks.append("semantic match roles are separate from candidate positions and matrix coordinates")
    labels = np.array([0, 1])
    good = np.array([[1., -1.], [-1., 1.]], dtype="float32")
    bad = good.copy(); bad[0] = bad[0, ::-1]
    assert eligible(good, good, labels) and not eligible(bad, good, labels)
    assert metrics(good, labels)["correct"] == 2
    assert metrics(-good, labels)["correct"] == 0
    rejects(lambda: metrics(good, np.array([0, 2])))
    checks.append("actual score protection catches a formerly correct regression")
    keep = dict(name="KEEP", dev=dict(correct=3, brier=.2), norm=0., declaration_index=0)
    tie = dict(name="candidate", dev=dict(correct=3, brier=.2), norm=0., declaration_index=1)
    better_brier = dict(name="candidate", dev=dict(correct=3, brier=.1), norm=.1, declaration_index=1)
    better_count = dict(name="candidate", dev=dict(correct=4, brier=.8), norm=.9, declaration_index=2)
    assert choose([tie, keep])["name"] == "KEEP"
    assert choose([keep, better_brier]) is better_brier
    assert choose([keep, better_brier, better_count]) is better_count
    checks.append("frozen full lexicographic selection and KEEP ties")
    with tempfile.TemporaryDirectory() as directory:
        ledger = Ledger(Path(directory), time.monotonic())
        ledger.charge("forwards", 33)
        rejects(lambda: ledger.charge("forwards"), RuntimeError)
        rejects(lambda: ledger.charge("forwards", -1))
        rejects(lambda: ledger.charge("unlisted"))
        ledger.charge("trace_linear_replays", 6)
        rejects(lambda: ledger.charge("trace_linear_replays"), RuntimeError)
    checks.append("started-call budget caps and trace-only linear work cap")
    limits = {"memory.max": "1073741824", "cpu.max": "100000 100000", "pids.max": "64"}
    assert parse_limits(limits)["memory_max_bytes"] == 1073741824
    for name, value in (("memory.max", "max"), ("memory.max", "2147483648"),
                        ("cpu.max", "max 100000"), ("cpu.max", "200000 100000"), ("pids.max", "65")):
        rejects(lambda n=name, v=value: parse_limits(dict(limits, **{n: v})))
    checks.append("missing/loose dedicated memory, CPU and task caps fail closed")
    with patch("supervise.os.killpg", side_effect=ProcessLookupError), patch("supervise.os.kill") as direct:
        stop_child(12345)
        direct.assert_called_once()
        assert direct.call_args.args[0] == 12345
    checks.append("owned-child pre-setsid cleanup falls back to direct termination without any real signal")
    here = Path(__file__).resolve().parent
    protocol = json.loads((here / "PROTOCOL.json").read_text())
    assert protocol["proposed_new_budget"]["python_complete_six_tick_rollouts"] == 3 + 2 + 16 + 12 == 33
    assert 3 * 2 + 2 * 70 + 16 * 8 + 12 * 70 == 1114
    assert protocol["proposed_new_budget"]["backward_calls"] == 1 + 16
    for source in here.glob("*.py"):
        ast.parse(source.read_text(), filename=str(source))
    assert "torch" not in sys.modules
    checks.append("declared whole budget and syntax without any Torch import")
    write_json(Path(sys.argv[1]), dict(status="PASS", controls=checks, count=len(checks),
                                     model_calls=0, backward_calls=0, task_data_access=False,
                                     synthetic_quadratic_controls_only=True))


if __name__ == "__main__":
    main()
