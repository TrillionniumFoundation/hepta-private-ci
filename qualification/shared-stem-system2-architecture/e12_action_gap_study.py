"""Create-only blind proposals and original-E12 independent mathematical review.

Execute 'propose' and 'review' as different OS processes. A reviewed outcome
only establishes a finite synthetic discrete action certificate, never a
natural-language gain, deployment authority or learned utility correctness.
"""
import argparse
from dataclasses import asdict
from fractions import Fraction as Q
from hashlib import sha256
import json
from pathlib import Path

from e12_action_gap import (AUTHORITY, BITS, evaluate_actions, make_actions,
                            rational)

SCHEMA = "hepta.e12.global-gap-decision.v1"
X0 = ("-117/128", "-79/128", "-37/128", "37/128", "79/128", "117/128")
DEPTHS = (1, 2, 3)
MAX_MAPS = 32


def canonical(data: object) -> bytes:
    return (json.dumps(data, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")


def write_once(path: str, data: object) -> str:
    dest = Path(path)
    if dest.is_symlink() or not dest.parent.is_dir():
        raise ValueError("not a fresh ordinary output file")
    with dest.open("xb") as f:
        content = canonical(data)
        f.write(content)
    return sha256(content).hexdigest()


def read_locked(path: str, digest: str) -> dict:
    src = Path(path)
    if src.is_symlink() or not src.is_file() or type(digest) is not str or len(digest) != 64:
        raise ValueError("unbound input")
    raw = src.read_bytes()
    if len(raw) > 3_000_000 or sha256(raw).hexdigest() != digest:
        raise ValueError("immutable artifact mismatch")
    data = json.loads(raw, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    if type(data) is not dict or raw != canonical(data):
        raise ValueError("noncanonical artifact")
    return data


def plan() -> dict:
    return {"schema": SCHEMA, "depths": list(DEPTHS), "x0": list(X0),
            "admissible_actions": ["direct", "coupled", "stop"],
            "cost_coupled": "1/512", "cost_direct": "0", "stop_value": "0",
            "max_total_map_evals_per_case": MAX_MAPS, "bits": BITS,
            "utility_kind": "synthetic E12 root Y minus registered toy cost",
            "source_sha256": sha256(Path(__file__).with_name("e12_action_gap.py").read_bytes()).hexdigest()}


def head_from_train(path: str, digest: str):
    """Registered E12 train-only artifact, no held teacher or labels opened."""
    if not path or not digest:
        return None
    from e12_continuation_study import _read_training
    _train, heads = _read_training(path, digest)
    return heads["neural"]


def initial_for(actions, head):
    if head is None:
        return None
    from e12_continuation_field import initial_y
    from e12_nonlinear_cert import Law as E12Law
    return {a.name: initial_y(E12Law(depth=a.law.depth, x0=a.law.x0,
                                      a=a.law.a), head) for a in actions}


def propose(out: str, training: str = "", training_sha: str = "") -> str:
    if bool(training) != bool(training_sha):
        raise ValueError("partial training identity")
    head = head_from_train(training, training_sha)
    mode = "trained-neural" if head else "zero-control"
    cases = []
    for depth in DEPTHS:
        for x0 in X0:
            actions = make_actions(x0, depth)
            outcome = evaluate_actions(actions, initial=initial_for(actions, head),
                                       max_maps=MAX_MAPS)
            cases.append({"depth": depth, "x0": x0,
                          "actions": [asdict(a) for a in actions],
                          "outcome": asdict(outcome)})
    return write_once(out, {"schema": SCHEMA + ".proposal",
                            "plan": plan(), "mode": mode,
                            "training_sha256": training_sha or None,
                            "cases": cases,
                            "authority": AUTHORITY,
                            "original_e12_teacher_called_by_proposer": False,
                            "natural_reasoning_gain_verified": False,
                            "production_accepted": False})


def _independent_review_case(case: dict, head) -> dict:
    """Recompute map with ORIGINAL E12, do not call proposer tree_map.

    An independent operator checks every interim row and full-horizon root,
    not merely the final selected action or local terminal condition.
    """
    from e12_nonlinear_cert import Law as E12Law, operator, solve
    from e12_independent_audit import audit, exact, round_even as original_round_even

    if (type(case) is not dict or set(case) != {"depth", "x0", "actions", "outcome"}
        or type(case["depth"]) is not int or case["depth"] not in DEPTHS or
        type(case["x0"]) is not str or case["x0"] not in X0):
        raise ValueError("unknown or missing case")
    depth, x0 = case["depth"], case["x0"]
    actions = make_actions(x0, depth)
    if case["actions"] != [asdict(a) for a in actions]:
        raise ValueError("action identity or cost drift")
    outcome = case["outcome"]
    if (type(outcome) is not dict or
        set(outcome) != {"selected", "cheap_one_map", "snapshots", "map_evals",
                         "forward_cell_calls", "backward_cell_calls", "cpu_ns",
                         "reason", "authority", "pretrained_model_forwards",
                         "production_accepted", "natural_task_gain_proven"} or
        outcome["authority"] != AUTHORITY or outcome["production_accepted"] is not False or
        outcome["natural_task_gain_proven"] is not False or
        outcome["pretrained_model_forwards"] != 0 or
        type(outcome["cpu_ns"]) is not int or outcome["cpu_ns"] <= 0 or
        type(outcome["map_evals"]) is not int or not 2 <= outcome["map_evals"] <= MAX_MAPS):
        raise ValueError("authority, cost or scientific disposition drift")
    histories = outcome["snapshots"]
    if type(histories) is not dict or set(histories) != {"direct", "coupled"}:
        raise ValueError("lost action or unknown branch")
    starts = initial_for(actions, head)
    oracle_values = {"stop": Q(0)}
    replay = {}
    for a in actions:
        law = E12Law(depth=depth, x0=x0, a=a.law.a)
        hist = histories[a.name]
        if type(hist) is not list or not hist:
            raise ValueError("missing filtration-adapted tree trace")
        n = (1 << depth) - 1
        expected = (Q(0),) * n if starts is None else starts[a.name]
        for row in hist:
            if (type(row) is not dict or
                set(row) != {"action", "guess", "mapped", "residual", "error_bound",
                             "lower", "upper", "cell_forwards", "cell_backwards"} or
                row["action"] != a.name or row["cell_forwards"] != n or
                row["cell_backwards"] != n or type(row["guess"]) is not list or
                type(row["mapped"]) is not list):
                raise ValueError("invalid Cell work or missing messages")
            guessed = tuple(rational(v) for v in row["guess"])
            if guessed != expected:
                raise ValueError("incorrect initial guess or Cell handoff")
            mapped = operator(law, guessed)
            M = law.values()["M"]
            rounded = tuple(max(-M, min(M, original_round_even(v, BITS))) for v in mapped)
            if tuple(map(str, rounded)) != tuple(row["mapped"]):
                raise ValueError("independent original-E12 tree disagrees")
            q = law.values()["q"]
            residual = max(abs(v - m) for v, m in zip(guessed, mapped))
            radius = residual / (1 - q)
            penalty = a.check()
            def upper_q(x):
                scaled = x * (1 << BITS)
                return Q(-(-scaled.numerator // scaled.denominator), 1 << BITS)
            radius = upper_q(radius)
            if (row["residual"] != str(upper_q(residual)) or row["error_bound"] != str(radius) or
                row["lower"] != str(guessed[0] - radius - penalty) or
                row["upper"] != str(guessed[0] + radius - penalty)):
                raise ValueError("false global certificate")
            expected = rounded
        oracle = solve(law)
        if not audit(law, oracle).certified:
            raise ValueError("original E12 teacher not independently accepted")
        true_value = rational(oracle.trace.states[0].y) - a.check()
        last = hist[-1]
        if not rational(last["lower"]) <= true_value <= rational(last["upper"]):
            # Original E12 is itself an approximate, certified value. An
            # enclosure may be narrower than its approximate center: compare
            # BOTH rigorously certified intervals instead of point inclusion.
            oracle_error = exact(oracle.fixed_point_error_bound)
            if (true_value + oracle_error < rational(last["lower"]) or
                true_value - oracle_error > rational(last["upper"])):
                raise ValueError("inconsistent certified root intervals")
        oracle_values[a.name] = true_value
        replay[a.name] = hist

    # Independently replay the deterministic global interval scheduler.
    index = {"direct": 0, "coupled": 0}
    count = 2
    def bounds():
        return {a: (rational(replay[a][index[a]]["lower"]),
                    rational(replay[a][index[a]]["upper"])) for a in index} | {"stop": (Q(0), Q(0))}
    def winner():
        b = bounds()
        possible = [a for a, (lo, _hi) in b.items()
                    if all(lo > high for k, (_low, high) in b.items() if k != a)]
        return possible[0] if len(possible) == 1 else None
    b = bounds()
    cheap_scores = {a: rational(replay[a][0]["mapped"][0]) - (
        Q(1, 512) if a == "coupled" else Q(0)) for a in index} | {"stop": Q(0)}
    top = max(cheap_scores.values())
    cheap = [a for a, score in cheap_scores.items() if score == top]
    if outcome["cheap_one_map"] != (cheap[0] if len(cheap) == 1 else "hold"):
        raise ValueError("changed low-cost control")
    selected = winner()
    while selected is None and count < MAX_MAPS:
        b = bounds()
        floor = max(lo for lo, _ in b.values())
        competitive = [a for a in ("direct", "coupled") if b[a][1] >= floor]
        if not competitive:
            break
        target = max(competitive, key=lambda a: (b[a][1] - b[a][0],
                                                 -(0 if a == "direct" else 1)))
        if index[target] + 1 >= len(replay[target]):
            break
        index[target] += 1
        count += 1
        selected = winner()
    if (outcome["map_evals"] != count or
        outcome["forward_cell_calls"] != count * ((1 << depth) - 1) or
        outcome["backward_cell_calls"] != count * ((1 << depth) - 1) or
        any(index[name] != len(rows) - 1 for name, rows in replay.items()) or
        outcome["selected"] != selected or
        outcome["reason"] != ("CERTIFIED_GAP" if selected else "HOLD_UNRESOLVED")):
        raise ValueError("control, work census or terminal claim mismatch")
    best = max(oracle_values.values())
    true_winners = [a for a, v in oracle_values.items() if v == best]
    if selected is not None and (len(true_winners) != 1 or selected != true_winners[0]):
        # Need an independently certified separation of the original oracle
        # approximations; overlapping teacher bounds cannot establish identity.
        raise ValueError("wrong selected action vs original E12 oracle")
    return {"selected": selected, "reference_best": true_winners[0] if len(true_winners) == 1 else None,
            "map_evals": count, "cheap_one_map": outcome["cheap_one_map"]}


def review(src: str, digest: str, out: str, training: str = "", training_sha: str = "") -> str:
    data = read_locked(src, digest)
    mode = "trained-neural" if training else "zero-control"
    if (type(data) is not dict or set(data) != {
            "schema", "plan", "mode", "training_sha256", "cases", "authority",
            "original_e12_teacher_called_by_proposer", "natural_reasoning_gain_verified",
            "production_accepted"} or
        data["schema"] != SCHEMA + ".proposal" or data["plan"] != plan() or
        data["mode"] != mode or data["training_sha256"] != (training_sha or None) or
        data["authority"] != AUTHORITY or
        data["original_e12_teacher_called_by_proposer"] is not False or
        data["natural_reasoning_gain_verified"] is not False or
        data["production_accepted"] is not False or
        type(data["cases"]) is not list or len(data["cases"]) != len(X0) * len(DEPTHS)):
        raise ValueError("invalid source / plan / authority bindings")
    head = head_from_train(training, training_sha)
    expected_cases = [(d, x) for d in DEPTHS for x in X0]
    if [(v["depth"], v["x0"]) for v in data["cases"]] != expected_cases:
        raise ValueError("missing or reordered source cases")
    results = [_independent_review_case(c, head) for c in data["cases"]]
    return write_once(out, {"schema": SCHEMA + ".independent-review",
                            "proposal_sha256": digest, "plan": plan(),
                            "cases": len(results),
                            "certified": sum(v["selected"] is not None for v in results),
                            "matches_reference": sum(v["selected"] == v["reference_best"]
                                                     for v in results if v["selected"] is not None),
                            "map_evals": sum(v["map_evals"] for v in results),
                            "cheap_disagreements": sum(v["selected"] is not None and
                                                     v["selected"] != v["cheap_one_map"] for v in results),
                            "authority": AUTHORITY,
                            "pretrained_model_forwards": 0,
                            "natural_reasoning_gain_verified": False,
                            "production_accepted": False})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("propose", "review"))
    parser.add_argument("--output", required=True)
    parser.add_argument("--input")
    parser.add_argument("--input-sha")
    parser.add_argument("--training", default="")
    parser.add_argument("--training-sha", default="")
    args = parser.parse_args()
    if args.mode == "propose":
        digest = propose(args.output, args.training, args.training_sha)
    else:
        if not args.input or not args.input_sha:
            parser.error("review requires --input and --input-sha")
        digest = review(args.input, args.input_sha, args.output,
                        args.training, args.training_sha)
    print(json.dumps({"sha256": digest, "mode": args.mode,
                      "authority": AUTHORITY}, sort_keys=True))


if __name__ == "__main__":
    main()
