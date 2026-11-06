"""Exact arithmetic qualification of designed mechanisms, not confirmation data."""
import argparse
import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from fractions import Fraction as F
from itertools import product
from pathlib import Path

from .mechanism import (Contract, Law, HALF, events, known_law_plan, gate_margin,
                        closed_form_value, score_estimate, structured_mle, confidence_decision)

ROOT = Path(__file__).parent


def verify():
    names = ("mechanism.py", "verify_mechanism.py", "protocol.json")
    before = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}
    base = Contract()
    models = {"profitable": Law(F(1), F(87, 100)), "unprofitable": Law(F(1), F(57, 100)),
              "partial_success": Law(HALF, F(87, 100)), "never_ready": Law(F(0), F(1)),
              "perfect": Law(F(1), F(1)), "boundary": Law(F(1), F(72, 100))}
    contracts = {"normal": base, "too_short": replace(base, deadline=1),
                 "costly": replace(base, probe_fee=F(1, 2)),
                 "clock_penalty": replace(base, time_price=F(1, 10)),
                 "unequal_durations": replace(base, prepare_duration=2, probe_duration=3, deadline=5),
                 "censored": replace(base, prepare_duration=2, probe_duration=3, deadline=4)}
    rows = []
    for (cn, contract), (mn, law) in product(contracts.items(), models.items()):
        value, action = known_law_plan(contract, law)
        greedy, greedy_action = known_law_plan(contract, law, "myopic")
        assert value == closed_form_value(contract, law)
        assert greedy == HALF and greedy_action[0] == "stop"
        assert (action[0] == "prepare") == (value > HALF)
        rows.append({"contract": cn, "law": mn, "dp_value": str(value), "myopic_value": str(greedy),
                     "dp_action": list(action), "myopic_action": list(greedy_action),
                     "margin": str(gate_margin(contract, law))})
    assert known_law_plan(base, models["profitable"])[0] == F(13, 20)
    assert known_law_plan(base, models["partial_success"])[0] == F(53, 100)
    count_checks = 0
    for n in range(1, 17):
        for successes in range(n + 1):
            for correct in range(successes + 1):
                score = score_estimate(base, n, successes, correct)
                fitted = structured_mle(n, successes, correct)
                assert (score > 0) == (gate_margin(base, fitted) > 0)
                count_checks += 1
    # These are count-enumeration fixtures, not generated or collected observations.
    for counts in ((1, 0, 0), (10, 10, 9), (10, 10, 7), (16, 8, 8), (16, 8, 0)):
        fitted = structured_mle(*counts)
        assert (score_estimate(base, *counts) > 0) == (known_law_plan(base, fitted)[1][0] == "prepare")
    cancellation = replace(base, prepare_duration=3, probe_duration=2, deadline=5)
    for hidden in (0, 1):
        assert events(cancellation, models["profitable"], hidden, 0, "prepare", 1) == (((-2, 1, 0), F(1)),)
        assert events(cancellation, models["profitable"], hidden, 1, "probe", 1) == (((-2, 1, 1), F(1)),)
    completion = events(cancellation, models["profitable"], 0, 0, "prepare", 3)
    assert completion[0] == ((-1, 3, 1), F(1))
    positive = confidence_decision(base, 10000, 10000, 8700, .05, 4)
    negative = confidence_decision(base, 10000, 10000, 5700, .05, 4)
    unresolved = confidence_decision(base, 1, 1, 1, .05, 4)
    assert (positive["decision"], negative["decision"], unresolved["decision"]) == ("prepare", "stop", "unresolved")
    for n, band in ((10000, positive), (10000, negative), (1, unresolved)):
        radius, bound = F(band["radius_exact"]), band["natural_log_upper_integer"]
        assert 2 * n * radius ** 2 >= bound
        assert 2 * n * (radius - F(1, 10 ** 6)) ** 2 < bound
    no_data = confidence_decision(contracts["too_short"], 0, 0, 0, .05)
    assert no_data["decision"] == "stop" and no_data["reason"] == "known_contract"
    after = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}
    assert before == after
    return {"schema": "ndu.pure-information-mechanism.v1", "status": "PASS_EXACT_DESIGNED_MECHANISMS",
            "at_utc": datetime.now(timezone.utc).isoformat(), "exact_dp_contract_law_pairs": len(rows),
            "equivalence_count_triples": count_checks, "cases": rows,
            "bands_from_constructed_counts": {"positive": positive, "negative": negative, "unresolved": unresolved},
            "actual_calibration_samples_collected": 0, "actual_confirmation_samples_collected": 0,
            "random_generators_used": False, "real_llm_calls": 0,
            "source_sha256_before": before, "source_sha256_after": after, "source_unchanged": True,
            "prior_engineering_receipt": "mechanism-before-conservative-radius.json",
            "prior_receipt_sha256": hashlib.sha256((ROOT / "evidence/mechanism-before-conservative-radius.json").read_bytes()).hexdigest(),
            "scope": "Designed exact rational examples and exhaustive integer count identities; not independent confirmation, real time execution, new RL superiority or external proof review."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = verify()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        stream.write(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({k: report[k] for k in ("status", "exact_dp_contract_law_pairs", "equivalence_count_triples", "actual_calibration_samples_collected")}))
