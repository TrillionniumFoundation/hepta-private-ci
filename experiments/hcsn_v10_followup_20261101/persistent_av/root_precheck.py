"""Independent finite-path enumeration and sealed-input evaluation entry point."""

import argparse
import hashlib
import itertools
import json
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp

from . import candidate


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def transition_ode(q):
    k = len(q)
    result = solve_ivp(lambda _, y: (y.reshape(k, k) @ q).ravel(),
                       (0, 1), np.eye(k).ravel(), method="DOP853",
                       rtol=2e-13, atol=3e-15)
    if not result.success:
        raise ArithmeticError("Independent ODE failed")
    return result.y[:, -1].reshape(k, k)


def likelihood(law, modality, value):
    variance = np.asarray(law["variance"])[modality]
    return -.5 * np.sum(np.log(2 * np.pi * variance)
                        + (value - np.asarray(law["mean"])[modality])**2 / variance, axis=1)


def enumerate_posterior(law, transition, time, observations):
    k = len(law["prior"])
    paths = list(itertools.product(range(k), repeat=time + 1))
    scores = []
    for path in paths:
        score = np.log(law["prior"][path[0]])
        for before, after in zip(path[:-1], path[1:]):
            score += np.log(transition[before, after])
        for source, modality, value in observations:
            score += likelihood(law, modality, value)[path[source]]
        scores.append(score)
    weights = np.exp(np.asarray(scores) - max(scores))
    return (weights / weights.sum()).reshape((k,) * (time + 1))


def check(output):
    frozen_path = output / "FROZEN.json"
    frozen = json.loads(frozen_path.read_text())
    checks, largest, wrong_controls = 0, 0.0, 0
    law_count = 0
    for path in sorted(output.glob("*/LAW-*.json")):
        for attempt in json.loads(path.read_text())["all_candidates"]:
            law = attempt["law"]
            q = np.asarray(law["q"])
            reference = transition_ode(q)
            p = candidate.PathFilter(law)
            u = candidate.PathFilter(law, "uniformization")
            error = max(abs(p.transition - reference).max(), abs(u.transition - reference).max())
            assert error < 5e-12
            largest = max(largest, float(error)); checks += 1; law_count += 1
            values = {(t, m): np.asarray(law["mean"])[m, (t + m) % len(q)]
                      + .1 * np.sqrt(np.asarray(law["variance"])[m, (t + m) % len(q)])
                      for t, m in itertools.product(range(1, 4), range(2))}
            endings = []
            for audio_positions in itertools.combinations(range(5), 2):
                order = [0] + [0 if i in audio_positions else 1 for i in range(5)]
                counters, accepted, global_time = [0, 0], [], 0
                exact = candidate.PathFilter(law)
                ordinary = candidate.PathFilter(law, "uniformization")
                for modality in order:
                    counters[modality] += 1
                    source = counters[modality]; global_time = max(global_time, source)
                    value = values[source, modality]
                    accepted.append((source, modality, value))
                    exact.accept(source, modality, value, 1, global_time)
                    ordinary.accept(source, modality, value, 1, global_time)
                    independent = enumerate_posterior(law, reference, global_time, accepted)
                    error = max(abs(exact.p - independent).max(), abs(exact.p - ordinary.p).max())
                    assert error < 2e-10
                    assert abs(exact.p.sum() - 1) < 1e-12 and exact.p.min() >= 0
                    assert exact.p.size <= 256
                    largest = max(largest, float(error)); checks += 3
                endings.append(exact.p)
            assert all(np.max(abs(row - endings[0])) < 1e-12 for row in endings)
            checks += 1
            # Deliberately condition late V1 at z3 to check that this error is detectable.
            accepted = [(t, 0, values[t, 0]) for t in range(1, 4)]
            proper = enumerate_posterior(law, reference, 3, accepted + [(1, 1, values[1, 1])])
            wrong = enumerate_posterior(law, reference, 3, accepted + [(3, 1, values[1, 1])])
            if np.max(abs(proper - wrong)) > 1e-8:
                wrong_controls += 1
    assert law_count == 16 and wrong_controls > 0
    for item in frozen["models"]:
        assert digest(output / item["path"]) == item["sha256"]
        checks += 1
    for path, expected in frozen["sources"].items():
        assert digest(path) == expected
        checks += 1
    artifacts = [output / "PROTOCOL.json", frozen_path]
    for pattern in ("*/LAW-*.json", "*/data-*.npz", "*/*_ADAPTERS.json", "*/INPUTS.json", "*/*-selected.pt"):
        artifacts.extend(output.glob(pattern))
    receipt = {"schema": "hcsn-v10-independent-path-precheck.v1", "status": "passed",
               "checks": checks, "law_candidates": law_count,
               "largest_absolute_error": largest, "late_wrong_axis_detected_laws": wrong_controls,
               "artifact_sha256": {str(p.relative_to(output)): digest(p) for p in sorted(set(artifacts))},
               "precheck_source_sha256": digest(__file__),
               "scope": "Independent ODE and explicit latent-path enumeration, ordered late observations, same-law HMM; not empirical generative-law adequacy or HX qualification"}
    with (output / "INDEPENDENT_PRECHECK.json").open("x") as stream:
        json.dump(receipt, stream, indent=2); stream.write("\n")
    return receipt


def verify_seal(output, receipt):
    if receipt.get("status") != "passed" or receipt.get("schema") != "hcsn-v10-independent-path-precheck.v1":
        raise ValueError("Independent precheck required")
    if digest(__file__) != receipt["precheck_source_sha256"]:
        raise ValueError("Precheck entry point changed")
    for relative, expected in receipt["artifact_sha256"].items():
        path = (output / relative).resolve()
        if not path.is_relative_to(output.resolve()) or digest(path) != expected:
            raise ValueError("Frozen evaluation artifact changed: " + relative)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("check", "evaluate"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    candidate.torch.set_num_threads(1)
    if args.stage == "check":
        receipt = check(args.output)
        print(json.dumps({k: v for k, v in receipt.items() if k != "artifact_sha256"}))
    else:
        receipt = json.loads((args.output / "INDEPENDENT_PRECHECK.json").read_text())
        verify_seal(args.output, receipt)
        candidate.evaluate(args.output)
        verify_seal(args.output, receipt)


if __name__ == "__main__":
    main()
