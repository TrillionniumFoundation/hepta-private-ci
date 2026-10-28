"""Independent SciPy distribution references for retained joint model fits."""

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.stats import invgauss, levy


def reference_loss(vector, path):
    with np.load(path, allow_pickle=False) as data:
        meta = json.loads(data["metadata_utf8"].tobytes())
        vector = np.array(vector)
        mu = vector[0] + data["inputs"] @ vector[1:3]
        if len(vector) == 7:
            mu += vector[6] * np.prod(data["inputs"], axis=1)
        sigma = math.exp(vector[3])
        x = np.where(data["after_reset"], math.exp(vector[5]), data["initial_level"] - vector[4])
        time, event = data["duration"], data["event"]
        scale = x * x / (sigma * sigma)
        result = np.empty(len(time))
        zero = np.abs(mu) < 1e-14
        result[zero] = np.where(event[zero], levy.logpdf(time[zero], scale=scale[zero]),
                                levy.logsf(time[zero], scale=scale[zero]))
        nz = ~zero
        shape = sigma * sigma / (x[nz] * np.abs(mu[nz]))
        logpdf = invgauss.logpdf(time[nz], shape, scale=scale[nz])
        logsf = invgauss.logsf(time[nz], shape, scale=scale[nz])
        loghit = np.minimum(0, -2 * mu[nz] * x[nz] / (sigma * sigma))
        logpdf += loghit
        with np.errstate(divide="ignore"):
            lognever = np.log(-np.expm1(loghit))
        logsf = np.logaddexp(lognever, loghit + logsf)
        result[nz] = np.where(event[nz], logpdf, logsf)
        if not np.isfinite(result).all():
            raise ArithmeticError("Independent likelihood reference is not finite")
        return -float(result.sum()) / meta["trajectories"]


def validate(prepared):
    root = Path(prepared)
    rows = []
    for seed in (1103, 1151, 1201, 1213, 1223, 1231, 1237, 1249):
        for width in (6, 7):
            directory = root / str(seed)
            path = directory / f"model{width}.json"
            model = json.loads(path.read_text())
            training, development = directory / "training.npz", directory / "likelihood_development.npz"
            for data_path, identity in ((training, "training_file_sha256"),
                                        (development, "development_file_sha256")):
                if hashlib.sha256(data_path.read_bytes()).hexdigest() != model[identity]:
                    raise ValueError("Fitted model/data binding mismatch")
            if model["seed"] != seed or model["active_parameter_count"] != width:
                raise ValueError("Model identity or parameter count mismatch")
            if not model["optimizer_success"] or model["selected_loss"] >= model["initial_loss"]:
                raise ValueError("Joint optimizer failed or did not improve training likelihood")
            deltas = np.abs(np.array(model["selected_vector"]) - np.array(model["initial_vector"]))
            if len(deltas) != width or np.min(deltas) <= 1e-8:
                raise ValueError("At least one claimed active parameter did not change")
            selected = reference_loss(model["selected_vector"], training)
            heldout = reference_loss(model["selected_vector"], development)
            initial = reference_loss(model["initial_vector"], training)
            differences = {"initial": initial - model["initial_loss"],
                           "selected": selected - model["selected_loss"],
                           "heldout": heldout - model["heldout_loss"]}
            if max(abs(x) for x in differences.values()) > 2e-8:
                raise ArithmeticError("Independent inverse-Gaussian likelihood disagrees")
            rows.append({"seed": seed, "parameters": width, "pass": True,
                         "likelihood_differences": differences,
                         "min_parameter_delta": float(np.min(deltas)),
                         "selected_loss": selected, "initial_loss": initial,
                         "heldout_loss": heldout, "model_digest": model["model_digest"],
                         "model_file_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return {"schema": "HeptaFirstPassageTrainingValidationV1", "pass": True,
            "reference": "SciPy inverse-Gaussian and Levy pdf/survival; no first-passage kernel imports",
            "runs": rows, "training_seeds": 8, "fitted_models": 16,
            "claim": "Every common input/dynamics/boundary/reset coefficient participates and changes; not a hard-spike network backpropagation claim"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prepared", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = validate(args.prepared)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"pass": True, "models": 16, "output": str(args.output)}))


if __name__ == "__main__":
    main()
