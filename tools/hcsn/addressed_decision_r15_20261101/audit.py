"""Independent numerical and behavioral checks for the finite R15 experiment.

The Poisson series, occupation ODE, scalar decision recursion, and HMM filter
below do not call their production counterparts. They audit a finite generator;
passing does not establish convergence to a continuum free-boundary model.
"""

import argparse
import copy
import json
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp
from scipy.stats import poisson


def uniformization(generator, duration, tolerance=3e-14):
    """Independent Poisson series for a conservative or killed row generator."""
    q = np.asarray(generator, dtype=float)
    duration = float(duration)
    if q.ndim != 2 or q.shape[0] != q.shape[1] or not np.isfinite(q).all():
        raise ValueError("Expected a finite square generator")
    if not np.isfinite(duration) or duration < 0:
        raise ValueError("Duration must be finite and nonnegative")
    off = q.copy()
    np.fill_diagonal(off, 0)
    if np.min(off) < -1e-14 or np.max(q.sum(1)) > 1e-11:
        raise ValueError("Uniformization requires a conservative or killed generator")
    identity = np.eye(len(q))
    rate = float(np.max(-np.diag(q)))
    if duration == 0 or rate == 0:
        return identity
    pieces = max(1, int(np.ceil(rate * duration / 12)))
    intensity = rate * duration / pieces
    step = identity + q / rate
    power = identity.copy()
    weight = float(np.exp(-intensity))
    result = weight * power
    order = 0
    while poisson.sf(order, intensity) > tolerance / pieces:
        order += 1
        power = power @ step
        weight *= intensity / order
        result += weight * power
        if order > 10000:
            raise RuntimeError("Poisson reference did not converge")
    return np.linalg.matrix_power(result, pieces)


def marked_generator(law):
    """Independently mark natural active-to-recovery absorption transitions."""
    phase = np.arange(law.state_count) // law.class_count
    marked = (phase[:, None] < law.n_active) & (phase[None, :] >= law.n_active)
    rates = np.where(marked, law.Q, 0).sum(1)
    killed = law.Q.copy()
    killed[marked] = 0
    return killed, rates


def count_by_ode(generator, initial, rate, duration):
    """Integrate probability and accumulated event occupation together."""
    q, initial, rate = map(np.asarray, (generator, initial, rate))
    def derivative(_, state):
        return np.r_[state[:-1] @ q, state[:-1] @ rate]
    answer = solve_ivp(derivative, (0., float(duration)), np.r_[initial, 0.],
                       method="DOP853", rtol=2e-11, atol=2e-13)
    if not answer.success:
        raise AssertionError(answer.message)
    return float(answer.y[-1, -1])


def correlation_witness(law):
    """Equal marginals need not determine posterior or observation value.

    This is a constructed state witness, not a confirmation-history claim.
    One source is either active with content 0 or recovering with content 1.
    The independent product has identical phase and content marginals.
    """
    coupled = np.zeros(law.state_count)
    coupled[0] = coupled[law.n_active * law.class_count + 1] = .5
    joint = coupled.reshape(law.phase_count, law.class_count)
    independent = np.outer(joint.sum(1), joint.sum(0)).ravel()
    def outcome_values(p):
        weighted = p[:, None] * law.E_read
        content_outcome = weighted.reshape(law.phase_count, law.class_count, -1).sum(0)
        return float(content_outcome.max(0).sum())
    before = float((coupled @ law.reward).max())
    a, b = outcome_values(coupled), outcome_values(independent)
    # A fee between the two information gains gives opposite READ/STOP choices.
    diagnostic_fee = (a + b) / 2 - before
    return dict(coupled=coupled, independent=independent,
                marginal_error=float(np.max(np.abs(
                    law.project(coupled, "factorized") - independent))),
                current_correctness=before,
                coupled_read_correctness=a, independent_read_correctness=b,
                read_gain_gap=a - b, diagnostic_fee=diagnostic_fee,
                coupled_reads=a - diagnostic_fee > before,
                independent_stops=b - diagnostic_fee < before,
                scope="constructed joint-state witness; no elapsed-time or reachability claim")


