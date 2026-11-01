"""Check the candidate without rerunning or replacing confirmation outcomes."""

from fractions import Fraction
import hashlib
import json
from pathlib import Path

import numpy as np

from candidate import CONTROLLER, SOURCE, resolve_action, wrapped_plan

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name, data):
    path = ROOT / name
    if path.exists():
        raise ValueError(f"Refusing to overwrite {path}")
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")


def decode(values):
    return np.asarray([-np.inf if x is None else x for x in values])


def main():
    before = sha(SOURCE)
    fixtures = [([.5, .5, -np.inf, -np.inf], 0),
                ([.5, .5 + 5e-13, -np.inf, -np.inf], 0),
                ([.5, .5 + 2e-12, -np.inf, -np.inf], 1),
                ([-np.inf, -3., -3. + 2e-13, -np.inf], 1),
                ([-1e308, 1e308, -np.inf], 1),
                ([-np.inf, -np.inf, -.25], 2)]
    for q, expected in fixtures:
        snapshot = np.array(q)
        actual = resolve_action(snapshot)
        assert actual == expected and np.array_equal(snapshot, q)
    assert resolve_action(np.empty((0, 4))).shape == (0,)
    invalid = [np.nan, [], [[]], [[[1.]]], [np.nan, 1.], [np.inf, 1.],
               [-np.inf, -np.inf], [[1., 0.], [-np.inf, -np.inf]], [1j, 0j],
               [True, False], ["0.5", "0.6"], [None, .5]]
    invalid_checks = []
    for q in invalid:
        try:
            resolve_action(q)
        except ValueError:
            invalid_checks.append(True)
        else:
            raise AssertionError(f"Invalid Q accepted: {q!r}")
    for tol in (-1., np.nan, np.inf, True, [1e-12], "1e-12"):
        try:
            resolve_action([.5, .5], tol)
        except ValueError:
            invalid_checks.append(True)
        else:
            raise AssertionError(f"Invalid tolerance accepted: {tol!r}")
    # Independent exact-rational audit of the represented-value tolerance rule.
    rng = np.random.default_rng(2026103112)
    q = rng.normal(size=(512, 4))
    q[:, 1] = q[:, 0] + rng.choice([0., 2e-13, 8e-13, 2e-12], len(q))
    q[:, 2:] = q[:, [0]] - .1
    q[::7, 0] = -np.inf
    q.setflags(write=False)
    action = resolve_action(q)
    exact_tol = Fraction.from_float(1e-12)
    rational_gaps = []
    for row, selected in zip(q, action):
        maximum = Fraction.from_float(float(max(row)))
        eligible = [i for i, v in enumerate(row) if np.isfinite(v)
                    and maximum - Fraction.from_float(float(v)) <= exact_tol]
        assert selected == min(eligible)
        gap = maximum - Fraction.from_float(float(row[selected]))
        assert 0 <= gap <= exact_tol
        rational_gaps.append(float(gap))
    assert np.array_equal(resolve_action(q, 0.), np.argmax(q, axis=1))
    # The actual planner changes its returned selected value on a near tie.
    p = np.array([[.5, .5], [.25, .75]])
    transition = np.eye(2)
    emission = np.full((2, 7), 1/7)
    rewards = np.array([[1., 1. + 1e-12], [0., 0.]])
    costs = np.full(2, .03)
    inputs = [p, transition, emission, rewards, costs]
    copies = [x.copy() for x in inputs]
    for x in inputs:
        x.setflags(write=False)
    ordinary = CONTROLLER.plan(*inputs, horizon=1)
    resolved = wrapped_plan(*inputs, horizon=1)
    assert np.array_equal(resolved.qvalues, ordinary.qvalues)
    assert np.array_equal(resolved.action, [0, 0])
    assert np.array_equal(resolved.value, resolved.qvalues[np.arange(2), resolved.action])
    assert np.all(resolved.value < ordinary.value)
    assert all(np.array_equal(x, y) for x, y in zip(inputs, copies))
    # General expected-Q regret bound: true max - selected <= 2 eps + tol.
    true_q = rng.normal(size=(512, 4))
    true_q[:, 1] = true_q[:, 0] + rng.uniform(-2e-3, 2e-3, 512)
    eps = 1e-3
    approximate = true_q + rng.uniform(-eps, eps, true_q.shape)
    choices = resolve_action(approximate)
    regret = true_q.max(1) - true_q[np.arange(len(choices)), choices]
    assert np.all(regret <= 2*eps + 1e-12)
    review_path = ROOT.parent / "review" / "raw.json"
    review = json.loads(review_path.read_text())
    formal_rows = []
    for episode in review["ties"]:
        steps = []
        for pair in episode["trace"]:
            arms = {}
            for name in ("D", "HMM"):
                row = pair[name]
                values = decode(row["qvalues"])
                original, selected = int(np.argmax(values)), resolve_action(values)
                assert original == row["action"]
                arms[name] = dict(step=row["step"], dt=row["dt"], original=original, resolved=selected,
                    qvalues=row["qvalues"], selected_q=float(values[selected]),
                    loss_from_max=float(max(values)-values[selected]), history=row["history_before"], tokens=row["tokens_before"])
            assert arms["D"]["resolved"] == arms["HMM"]["resolved"]
            assert arms["D"]["history"] == arms["HMM"]["history"]
            assert arms["D"]["tokens"] == arms["HMM"]["tokens"]
            steps.append(arms)
        formal_rows.append(dict(seed=episode["seed"], domain=episode["domain"],
            episode_index_zero_based=episode["episode_index_zero_based"], steps=steps,
            replay_matches_frozen=episode["replay_matches_frozen"]))
    assert len(formal_rows) == 5
    write("ACTUAL_Q_PAIRS.json", dict(rows=formal_rows, source_path=str(review_path.relative_to(ROOT.parent)),
        source_payload_sha256_at_read=sha(review_path), source_ties_sha256=hashlib.sha256(
            json.dumps(review["ties"], sort_keys=True).encode()).hexdigest(),
        original_freeze_sha256=review["provenance"]["FREEZE.json"],
        original_confirmation_sha256=review["provenance"]["CONFIRMATION.json"],
        scope="Post-confirmation selection on recorded Q-values only; no new episode or changed primary result"))
    dev_path = ROOT.parent / "mechanisms" / "TIE_DIAGNOSTIC.json"
    dev = json.loads(dev_path.read_text())["different_episodes"][0]
    dev_values = [decode(dev["evaluations"][arm][-1]["qvalues"]) for arm in ("constant", "fast")]
    dev_actions = [resolve_action(values) for values in dev_values]
    assert dev_actions == [0, 0]
    assert before == sha(SOURCE)
    write("EVIDENCE.json", dict(candidate_sha256=sha(ROOT / "candidate.py"),
        controller_sha256_before=before, controller_sha256_after=sha(SOURCE),
        tolerance=1e-12, explicit_valid_fixtures=len(fixtures), invalid_rejected=len(invalid_checks),
        exact_rational_rows=len(q), maximum_selected_Q_loss=max(rational_gaps),
        zero_tolerance_matches_argmax=True, readonly_inputs_unchanged=True, wrapper_qvalues_unchanged=True,
        wrapper_selected_values=resolved.value.tolist(), original_max_values=ordinary.value.tolist(),
        empirical_bound_test=dict(rows=len(regret), epsilon=eps, maximum_regret=float(regret.max()), bound=2*eps+1e-12),
        actual_formal_ties_unified=len(formal_rows), checked_formal_steps=sum(len(x["steps"]) for x in formal_rows),
        development_episode=dev["episode"], development_original_actions=[int(np.argmax(v)) for v in dev_values],
        development_resolved_actions=dev_actions, development_source_sha256=sha(dev_path),
        qualification="Post-confirmation numerical repair candidate only; not a new quality or significance result"))
    print(json.dumps(dict(formal_ties_unified=len(formal_rows), development_resolved=dev_actions,
                         invalid_rejected=len(invalid_checks), rational_rows=len(q)), indent=2))


if __name__ == "__main__":
    main()
