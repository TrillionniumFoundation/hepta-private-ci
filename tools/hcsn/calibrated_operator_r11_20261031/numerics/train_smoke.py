"""Thirty actual AD optimization steps through the complete financial kernel."""

import hashlib
import json
from pathlib import Path

import numpy as np

import kernel
import reference

ROOT = Path(__file__).resolve().parent


def run(destination):
    if destination.exists():
        raise ValueError("Choose a new evidence path")
    path = ROOT / "TRAINING_PROTOCOL.json"
    protocol = json.loads(path.read_text())
    indices = [kernel.NAMES.index(n) for n in protocol["trained_parameter_names"]]
    lo, hi = np.array(protocol["raw_sigmoid_lower"]), np.array(protocol["raw_sigmoid_upper"])
    scale = np.array(protocol["output_scales"])
    teacher = kernel.BASE.copy()
    teacher[indices] = protocol["target_parameters"]
    targets = np.array([reference.fields(teacher, asset) for asset in protocol["fixed_assets"]], dtype=float)
    runs = []
    for mode in protocol["modes"]:
        def objective(raw):
            sigmoid = 1 / (1 + np.exp(-raw))
            theta = kernel.BASE.copy()
            theta[indices] = lo + (hi - lo) * sigmoid
            output, jacobian = zip(*(kernel.evaluate(theta, asset, mode=mode) for asset in protocol["fixed_assets"]))
            values, jac = np.array(output, dtype=float), np.array(jacobian, dtype=float)
            residual = (values - targets) / scale
            gradient = np.sum(2 * residual[:, :, None] * jac[:, :, indices] / scale[None, :, None], axis=(0, 1)) / residual.size
            gradient *= (hi - lo) * sigmoid * (1 - sigmoid)
            loss = float(np.mean(residual ** 2))
            if not np.isfinite(loss) or not np.all(np.isfinite(gradient)):
                raise ValueError("Nonfinite full-kernel loss or AD gradient")
            return loss, gradient, theta, values

        ratio = (kernel.BASE[indices] - lo) / (hi - lo)
        raw = np.log(ratio / (1 - ratio))
        first, second = np.zeros(3), np.zeros(3)
        trajectory, attempts = [], []
        for step in range(protocol["steps"] + 1):
            loss, gradient, theta, values = objective(raw)
            trajectory.append(dict(step=step, loss=loss, raw_parameters=raw.tolist(), theta=theta.tolist(),
                                   raw_ad_gradient=gradient.tolist(), outputs=values.tolist(), domain_accepted=True))
            if step == protocol["steps"]:
                break
            first, second = .9 * first + .1 * gradient, .999 * second + .001 * gradient ** 2
            direction = (first / (1 - .9 ** (step + 1))) / (np.sqrt(second / (1 - .999 ** (step + 1))) + 1e-8)
            for halving in range(13):
                candidate = raw - .08 * direction / (2 ** halving)
                try:
                    trial_loss, _, trial_theta, _ = objective(candidate)
                    accepted = trial_loss < loss
                    attempts.append(dict(step=step + 1, halving=halving, loss=trial_loss,
                                         theta=trial_theta.tolist(), accepted=bool(accepted), invalid=False))
                    if accepted:
                        raw = candidate
                        break
                except ValueError as error:
                    attempts.append(dict(step=step + 1, halving=halving, accepted=False, invalid=True, reason=str(error)))
        relative_reduction = 1 - trajectory[-1]["loss"] / trajectory[0]["loss"]
        runs.append(dict(mode=mode, trajectory=trajectory, attempts=attempts, relative_loss_reduction=relative_reduction,
                         accepted_updates=sum(a["accepted"] for a in attempts),
                         invalid_proposals=sum(a["invalid"] for a in attempts),
                         passed=relative_reduction >= protocol["minimum_relative_loss_reduction"]))
    result = dict(schema="hcsn-full-hx-mini-optimization-r11-evidence-v1", protocol=protocol,
                  protocol_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), targets=targets.tolist(),
                  source_sha256={n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest()
                                 for n in ("kernel.py", "reference.py", "train_smoke.py")},
                  runs=runs, passed=all(r["passed"] for r in runs))
    destination.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps([{k: v for k, v in r.items() if k not in ("trajectory", "attempts")} for r in runs], indent=2))
    return result


if __name__ == "__main__":
    result = run(ROOT / "TRAINING_RESULTS.json")
    raise SystemExit(0 if result["passed"] else 1)
