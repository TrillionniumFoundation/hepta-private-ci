"""Independent complete-state, gradient, checkpoint and conditional-data audits."""
import json
import time
import numpy as np
import jax
import jax.numpy as jnp
from identity import HERE, protocol, save, sha, verify
from network import features, initialize, forward, numpy_forward, loss
from oracle import Bellman, features as old_features
from training_v2 import metrics


def validate_numerical():
    start, cpu = time.perf_counter(), time.process_time()
    rng = np.random.default_rng(2026103091)
    parameters = {k: jnp.asarray(v, jnp.float64) for k, v in initialize(0).items()}
    x = jnp.asarray(rng.normal(size=(7, 84)))
    target = jnp.asarray(rng.normal(size=(7, 4)))
    valid = rng.random((7, 4)) > .35
    valid[:, 0] = True
    valid = jnp.asarray(valid)
    direction = {k: jnp.asarray(rng.normal(size=v.shape)) for k, v in parameters.items()}
    norm = np.sqrt(sum(float(jnp.sum(v*v)) for v in direction.values()))
    direction = {k: v/norm for k, v in direction.items()}
    gradient = jax.grad(loss)(parameters, x, target, valid)
    analytic = sum(float(jnp.sum(gradient[k]*direction[k])) for k in gradient)
    errors = []
    for eps in (1e-4, 3e-5):
        plus = {k: v+eps*direction[k] for k, v in parameters.items()}
        minus = {k: v-eps*direction[k] for k, v in parameters.items()}
        finite = float((loss(plus, x, target, valid)-loss(minus, x, target, valid))/(2*eps))
        errors.append(abs(finite-analytic)/max(1., abs(analytic)))
    changed = jnp.where(valid, target, 999.)
    altered_gradient = jax.grad(loss)(parameters, x, changed, valid)
    mask_error = max(float(jnp.max(jnp.abs(gradient[k]-altered_gradient[k]))) for k in gradient)
    assert mask_error == 0. and float(loss(parameters, x, target, valid)) == float(loss(parameters, x, changed, valid))
    np_error = float(np.max(np.abs(np.asarray(forward(parameters, x))-numpy_forward({k: np.asarray(v) for k, v in parameters.items()}, np.asarray(x)))))
    confusion = np.array([[.99, .01], [.01, .99]])
    base = dict(deadline=8, budget=3, reliability=[[.74]*8, [.58]*8], price=[[.06]*8, [.12]*8])
    better = dict(deadline=8, budget=3, reliability=[[.74]*8, [.9]*8], price=[[.06]*8, [.02]*8])
    args = (0, 0, 3, .9, confusion, 1.5)
    old_same = np.array_equal(old_features(base, *args), old_features(better, *args))
    full_a, full_b = features(base, *args), features(better, *args)
    q_a, q_b = Bellman(base, confusion, 1.5).q(0, 0, 3, .9)[3], Bellman(better, confusion, 1.5).q(0, 0, 3, .9)[3]
    assert old_same and not np.array_equal(full_a, full_b) and abs(q_a-q_b) > .1
    qualities = full_a[40:60].reshape(2, 10)
    prices = full_a[60:80].reshape(2, 10)/1.5
    assert np.array_equal(qualities[:, :8], base["reliability"])
    assert np.allclose(prices[:, :8], base["price"], atol=1e-15, rtol=0.)
    assert np.array_equal(full_a[80:84].reshape(2, 2), confusion)
    assert int(np.count_nonzero(qualities[0]))-int(round(full_a[3]*10)) == 0
    assert round(full_a[4]*4) == 3 and full_a[5] == 0 and full_a[1] == .9
    one = dict(deadline=2, budget=1, reliability=[[.8]*2]*2, price=[[.05]*2]*2)
    law = np.array([[.9, .1], [.1, .9]])
    value = Bellman(one, law, 1.).q(0, 0, 1, .5)[2]
    independent = 2*(.8*.9+.2*.1)-1-.05
    assert abs(value-independent) < 1e-12
    passed = max(errors) < 2e-6 and np_error < 1e-12
    assert passed
    result = dict(passed=True, directional_errors=errors, masked_target_gradient_error=mask_error,
        independent_numpy_forward_error=np_error, v1_alias_witness=dict(old_features_identical=old_same,
            complete_features_differ=True, first_fire_q=q_a, altered_next_job_fire_q=q_b),
        public_state_reconstruction=True, one_read_q=value, independent_one_read_q=independent,
        parameter_count=sum(v.size for v in parameters.values()),
        wall_seconds=time.perf_counter()-start, cpu_seconds=time.process_time()-cpu)
    save(HERE / "numerical_validation.json", result)
    return result


