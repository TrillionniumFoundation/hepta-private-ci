"""Frozen-V6, real-source development experiment for full joint target prediction.

MNIST pixels and the encoder are real; the shared occlusion and public modular
sum are constructed tasks. Historical validation is a development holdout,
not a new independent confirmation cohort. No audio likelihood is fitted here.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import resource
import time

import numpy as np
import torch

from ...v6.data import Observation, load_corpus, make_batch
from ...v6.plan_training import ControlledSnapshot
from .prior import JointPrior, group_weights


CHECKPOINT_SHA = "8fa76a13cdeee48e41b84e29211659a065d9573e2fdfecc4281f882248b508b6"
VIEWS = ("clean", "shared_occlusion_public_sum")
SEEDS = (17, 29, 43)
STEPS, RATE, L2 = 250, .01, .0001


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


class FactorizedReference:
    """Matched-input, approximately parameter-matched two-marginal reference."""

    def __init__(self, features, groups, hidden, seed):
        weights = group_weights(groups)
        self.mean = weights @ features
        self.scale = np.sqrt(weights @ np.square(features - self.mean))
        self.scale = np.where(self.scale < 1e-8, 1., self.scale)
        rng = np.random.default_rng(seed)
        self.p = {"w1": rng.normal(0, 1. / math.sqrt(features.shape[1]), (hidden, features.shape[1])),
                  "b1": np.zeros(hidden), "w2": rng.normal(0, .01, (20, hidden)), "b2": np.zeros(20)}

    def forward(self, features):
        x = (features - self.mean) / self.scale
        h = np.tanh(x @ self.p["w1"].T + self.p["b1"])
        z = (h @ self.p["w2"].T + self.p["b2"]).reshape(-1, 2, 10)
        z -= z.max(-1, keepdims=True)
        logp = z - np.log(np.exp(z).sum(-1, keepdims=True))
        return x, h, logp

    def fit(self, features, targets, groups):
        weights = group_weights(groups)
        labels = np.stack((targets // 10, targets % 10), 1)
        m, v = ({k: np.zeros_like(a) for k, a in self.p.items()} for _ in range(2))
        losses = []
        for step in range(1, STEPS + 1):
            x, h, logp = self.forward(features)
            loss = -(weights[:, None] * np.take_along_axis(logp, labels[..., None], -1)[..., 0]).sum()
            loss += .5 * L2 * (np.square(self.p["w1"]).sum() + np.square(self.p["w2"]).sum())
            delta = np.exp(logp)
            for slot in (0, 1):
                delta[np.arange(len(x)), slot, labels[:, slot]] -= 1.
            delta = (delta * weights[:, None, None]).reshape(-1, 20)
            back = (delta @ self.p["w2"]) * (1 - h * h)
            gradients = {"w2": delta.T @ h + L2 * self.p["w2"], "b2": delta.sum(0),
                         "w1": back.T @ x + L2 * self.p["w1"], "b1": back.sum(0)}
            if not np.isfinite(loss) or any(not np.isfinite(g).all() for g in gradients.values()):
                raise ValueError("Nonfinite factorized fitting trajectory")
            losses.append(float(loss))
            for key, gradient in gradients.items():
                m[key] = .9 * m[key] + .1 * gradient
                v[key] = .999 * v[key] + .001 * gradient * gradient
                self.p[key] -= RATE * (m[key] / (1 - .9 ** step)) / (np.sqrt(v[key] / (1 - .999 ** step)) + 1e-8)
        return losses

    def predict(self, features):
        logp = self.forward(features)[2]
        return np.exp(logp[:, 0, :, None] + logp[:, 1, None, :]).reshape(-1, 100)

    def export(self):
        return {"schema": "hepta.repair.factorized-reference.v1", "mean": self.mean.tolist(),
                "scale": self.scale.tolist(), "parameters": {k: a.tolist() for k, a in self.p.items()}}


@torch.inference_mode()
def features(snapshot, corpus, split, pairs):
    """Trusted task construction; both priors see the same public relation."""
    xs, ys, views, identities, originals = [], [], [], [], []
    for offset in range(0, pairs, 64):
        count = min(64, pairs - offset)
        batch = make_batch(corpus, split, count, 471101 + offset, corruption="clean", offset=offset)
        for view in range(2):
            mask = batch.observation.mask.clone()
            if view:
                mask[:, :, :20, :] = 0.
            observation = Observation(batch.observation.pixels * mask, mask, batch.observation.text_tokens)
            state = snapshot._base._model.encode(observation)
            context = state.context.double().numpy()
            marginal = snapshot._base._model.digit_head(state.h).reshape(-1, 2, 10).softmax(-1).double().numpy()
            original = (marginal[:, 0, :, None] * marginal[:, 1, None, :]).reshape(-1, 100)
            # This is a declared public task instruction, not hidden evidence secretly given to one arm.
            relation = np.zeros((count, 11))
            if view:
                public_sum = batch.target.labels.sum(1).numpy() % 10
                relation[np.arange(count), public_sum] = 1.; relation[:, 10] = 1.
            xs.append(np.concatenate((context, relation), 1))
            ys.extend((10 * batch.target.labels[:, 0] + batch.target.labels[:, 1]).tolist())
            views.extend([view] * count)
            identities.extend(batch.source_ids)
            originals.append(original)
    groups = [hashlib.sha256("\n".join(sorted(pair)).encode()).hexdigest() for pair in identities]
    return np.concatenate(xs), np.array(ys), np.array(views), groups, identities, np.concatenate(originals)


def public_condition(q, x, views):
    constrained = q.copy()
    for row in np.flatnonzero(views == 1):
        modulus = int(x[row, -11:-1].argmax())
        valid = np.array([(t // 10 + t % 10) % 10 == modulus for t in range(100)])
        constrained[row, ~valid] = 0.
        constrained[row] /= constrained[row].sum()
    return constrained


def score(q, target, x, views):
    if (q.shape != (len(target), 100) or not np.isfinite(q).all() or (q < 0).any()
            or not np.allclose(q.sum(1), 1., atol=1e-6) or (q[np.arange(len(q)), target] <= 0).any()):
        raise ValueError("A predictive joint distribution must put positive mass on actual targets")
    chosen, confidence = q.argmax(1), q.max(1)
    correct = chosen == target
    nll = -np.log(q[np.arange(len(q)), target])
    ece = 0.
    for low in np.arange(0, 1, .1):
        selected = (confidence >= low) & (confidence < low + .1 + (1e-12 if low > .89 else 0))
        if selected.any():
            ece += selected.mean() * abs(correct[selected].mean() - confidence[selected].mean())
    invalid = []
    for i in np.flatnonzero(views == 1):
        modulus = x[i, -11:-1].argmax()
        invalid.append(sum(q[i, t] for t in range(100) if (t // 10 + t % 10) % 10 != modulus))
    return {"joint_nll": float(nll.mean()), "joint_brier": float((np.square(q).sum(1) - 2 * q[np.arange(len(q)), target] + 1).mean()),
            "joint_accuracy": float(correct.mean()), "selected_ECE_10bins": float(ece),
            "violated_public_relation_mass": float(np.mean(invalid)) if invalid else None}, nll


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run = args.assets / "ndu-runs/full-002"
    checkpoint = run / "seed-17-terminal_entropic_ndu.pt"
    if sha(checkpoint) != CHECKPOINT_SHA:
        raise ValueError("This experiment requires the original full-002 frozen checkpoint")
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    protocol = json.loads((run / "protocol.json").read_bytes())
    registration = {"schema": "hepta.repair.v6-joint-development.v1", "created_ns": time.time_ns(),
        "checkpoint_sha256": CHECKPOINT_SHA, "original_protocol_sha256": sha(run / "protocol.json"),
        "fit_pairs": 2000, "holdout_pairs": 500, "fit_split": "train", "holdout_split": "validation",
        "pair_offset": 0, "views": VIEWS, "seeds": SEEDS, "steps": STEPS, "learning_rate": RATE, "l2": L2,
        "task": "Clean pairs; shared top-20-row occlusion plus explicitly public sum-modulo-10 instruction",
        "primary": "paired per-source joint NLL, learned joint minus learned factorized; lower is better",
        "strong_controls": "Frozen initial semantic marginals; each arm also conditioned on the public relation",
        "scope": "Historical-source development holdout; no writer-disjoint/new-source confirmation or generation claim",
        "source_sha256": {p.name: sha(p) for p in (Path(__file__), Path(__file__).with_name("prior.py"))}}
    save(args.output / "REGISTRATION.json", registration)
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    corpus = load_corpus(args.assets / "ndu-data", train_sources=10000, validation_sources=2000,
                         evaluator_sources=10000, retention_sources=1000, test_sources=2000, seed=271828)
    if corpus.manifest != protocol["dataset_manifest"]:
        raise ValueError("Rebuilt source identities differ from the original full-002 manifest")
    snapshot = ControlledSnapshot.load(checkpoint, expected_file_sha256=CHECKPOINT_SHA)
    x, target, view, groups, ids, _ = features(snapshot, corpus, "train", 2000)
    np.savez_compressed(args.output / "fit_features.npz", features=x, targets=target, views=view, groups=groups)
    hidden_joint = 32
    joint_count = (x.shape[1] + 1) * hidden_joint + (hidden_joint + 1) * 100
    hidden_factorized = round((joint_count - 20) / (x.shape[1] + 21))
    trained, training = {}, []
    for seed in SEEDS:
        began = time.perf_counter()
        joint = JointPrior.fit(x, target, groups, steps=STEPS, learning_rate=RATE, seed=seed, hidden=hidden_joint, l2=L2)
        factorized = FactorizedReference(x, groups, hidden_factorized, seed)
        losses = factorized.fit(x, target, groups)
        for name, model in (("joint", joint), ("factorized", factorized)):
            trained[(name, seed)] = model
            save(args.output / f"{name}-{seed}.json", model.export())
        training.append({"seed": seed, "wall_seconds": time.perf_counter() - began,
                         "joint_objective": joint.provenance["final_objective"], "factorized_objective_before_last_update": losses[-1]})
        print(json.dumps({"trained_seed": seed}), flush=True)
    save(args.output / "TRAINING_COMPLETE.json", {"models": training, "holdout_prediction_started": False})
    hx, hy, hv, hg, hi, original = features(snapshot, corpus, "validation", 500)
    if set(groups) & set(hg) or {i for pair in ids for i in pair} & {i for pair in hi for i in pair}:
        raise ValueError("A raw source crossed the fitting/holdout boundary")
    predictions = {"original_factorized": original}
    for (name, seed), model in trained.items():
        predictions[f"{name}-{seed}"] = model.predict(hx)
    predictions.update({name + "_public_conditioned": public_condition(q, hx, hv) for name, q in list(predictions.items())})
    np.savez_compressed(args.output / "sealed_predictions.npz", **predictions)
    np.savez_compressed(args.output / "holdout_scoring.npz", features=hx, targets=hy, views=hv, groups=hg)
    metrics, differences = {}, {}
    for vi, view_name in enumerate(VIEWS):
        take = hv == vi
        metrics[view_name] = {name: score(q[take], hy[take], hx[take], hv[take])[0] for name, q in predictions.items()}
        for suffix in ("", "_public_conditioned"):
            delta = np.mean([score(predictions[f"joint-{s}{suffix}"][take], hy[take], hx[take], hv[take])[1]
                             - score(predictions[f"factorized-{s}{suffix}"][take], hy[take], hx[take], hv[take])[1] for s in SEEDS], 0)
            rng = np.random.default_rng(271829)
            boot = delta[rng.integers(len(delta), size=(5000, len(delta)))].mean(1)
            differences[view_name + suffix] = {"joint_minus_factorized_nll": float(delta.mean()),
                "nominal_source_pair_95CI": np.quantile(boot, [.025, .975]).tolist()}
    snapshot.verify_integrity()
    save(args.output / "RESULTS.json", {"schema": "hepta.repair.v6-joint-development-result.v1",
        "registration_sha256": sha(args.output / "REGISTRATION.json"), "source_manifest_sha256": corpus.manifest["manifest_sha256"],
        "actual_encoder_rows": len(x) + len(hx), "fit_source_pairs": 2000, "holdout_source_pairs": 500,
        "joint_parameters": joint_count, "factorized_parameters": (x.shape[1] + 21) * hidden_factorized + 20,
        "metrics": metrics, "paired_differences": differences, "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu, "peak_RSS_KiB": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "raw_file_sha256": {p.name: sha(p) for p in sorted(args.output.iterdir()) if p.is_file()},
        "scope": registration["scope"], "same_speaker_likelihood_identified": False, "production_authority": False})
    print(json.dumps({"completed": True, "differences": differences, "output": str(args.output)}), flush=True)


if __name__ == "__main__":
    main()