def numerical_audit(law):
    """Compare production propagation/events against separate algorithms."""
    rng = np.random.default_rng(150419)
    initial = rng.dirichlet(np.ones(law.state_count))
    initial[:4] += .3
    initial /= initial.sum()
    killed, rate = marked_generator(law)
    errors, rows, negatives, hits, counts = [], [], [], [], []
    for dt in (.07, .65, 2.3):
        transition = law.transition(dt)
        reference = uniformization(law.Q, dt)
        errors.append(float(np.max(np.abs(transition - reference))))
        rows.append(float(np.max(np.abs(transition.sum(1) - 1))))
        negatives.append(float(np.min(transition)))
        hit_reference = float(1 - initial @ uniformization(killed, dt) @ np.ones(law.state_count))
        count_reference = count_by_ode(law.Q, initial, rate, dt)
        hit, count = float(law.first_hit(initial, dt)), float(law.event_count(initial, dt))
        hits.append(dict(dt=dt, computed=hit, reference=hit_reference,
                         error=abs(hit - hit_reference)))
        counts.append(dict(dt=dt, computed=count, reference=count_reference,
                           error=abs(count - count_reference)))
        assert -1e-12 <= hit <= 1 + 1e-12 and count >= hit - 1e-11
    composition = float(np.max(np.abs(
        law.transition(.37) @ law.transition(.61) - law.transition(.98))))
    long_time = 8.
    while law.event_count(initial, long_time) <= 1.05 and long_time < 4096:
        long_time *= 4
    repeated = float(law.event_count(initial, long_time))
    first = float(law.first_hit(initial, long_time))
    assert max(errors) < 3e-11 and max(rows) < 2e-11 and min(negatives) > -1e-12
    assert composition < 3e-11
    assert max(item["error"] for item in hits) < 3e-10
    assert max(item["error"] for item in counts) < 3e-9
    assert repeated > 1.05 and first <= 1 + 1e-10 and repeated > first
    witness = correlation_witness(law)
    assert witness["marginal_error"] < 1e-14
    assert witness["read_gain_gap"] > .1
    assert witness["coupled_reads"] and witness["independent_stops"]
    return dict(passed=True, independent_reference="Poisson series and DOP853 occupation ODE",
                expm_uniformization_max_error=max(errors), stochastic_row_error=max(rows),
                minimum_transition_entry=min(negatives), semigroup_error=composition,
                first_hit=hits, event_count=counts,
                repeated_events=dict(duration=long_time, expected_count=repeated,
                                     probability_at_least_one=first),
                correlation={k: v for k, v in witness.items()
                             if k not in ("coupled", "independent")})


def reference_values(law, p, dt, remaining, read_cost=.025, refresh_cost=.07, time_price=.003):
    """Slow scalar Bayes tree for current-query finite-deadline control."""
    transitions = {j: uniformization(law.Q, j * dt) for j in range(remaining + 1)}
    def solve(belief, left):
        values = {"STOP": float((belief @ transitions[left] @ law.reward).max())}
        if left == 0:
            return values
        predicted = belief @ transitions[1]
        values["WAIT"] = -time_price * dt + max(solve(predicted, left - 1).values())
        for action, steps, cost, emission in (
                ("READ", 1, read_cost, law.E_read),
                ("REFRESH", 2, refresh_cost, law.E_refresh)):
            if steps > left:
                continue
            advanced = belief @ transitions[steps]
            expected = 0.
            for likelihood in emission.T:
                weight = advanced * likelihood
                probability = float(weight.sum())
                if probability > 0:
                    expected += probability * max(solve(weight / probability, left - steps).values())
            values[action] = expected - cost - steps * dt * time_price
        return values
    return solve(np.asarray(p), int(remaining))