def recompute_gate(runs):
    p = protocol()
    details = []
    for family in ("full_value", "ordinary_boundary"):
        values = [r["selected"]["regret"] for r in runs if r["family"] == family]
        assert len(values) == len(p["seeds"])
        mean, largest = float(np.mean(values)), float(max(values))
        details.append(dict(family=family, seed_regrets=values, mean=mean, maximum=largest,
            passed=mean <= p["gate"]["full_value_and_ordinary_each_mean_seed_regret_max"]
                and largest <= p["gate"]["full_value_and_ordinary_each_seed_regret_max"]))
    return dict(passed=all(d["passed"] for d in details), details=details,
                excluded_from_gate="first_event_value is a deliberate continuation ablation")


def audit():
    start = time.perf_counter()
    verify()
    result = json.loads((HERE / "development_results.json").read_text())
    assert result["complete"] and len(result["runs"]) == 15
    p = protocol()
    assert {(r["seed"], r["family"]) for r in result["runs"]} == {(s, f) for s in p["seeds"] for f in p["families"]}
    maximum_error = 0.
    for row in result["runs"]:
        assert row["updates"] == 600 and row["trainable_parameters"] == 2852
        assert row["all_parameter_groups_updated"] and len(row["candidates"]) == 12
        assert row["selected"] == min(row["candidates"], key=lambda c: (c["regret"], c["step"]))
        for candidate in row["candidates"]:
            assert sha(HERE / candidate["checkpoint"]) == candidate["sha256"]
        arrays = dict(np.load(HERE / row["selected"]["checkpoint"]))
        params = {k: arrays[k] for k in ("w1", "b1", "w2", "b2")}
        val = dict(np.load(HERE / "states" / f"seed{row['seed']}" / "validation.npz"))
        logits = numpy_forward(params, ((val["x"]-arrays["feature_mean"])/arrays["feature_scale"]).astype(np.float32))
        score = metrics(logits, val)
        error = abs(score["regret"]-row["selected"]["regret"])
        maximum_error = max(error, maximum_error)
        assert error < 1e-10
    for seed in p["seeds"]:
        rows = [r for r in result["runs"] if r["seed"] == seed]
        assert len({r["initialization_sha256"] for r in rows}) == 1
        assert len({r["batch_stream_sha256"] for r in rows}) == 1
    manifest = json.loads((HERE / "development_manifest.json").read_text())
    for path, digest in manifest["files"].items():
        assert sha(HERE / path) == digest
    gate = recompute_gate(result["runs"])
    assert gate == json.loads((HERE / "gate.json").read_text())
    confirmation = json.loads((HERE / "confirmation.json").read_text())
    if not gate["passed"]:
        assert confirmation["status"] == "not_generated_development_gate_failed"
        assert not (HERE / "heldout").exists() and not (HERE / "heldout_manifest.json").exists()
        assert confirmation["policy_sessions"] == 0
    else:
        assert confirmation["status"] == "completed" and len(confirmation["rows"]) == 800
        for row in confirmation["rows"]:
            assert sha(HERE / row["trace"]) == row["trace_sha256"]
            trace = json.loads((HERE / row["trace"]).read_text())
            assert trace["terminal"] and row["label_access_after_terminal"]
            assert sum(e["action"] == "READ" for e in trace["events"]) == trace["counts"]["content_invocations"]
    receipt = dict(integrity_passed=True, trained_controllers=15, retained_candidates=180,
        all_matched_initializations_and_batches=True, complete_public_state_check=True,
        selected_regret_independent_error=maximum_error, development_gate_passed=gate["passed"],
        heldout_policy_sessions=800 if gate["passed"] else 0,
        original_v1_identities_unchanged=True, audit_wall_seconds=time.perf_counter()-start,
        development_results_sha256=sha(HERE / "development_results.json"),
        gate_sha256=sha(HERE / "gate.json"), freeze_sha256=sha(HERE / "freeze.json"))
    save(HERE / "audit.json", receipt)
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    audit()
