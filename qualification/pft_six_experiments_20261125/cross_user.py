#!/usr/bin/env python3
"""PFT5: frozen-candidate A->B protocol; synthetic controls are not real-user proof.

NPZ dataset schema: X[n,d], Y[n,q], sample_ids[n] (non-object Unicode).
The train manifest contains A, keep_train, parent only. Eval labels live in a
separate manifest read only by the evaluate subprocess after candidate freezing.
This is auditable process/data separation, not an OS-enforced malicious-code box.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
import numpy as np


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def load_json(path):
    return json.loads(Path(path).read_text())


def sample_hashes(ids):
    return [hashlib.sha256(str(x).encode()).hexdigest() for x in ids]


def content_hashes(x, y):
    return [hashlib.sha256(np.asarray(a, dtype="<f8").tobytes() +
                           np.asarray(b, dtype="<f8").tobytes()).hexdigest()
            for a, b in zip(x, y)]


def load_dataset(desc, role):
    if desc["role"] != role:
        raise ValueError("Dataset role mismatch")
    if sha(desc["path"]) != desc["sha256"]:
        raise ValueError("Dataset hash mismatch")
    with np.load(desc["path"], allow_pickle=False) as z:
        x, y, ids = z["X"].copy(), z["Y"].copy(), z["sample_ids"].copy()
    if x.ndim != 2 or y.ndim != 2 or len(x) != len(y) or len(ids) != len(x):
        raise ValueError("Expected X[n,d], Y[n,q], sample_ids[n]")
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("Non-finite dataset")
    hashes = sample_hashes(ids)
    if len(set(hashes)) != len(hashes):
        raise ValueError("Duplicate sample ids")
    return x, y, hashes


def train(manifest_path, out):
    started = time.perf_counter()
    manifest = load_json(manifest_path)
    if set(manifest["datasets"]) != {"A", "keep_train"}:
        raise ValueError("Trainer accepts exactly A and keep_train; no B path")
    a = manifest["datasets"]["A"]
    keep = manifest["datasets"]["keep_train"]
    x, y, ids = load_dataset(a, "A")
    kx, ky, kids = load_dataset(keep, "keep_train")
    if set(ids) & set(kids):
        raise ValueError("A and keep train overlap")
    content_ids = content_hashes(x, y) + content_hashes(kx, ky)
    if len(set(content_ids)) != len(content_ids):
        raise ValueError("Identical training content under distinct ids")
    parent = manifest["parent"]
    if sha(parent["path"]) != parent["sha256"]:
        raise ValueError("Parent hash mismatch")
    with np.load(parent["path"], allow_pickle=False) as z:
        w0 = z["W"].copy()
    lam = float(manifest["protocol"]["ridge"])
    beta = float(manifest["protocol"]["keep_weight"])
    if lam <= 0 or beta < 0 or w0.shape != (x.shape[1], y.shape[1]):
        raise ValueError("Invalid parent/regularization")
    h = x.T @ x / len(x) + beta * (kx.T @ kx) / len(kx)
    b = x.T @ (y - x @ w0) / len(x)
    b += beta * kx.T @ (ky - kx @ w0) / len(kx)
    delta = np.linalg.solve(h + lam * np.eye(len(h)), b)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    candidate = out / "candidate.npz"
    if candidate.exists() or (out / "freeze.json").exists():
        raise FileExistsError("Refuse to overwrite frozen candidate")
    np.savez(candidate, W=w0 + delta, W0=w0)
    digest = sha(candidate)
    candidate.chmod(0o444)
    receipt = {
        "schema": "pft5.freeze.v1", "frozen_at_utc": now(),
        "source_sha256": sha(__file__),
        "candidate": str(candidate.resolve()), "candidate_sha256": digest,
        "train_manifest_sha256": sha(manifest_path), "parent": parent,
        "dataset_kind": manifest["dataset_kind"], "feature_schema": manifest["feature_schema"],
        "A_actor_id": a["actor_id"], "training_dataset_sha256": [a["sha256"], keep["sha256"]],
        "training_sample_hashes": ids + kids, "protocol": manifest["protocol"],
        "training_content_hashes": content_ids,
        "evaluation_commitment": manifest["evaluation_commitment"],
        "training_seconds": time.perf_counter() - started,
        "B_paths_in_training_manifest": False,
        "model_scope": "fixed_common_features_plus_linear_readout",
        "provenance": manifest.get("provenance", {}),
    }
    write_json(out / "freeze.json", receipt)
    return receipt


def scores(x, y, w0, w):
    old = np.mean((x @ w0 - y) ** 2, axis=1)
    new = np.mean((x @ w - y) ** 2, axis=1)
    gain = old - new
    se = float(np.std(gain, ddof=1) / np.sqrt(len(gain))) if len(gain) > 1 else None
    return {"n": len(x), "parent_mse": float(old.mean()), "candidate_mse": float(new.mean()),
            "absolute_improvement": float(gain.mean()),
            "relative_improvement": float(gain.mean() / max(old.mean(), 1e-15)),
            "paired_gain_ci95_normal": None if se is None else
            [float(gain.mean() - 1.96 * se), float(gain.mean() + 1.96 * se)]}


def evaluate(freeze_path, eval_manifest_path, output):
    freeze = load_json(freeze_path)
    candidate = Path(freeze["candidate"])
    if sha(candidate) != freeze["candidate_sha256"]:
        raise ValueError("Candidate changed after freeze")
    verified_at = now()
    with np.load(candidate, allow_pickle=False) as z:
        w, w0 = z["W"].copy(), z["W0"].copy()
    # This is the first access to the B manifest in this independent evaluator.
    manifest = load_json(eval_manifest_path)
    committed = freeze["evaluation_commitment"]
    if sha(eval_manifest_path) != committed["eval_manifest_sha256"]:
        raise ValueError("Evaluation manifest changed since preregistration")
    if manifest["feature_schema"] != freeze["feature_schema"]:
        raise ValueError("Feature coordinate mismatch")
    if manifest["dataset_kind"] != freeze["dataset_kind"]:
        raise ValueError("Dataset kind mismatch")
    bdesc, kdesc = manifest["datasets"]["B"], manifest["datasets"]["keep_eval"]
    if bdesc["actor_id"] == freeze["A_actor_id"]:
        raise ValueError("A and B actor ids must differ")
    labels_opened = now()
    x, y, ids = load_dataset(bdesc, "B")
    kx, ky, kids = load_dataset(kdesc, "keep_eval")
    if bdesc["sha256"] != committed["B_sha256"] or kdesc["sha256"] != committed["keep_eval_sha256"]:
        raise ValueError("Evaluation data changed since preregistration")
    if (set(ids) | set(kids)) & set(freeze["training_sample_hashes"]):
        raise ValueError("Evaluation overlaps training sample ids")
    if set(ids) & set(kids):
        raise ValueError("B and keep evaluation overlap")
    eval_content = content_hashes(x, y) + content_hashes(kx, ky)
    if set(eval_content) & set(freeze["training_content_hashes"]):
        raise ValueError("Evaluation repeats training content under changed ids")
    bscore, keep = scores(x, y, w0, w), scores(kx, ky, w0, w)
    p = freeze["protocol"]
    gain_gate = bscore["relative_improvement"] >= p["min_B_relative_gain"]
    keep_gate = keep["candidate_mse"] - keep["parent_mse"] <= p["max_keep_mse_increase"]
    unchanged = sha(candidate) == freeze["candidate_sha256"]
    real = freeze["dataset_kind"] == "real_authorized"
    result = {
        "schema": "pft5.evaluation.v1", "dataset_kind": freeze["dataset_kind"],
        "candidate_sha256": freeze["candidate_sha256"], "B": bscore, "keep": keep,
        "candidate_hash_verified_at_utc": verified_at, "B_labels_opened_at_utc": labels_opened,
        "candidate_frozen_at_utc": freeze["frozen_at_utc"], "candidate_unchanged": unchanged,
        "eval_manifest_sha256": sha(eval_manifest_path),
        "B_dataset_sha256": bdesc["sha256"], "keep_eval_sha256": kdesc["sha256"],
        "distinct_actor_ids": True, "sample_id_disjoint": True,
        "exact_XY_content_disjoint": True, "semantic_task_independence_proven": False,
        "evaluation_preregistered": True, "evaluation_commitment": committed,
        "B_gain_gate": gain_gate, "keep_gate": keep_gate,
        "numeric_gate": "PASS" if gain_gate and keep_gate and unchanged else "FAIL",
        "real_cross_user_gate": "REQUIRES_PROVENANCE_AND_RUNTIME_ADOPTION_REVIEW" if real else
        "BLOCKED_NO_REAL_CROSS_USER_DATA",
        "isolation_scope": "separate_process_and_manifest_not_OS_security_boundary",
        "provenance": {"train": freeze.get("provenance"), "eval": manifest.get("provenance")},
    }
    write_json(output, result)
    return result


def synthetic_pair(root, width, seed, condition):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    q, split = 3, width // 2
    w0 = rng.normal(0, 0.2, (width, q))
    delta = np.zeros_like(w0)
    delta[split:] = rng.normal(0, 0.25 / np.sqrt(width), (width - split, q))
    parent = root / "parent.npz"
    np.savez(parent, W=w0)
    descs = {}
    for role, n in [("A", 192), ("keep_train", 128), ("B", 384), ("keep_eval", 256)]:
        x = np.tanh(rng.normal(0, 1, (n, width)))
        if role in ("A", "B") and condition == "favorable":
            x[:, :split] *= 0.05
            if role == "B":
                x[:, split:] = np.tanh(np.arctanh(x[:, split:]) + 0.35)
        elif role not in ("A", "B") and condition == "favorable":
            x[:, split:] = 0
        target = w0 + delta
        if condition == "conflicting":
            target = w0 + (delta if role == "A" else -delta if role == "B" else 0)
        y = x @ target + rng.normal(0, 0.01, (n, q))
        path = root / (role + ".npz")
        np.savez(path, X=x, Y=y, sample_ids=np.array([f"s{seed}w{width}:{role}:{j}" for j in range(n)]))
        descs[role] = {"role": role, "path": str(path), "sha256": sha(path),
                       "actor_id": "synthetic_" + (role if role in ("A", "B") else "old")}
    common = {"dataset_kind": "synthetic_control", "feature_schema": f"fixed_tanh_{width}_v1",
              "provenance": {"generator": "cross_user.py:synthetic_pair", "seed": seed,
                             "condition": condition,
                             "favorable_shared_linear_task": condition == "favorable",
                             "real_users": False, "old_and_new_subspaces_separated": condition == "favorable"}}
    train_manifest = {**common, "parent": {"path": str(parent), "sha256": sha(parent)},
                      "datasets": {k: descs[k] for k in ("A", "keep_train")},
                      "protocol": {"ridge": 0.001, "keep_weight": 1.0,
                                   "min_B_relative_gain": 0.1, "max_keep_mse_increase": 0.0025}}
    eval_manifest = {**common, "datasets": {k: descs[k] for k in ("B", "keep_eval")}}
    write_json(root / "eval_manifest.json", eval_manifest)
    train_manifest["evaluation_commitment"] = {
        "registered_at_utc": now(), "B_sha256": descs["B"]["sha256"],
        "keep_eval_sha256": descs["keep_eval"]["sha256"],
        "eval_manifest_sha256": sha(root / "eval_manifest.json")}
    write_json(root / "train_manifest.json", train_manifest)
    write_json(root / "preregistered_protocol.json", {
        "train_manifest_sha256": sha(root / "train_manifest.json"),
        "condition": condition, "protocol": train_manifest["protocol"],
        **train_manifest["evaluation_commitment"]})
    return root / "train_manifest.json", root / "eval_manifest.json"


def suite(root, widths, seeds, conditions, output):
    root = Path(root).resolve()
    rows = []
    for condition, width, seed in [(c, w, s) for c in conditions for w in widths for s in seeds]:
            case = root / f"{condition}_w{width}_s{seed}"
            train_m, eval_m = synthetic_pair(case / "data", width, seed, condition)
            frozen = case / "frozen"
            subprocess.run([sys.executable, __file__, "train", "--manifest", str(train_m),
                            "--out", str(frozen)], check=True, stdout=subprocess.DEVNULL)
            result_path = case / "evaluation.json"
            subprocess.run([sys.executable, __file__, "evaluate", "--freeze", str(frozen / "freeze.json"),
                            "--manifest", str(eval_m), "--out", str(result_path)],
                           check=True, stdout=subprocess.DEVNULL)
            rows.append({"width": width, "seed": seed, "condition": condition, **load_json(result_path)})
    result = {"experiment": "PFT5", "schema": "pft5.suite.v1", "created_utc": now(),
              "dataset_kind": "synthetic_control", "results": rows,
              "synthetic_numeric_passes": sum(x["numeric_gate"] == "PASS" for x in rows),
              "n_cases": len(rows), "real_cross_user_gate": "BLOCKED_NO_REAL_CROSS_USER_DATA",
              "conclusion": "Synthetic protocol control only; no real A-to-B or runtime adoption acceptance."}
    write_json(output, result)
    return result


def protocol_checks(root, output):
    root, rows = Path(root).resolve(), []
    tm, em = synthetic_pair(root / "data", 8, 900, "favorable")
    def rejected(name, fn):
        try:
            fn()
        except ValueError as error:
            rows.append({"check": name, "rejected": True, "reason": str(error)})
        else:
            raise AssertionError(name + " was not rejected")
    receipt = train(tm, root / "frozen")
    bad = load_json(tm)
    bad["datasets"]["B"] = load_json(em)["datasets"]["B"]
    write_json(root / "bad_train.json", bad)
    rejected("trainer_rejects_B_manifest", lambda: train(root / "bad_train.json", root / "bad_out"))
    altered = load_json(em)
    altered["postfreeze_change"] = True
    write_json(root / "changed_eval.json", altered)
    rejected("changed_eval_commitment", lambda: evaluate(root / "frozen/freeze.json", root / "changed_eval.json", root / "bad.json"))
    duplicate = load_json(em)
    with np.load(load_json(tm)["datasets"]["A"]["path"], allow_pickle=False) as z:
        np.savez(root / "duplicate.npz", X=z["X"], Y=z["Y"], sample_ids=np.array([f"renamed{i}" for i in range(len(z["X"]))]))
    duplicate["datasets"]["B"].update(path=str(root / "duplicate.npz"), sha256=sha(root / "duplicate.npz"))
    write_json(root / "duplicate_eval.json", duplicate)
    committed = load_json(tm)
    committed["evaluation_commitment"].update(B_sha256=sha(root / "duplicate.npz"), eval_manifest_sha256=sha(root / "duplicate_eval.json"))
    write_json(root / "duplicate_train.json", committed)
    train(root / "duplicate_train.json", root / "duplicate_frozen")
    rejected("copied_XY_with_changed_ids", lambda: evaluate(root / "duplicate_frozen/freeze.json", root / "duplicate_eval.json", root / "bad.json"))
    candidate = Path(receipt["candidate"])
    candidate.chmod(0o644)
    candidate.write_bytes(candidate.read_bytes() + b"tamper")
    rejected("candidate_changed_after_freeze", lambda: evaluate(root / "frozen/freeze.json", em, root / "bad.json"))
    result = {"schema": "pft5.isolation_checks.v1", "checks": rows, "all_rejected": all(r["rejected"] for r in rows)}
    write_json(output, result)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    t = sub.add_parser("train")
    t.add_argument("--manifest", required=True)
    t.add_argument("--out", required=True)
    e = sub.add_parser("evaluate")
    e.add_argument("--freeze", required=True)
    e.add_argument("--manifest", required=True)
    e.add_argument("--out", required=True)
    s = sub.add_parser("suite")
    s.add_argument("--root", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--widths", default="8,16,32,64")
    s.add_argument("--seeds", default="0,1,2")
    s.add_argument("--conditions", default="favorable,conflicting")
    c = sub.add_parser("check-isolation")
    c.add_argument("--root", required=True)
    c.add_argument("--out", required=True)
    args = p.parse_args()
    if args.command == "train":
        result = train(args.manifest, args.out)
    elif args.command == "evaluate":
        result = evaluate(args.freeze, args.manifest, args.out)
    elif args.command == "check-isolation":
        result = protocol_checks(args.root, args.out)
    else:
        result = suite(args.root, [int(x) for x in args.widths.split(",")],
                       [int(x) for x in args.seeds.split(",")], args.conditions.split(","), args.out)
    print(json.dumps({k: v for k, v in result.items() if k not in
                     ("results", "training_sample_hashes", "training_content_hashes")}, indent=2))


if __name__ == "__main__":
    main()