def behavior_audit(law):
    """Exercise deployed memory, planner, world tape, and checkpoint behavior."""
    from .law import Law
    from .planner import BeliefMemory, Planner
    from .world import make_episode

    memory = BeliefMemory(law, [0, 1, 2, 3])
    before = memory.beliefs.copy()
    memory.advance(.41)
    reference = before @ uniformization(law.Q, .41)
    advance_error = float(np.max(np.abs(memory.beliefs - reference)))
    assert advance_error < 3e-11
    assert all(np.max(np.abs(memory.beliefs[k] - before[k])) > 1e-8 for k in range(4))
    prior_observation = memory.beliefs.copy()
    memory.observe(2, 2, "read")
    untouched = [0, 1, 3]
    assert np.array_equal(memory.beliefs[untouched], prior_observation[untouched])
    weight = reference[2] * law.E_read[:, 2]
    reference[2] = weight / weight.sum()
    hmm_error = float(np.max(np.abs(memory.beliefs - reference)))
    assert hmm_error < 3e-11
    phase = memory.beliefs[1].reshape(10, 4).sum(1)
    old_other = memory.beliefs[[0, 2, 3]].copy()
    memory.write(1, 3)
    assert np.allclose(memory.beliefs[1].reshape(10, 4).sum(1), phase, atol=1e-14)
    assert np.array_equal(memory.beliefs[[0, 2, 3]], old_other)
    assert np.allclose(memory.beliefs[1] @ law.reward, [0, 0, 0, 1], atol=1e-14)

    payload = json.loads(json.dumps(memory.checkpoint(), allow_nan=False))
    same_matrix_hmm = Law.from_payload(json.loads(json.dumps(law.export(), allow_nan=False)))
    restored = BeliefMemory.restore(same_matrix_hmm, payload)
    for candidate in (memory, restored):
        candidate.advance(.19)
        candidate.observe(3, 0, "refresh")
        candidate.advance(.31)
        candidate.observe(0, 1, "read")
    assert memory.clock == restored.clock
    assert np.array_equal(memory.beliefs, restored.beliefs)
    planner = Planner(law, .35)
    hmm_planner = Planner(same_matrix_hmm, .35)
    all_actions_equal = all(planner.choose(memory.beliefs[k], 3) ==
                            hmm_planner.choose(restored.beliefs[k], 3) for k in range(4))
    assert all_actions_equal
    recursive_errors = []
    for key, horizon in ((0, 2), (2, 3)):
        actual = planner.values(memory.beliefs[key], horizon)
        expected = reference_values(law, memory.beliefs[key], .35, horizon)
        assert set(actual) == set(expected)
        recursive_errors.extend(abs(float(actual[a]) - expected[a]) for a in expected)
    assert max(recursive_errors) < 2e-10
    expensive = Planner(law, .35, refresh_cost=2.)
    expensive_values = [expensive.values(p, 3) for p in memory.beliefs]
    assert all(v["REFRESH"] < v["STOP"] for v in expensive_values)
    assert all(expensive.choose(p, 3) != "REFRESH" for p in memory.beliefs)

    episode = make_episode(law, 150419, "iid")
    replay = make_episode(law, 150419, "iid")
    assert episode.fingerprint == replay.fingerprint
    targets_before = [episode.target(int(k), float(t))
                      for k, t in zip(episode.query_keys, episode.deadlines)]
    requests = [(int(episode.query_keys[q]), float(episode.starts[q] + 2 * episode.dts[q]),
                 "refresh", q, 2) for q in range(len(episode.query_keys))]
    observed = [episode.observe(*request) for request in requests]
    reversed_observed = [replay.observe(*request) for request in reversed(requests)]
    assert observed == list(reversed(reversed_observed))
    # An agent-only reinitialization cannot alter the shared external tape.
    BeliefMemory(law, episode.initial_values)
    targets_after = [episode.target(int(k), float(t))
                     for k, t in zip(episode.query_keys, episode.deadlines)]
    assert targets_before == targets_after
    assert observed == [episode.observe(*request) for request in requests]
    try:
        episode.observe(int(episode.query_keys[0]), float(episode.starts[0]), "read", 0, 1)
    except ValueError:
        pass
    else:
        raise AssertionError("Observation leaked before its completion timestamp")
    try:
        episode.observe(int(episode.query_keys[0]), float(episode.starts[0] + episode.dts[0]),
                        "refresh", 0, 1)
    except ValueError:
        pass
    else:
        raise AssertionError("REFRESH completed in less than two stages")
    return dict(passed=True, all_address_advance_error=advance_error,
                addressed_observation_isolation=True, typed_write_preserves_phase=True,
                independent_same_matrix_hmm_error=hmm_error,
                checkpoint_replay_exact=True, same_matrix_hmm_actions_identical=all_actions_equal,
                scalar_dp_max_error=max(recursive_errors),
                high_refresh_price_dominance=True, world_replay_fingerprint=episode.fingerprint,
                observation_order_invariant=True, no_early_observation=True,
                internal_reinitialization_changes_world=False,
                planner_scope="current query finite deadline; not six-query global optimality")


