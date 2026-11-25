"""Independent kernel/causality checks and exact-parent route-ablation replay."""

import copy
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.integrate import quad

from cells import ResearchCellNet, delayed_data, digest, evaluate, passage_features


def verify(output):
    kernel_errors = []
    sigma, horizon, discount, boundary = 0.55, 0.8, 0.7, 2.0
    for state in (-1.5, -0.4, 0.0, 0.6, 1.4):
        expected = []
        for rate in (0, discount):
            terms = []
            for distance in (boundary - state, boundary + state):
                def integrand(t):
                    return (distance / (sigma * np.sqrt(2 * np.pi * t**3)) *
                            np.exp(-distance**2 / (2 * sigma**2 * t) - rate * t))
                terms.append(quad(integrand, 0, horizon, epsabs=1e-12)[0])
            expected.append(terms[0] - terms[1])
        actual = passage_features(np.array([[state]]), np.array([boundary]))
        kernel_errors.extend(abs(float(v[0, 0]) - ref) for v, ref in zip(actual, expected))
    data = delayed_data(99199, 32, 8)
    model = ResearchCellNet(8, 9)
    prob, logit = model.forward(data)
    changed = copy.deepcopy(data)
    changed["y"] = 1 - data["y"]
    target_leak_error = float(abs(model.forward(changed)[0] - prob).max())
    changed["x"][7:] += 5
    future_leak_error = float(abs(model.forward(changed)[1][:7] - logit[:7]).max())
    checks = {"kernel_vs_density_quadrature_max_error": max(kernel_errors),
              "forward_target_flip_error": target_leak_error,
              "future_observation_perturbation_prefix_error": future_leak_error}
    if max(checks.values()) > 1e-9:
        raise RuntimeError(checks)
    parent = json.loads((output / "pft4.json").read_text())
    rows, raw = [], []
    for record in (r for r in parent["rows"] if r["graph"] == "learned"):
        width, seed = record["width"], record["seed"]
        training = delayed_data(10000 + seed, 512, width)
        validation = delayed_data(20000 + seed, 128, width)
        test = delayed_data(30000 + seed, 1024, width, "laplace")
        net = ResearchCellNet(width, seed)
        fit = net.fit(training, validation, steps=record["fit"]["steps"], seed=seed)
        if fit["weights_sha256"] != record["fit"]["weights_sha256"]:
            raise ValueError("replay did not recover the frozen selected parent")
        baseline = evaluate(net, test)
        if baseline["prediction_sha256"] != record["test"]["prediction_sha256"]:
            raise ValueError("frozen parent predictions differ")
        intact = net.forward(test)[0]
        weights = {k: v.tolist() for k, v in net.p.items()}
        # Preserve both channels of each sender; cyclic shift has no fixed point.
        perm = np.roll(np.arange(width), max(1, width // 3))
        order = np.r_[perm, width + perm]
        old = net.p["rec"].copy()
        net.p["rec"][order] = old
        shuffled = evaluate(net, test)
        shuffled_prob = net.forward(test)[0]
        row = {"width": width, "seed": seed, "exact_parent_recovered": True,
               "intact_accuracy": baseline["accuracy"],
               "sender_permuted_accuracy": shuffled["accuracy"],
               "accuracy_drop": baseline["accuracy"] - shuffled["accuracy"],
               "permutation": perm.tolist(), "replay_fit_wall_seconds": fit["fit_wall_seconds"]}
        rows.append(row)
        raw.append({"width": width, "seed": seed, "weights": weights,
                    "labels": test["y"].astype(int).tolist(), "intact_prob": intact.tolist(),
                    "sender_permuted_prob": shuffled_prob.tolist(),
                    "frozen_weights_sha256": fit["weights_sha256"]})
        print(json.dumps(row), flush=True)
    roundtrip_error = 0.0
    for item in json.loads(json.dumps(raw, allow_nan=False)):
        restored = ResearchCellNet(item["width"], item["seed"])
        restored.p = {k: np.asarray(v, dtype=float) for k, v in item["weights"].items()}
        heldout = delayed_data(30000 + item["seed"], 1024, item["width"], "laplace")
        roundtrip_error = max(roundtrip_error, float(abs(
            restored.forward(heldout)[0] - item["intact_prob"]).max()))
    if roundtrip_error != 0:
        raise ValueError("JSON weight restoration changed predictions")
    checks["json_weight_roundtrip_prediction_error"] = roundtrip_error
    result = {"status": "PASS_SCOPE_LIMITED", "scope": "exact-parent within-trajectory sender permutation",
              "independent_checks": checks, "rows": rows,
              "original_shuffle_scope": "across examples; retained as a separate association ablation",
              "raw_file": "pft4_route_raw.json", "model": "new synthetic research proxy, not production HCSN",
              "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    for name, value in (("pft34_verification.json", result), ("pft4_route_raw.json", raw)):
        with (output / name).open("x") as file:
            json.dump(value, file, indent=2, allow_nan=False)
            file.write("\n")


if __name__ == "__main__":
    verify(Path(__file__).parent / "results")