def world_event_audit(law):
    """Check real WRITE/DISTRACTOR behavior and score-before-write boundaries.

    A deterministic readout on an isolated audit copy makes this timing test
    exact. It does not change confirmation's noisy observation channels.
    """
    from .world import make_episode
    diagnostic = copy.copy(law)
    diagnostic.E_refresh = law.reward
    diagnostic.identity = "audit-noiseless-readout:" + law.identity
    writes = changed = distractors = boundaries = 0
    for domain in ("iid", "ood"):
        for seed in (150431, 150433, 150437, 150439):
            episode = make_episode(diagnostic, seed, domain)
            for query in range(6):
                events = episode.events_at(query)
                for event in events:
                    key, at = event["key"], event["time"]
                    before = episode._state_at(key, at, side="left")
                    after = episode._state_at(key, at, side="right")
                    if event["kind"] == "WRITE":
                        writes += 1
                        changed += int(before % 4 != after % 4)
                        assert before // 4 == after // 4
                        assert after % 4 == event["value"]
                        assert episode.target(key, at) == before % 4
                        previous = query - 1
                        supplied_time = float(episode.starts[previous] + 3 * episode.dts[previous])
                        token = episode.observe(key, supplied_time, "refresh", previous, 3)
                        assert token == before % 4
                        boundaries += 1
                        for other in range(4):
                            if other != key:
                                assert episode._state_at(other, at, "left") == episode._state_at(other, at, "right")
                    elif event["kind"] == "DISTRACTOR":
                        distractors += 1
                        assert before == after
                    else:
                        raise AssertionError("Unexpected public event type")
                # The caller receives copies, not writable world-owned metadata.
                if events:
                    events[0]["value"] = -999
                    assert episode.events_at(query)[0]["value"] != -999
    assert changed > 0 and writes == boundaries
    return dict(passed=True, public_writes_checked=writes,
                content_changing_writes_checked=changed, distractors_checked=distractors,
                pre_write_deadline_observations_checked=boundaries,
                phase_preserved_on_write=True, event_metadata_returned_as_copies=True,
                scope="isolated deterministic sensor audit; noisy confirmation unchanged")


def run_all_audits(law=None, include_behavior=True):
    from .law import Law
    law = Law() if law is None else law
    report = dict(schema="hcsn-r15-independent-audit-v1", law_identity=law.identity,
                  numerics=numerical_audit(law))
    if include_behavior:
        report["behavior"] = behavior_audit(law)
        report["public_events"] = world_event_audit(law)
    report["passed"] = True
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--numerics-only", action="store_true")
    args = parser.parse_args()
    report = run_all_audits(include_behavior=not args.numerics_only)
    rendered = json.dumps(report, indent=2, sort_keys=True, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n")
    print(rendered)


if __name__ == "__main__":
    main()
