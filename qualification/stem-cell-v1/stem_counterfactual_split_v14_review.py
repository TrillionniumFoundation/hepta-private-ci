"""Separate NumPy numeric replay and original-label scorer for V14.

Does NOT import Torch or the training producer. Verifies original archive bytes,
saved candidate tensors, all six held profiles, calibration selection and costs.
It does not re-execute gradients or attest an independent model/host custodian.
"""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import numpy as np
from safetensors.numpy import load

ARCHIVE_SHA = "0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7"
FEATURE_SHA = "e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490"
DATA_SHA = "50335a2214756c7a9e09fee9ac9ed27ab855ea98635bb0fab0998144165ffb2c"
INPUT_SHA = "d029f906565946216126db39e4ca3f4f14d7ab5a3c297ec2a62639ccdfbf604a"
SCHEMA = "hepta.stem.counterfactual-split.v14.research"
ARMS = ("frozen", "continued", "wide", "split")
PROFILES = ARMS + ("shuffled_route", "swapped_route")


def demand(ok, why):
    if not ok:
        raise ValueError(why)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(x):
    return json.dumps(x, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def pairs(items):
    result = {}
    for key, value in items:
        demand(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def bounded(path):
    path = Path(path)
    demand(not path.is_symlink() and path.is_file() and path.stat().st_size < 8_000_000,
           "bounded regular evidence required")
    return path.read_bytes()


def probability(logits):
    logits = logits.astype(np.float64)
    ex = np.exp(logits - logits.max(1, keepdims=True))
    return ex / ex.sum(1, keepdims=True)


def route(x, centers):
    d = (x * x).sum(1, keepdims=True) - 2 * x @ centers.T + (centers * centers).sum(1)
    return np.argmin(d, axis=1)


def logits(state, arm, x, routes=None):
    if arm in ("frozen", "continued"):
        return x @ state["weight"].T + state["bias"]
    if arm == "wide":
        base = x @ state["parent.weight"].T + state["parent.bias"]
        hidden = np.tanh(x @ state["residual.0.weight"].T + state["residual.0.bias"])
        return base + hidden @ state["residual.2.weight"].T + state["residual.2.bias"]
    r = route(x, state["centers"]) if routes is None else routes
    result = np.empty((len(x), 4), dtype=np.float32)
    for cell in (0, 1):
        ix = np.flatnonzero(r == cell)
        result[ix] = x[ix] @ state[f"heads.{cell}.weight"].T + state[f"heads.{cell}.bias"]
    return result


def score(p, y):
    return {"correct": int((p.argmax(1) == y).sum()), "cases": len(y),
            "brier": float(((p - np.eye(4)[y]) ** 2).sum(1).mean())}


def choose(cal, old):
    resident = {"frozen": 1540, "continued": 1540, "wide": 3878, "split": 3848}
    allowed = ["frozen"] + [a for a in ARMS[1:] if cal["frozen"] - cal[a] > .01
                             and old[a] - old["frozen"] <= .01]
    rank = lambda a: (cal[a] + .01 * resident[a] / 4096, ARMS.index(a))
    winner = min(allowed, key=rank)
    if winner in ("wide", "split") and cal["continued"] - cal[winner] <= .01:
        winner = min([a for a in allowed if a in ("frozen", "continued")], key=rank)
    return winner


def review(archive, inputs, candidates):
    archive, inputs, candidates = Path(archive), Path(inputs), Path(candidates)
    # Freeze/read completed prediction bytes before opening original publisher labels.
    sealed = bounded(candidates / "predictions.json")
    report = json.loads(sealed, object_pairs_hook=pairs)
    encode(report)  # reject nonfinite JSON before any comparisons
    source = Path(__file__).with_name("stem_counterfactual_split_v14.py")
    demand(report["source_sha256"] == digest(bounded(source)), "producer source bytes differ")
    demand(report["schema"] == SCHEMA and report["archive_sha256"] == ARCHIVE_SHA
           and report["feature_sha256"] == FEATURE_SHA and report["input_sha256"] == INPUT_SHA
           and report["production_authorized"] is False
           and report["prospective_efficacy_verified"] is False
           and report["new_encoder_forwards"] == 0 and set(report["seeds"]) == {"41", "47", "53"},
           "wrong source, census or authority claim")
    demand(digest(bounded(inputs / "input.json")) == INPUT_SHA, "input identity changed")
    demand(digest(bounded(archive)) == ARCHIVE_SHA, "not the original archive")
    with ZipFile(archive) as z:
        data = z.read("hepta-public-study/dataset.jsonl")
        raw = z.read("hepta-public-study/execution/frozen-features/features.safetensors")
    demand(digest(data) == DATA_SHA and digest(raw) == FEATURE_SHA, "original bytes differ")
    records = [json.loads(line) for line in data.splitlines()]
    features = load(raw)["features"]
    indexes = {name: [i for i, r in enumerate(records) if r["split"] == name]
               for name in ("train", "calibration", "holdout")}
    hx, cx = features[indexes["holdout"]], features[indexes["calibration"]]
    tx = features[indexes["train"]][:32]
    hy = np.array([records[i]["label"] for i in indexes["holdout"]])
    cy = np.array([records[i]["label"] for i in indexes["calibration"]])
    ty = np.array([records[i]["label"] for i in indexes["train"][:32]])
    demand(report["case_ids"] == [records[i]["case_id"] for i in indexes["holdout"]], "held source swap")
    outcomes, deviations = {}, []
    for seed in (41, 47, 53):
        row = report["seeds"][str(seed)]
        demand(set(row["models"]) == set(ARMS) and set(row["held_predictions"]) == set(PROFILES)
               and row["frozen_parent_unchanged"] is True and row["inheritance_checked"] is True,
               "candidate/profile/inheritance census changed")
        states, cal, old = {}, {}, {}
        sizes = {}
        for arm in ARMS:
            slot = row["models"][arm]
            name = f"{seed}-{arm}.safetensors"
            demand(slot["file"] == name, "foreign model path")
            b = bounded(candidates / name)
            demand(digest(b) == slot["file_sha256"], "saved candidate bytes changed")
            state = load(b)
            if arm in ("frozen", "continued"):
                shapes = {"weight": (4, 384), "bias": (4,)}
            elif arm == "wide":
                shapes = {"parent.weight": (4, 384), "parent.bias": (4,),
                    "residual.0.weight": (6, 384), "residual.0.bias": (6,),
                    "residual.2.weight": (4, 6), "residual.2.bias": (4,)}
            else:
                shapes = {"centers": (2, 384), "heads.0.weight": (4, 384), "heads.0.bias": (4,),
                          "heads.1.weight": (4, 384), "heads.1.bias": (4,)}
            demand(set(state) == set(shapes) and all(state[k].shape == shape
                and state[k].dtype == np.float32 and np.isfinite(state[k]).all()
                for k, shape in shapes.items()), "wrong physical tensor census")
            count = sum(x.size for x in state.values())
            buffers = 768 if arm == "split" else 0
            demand(slot["parameter_scalars"] == count - buffers and slot["buffer_scalars"] == buffers
                   and slot["resident_bytes"] == 4 * count and count <= 4096
                   and slot["gradient_scalars"] == (0 if arm == "frozen" else count - buffers)
                   and slot["optimizer_state_scalars"] == 0,
                   "false parameter budget")
            h = hashlib.sha256()
            for key, value in sorted(state.items()):
                h.update(key.encode() + b"\0" + encode(list(value.shape)) + b"\0"
                         + value.astype("<f4", copy=False).tobytes())
            demand(h.hexdigest() == slot["parameter_sha256"], "false physical parameter digest")
            states[arm] = state
            sizes[arm] = count
            cal[arm] = score(probability(logits(state, arm, cx)), cy)["brier"]
            old[arm] = score(probability(logits(state, arm, tx)), ty)["brier"]
            demand(abs(cal[arm] - row["calibration_brier"][arm]) < 5e-5
                   and abs(old[arm] - row["old_train_brier"][arm]) < 5e-5,
                   "false calibration or old-fit evidence")
        chosen = choose(cal, old)
        demand(chosen == row["selected_research_candidate"], "selection not reproduced")
        r = route(hx, states["split"]["centers"])
        shuffled = r[np.random.default_rng(seed ^ 0x1414).permutation(len(hx))]
        demand(r.tolist() == row["held_routes"] and shuffled.tolist() == row["shuffled_routes"],
               "wrong source-based routes")
        scores = {}
        for profile in PROFILES:
            arm = profile if profile in ARMS else "split"
            routing = shuffled if profile == "shuffled_route" else 1 - r if profile == "swapped_route" else None
            p = probability(logits(states[arm], arm, hx, routing))
            saved = np.asarray(row["held_predictions"][profile], dtype=np.float64)
            demand(saved.shape == (32, 4) and np.isfinite(saved).all()
                   and (saved >= 0).all() and (saved <= 1).all()
                   and np.allclose(saved.sum(1), 1, atol=1e-6, rtol=0), "invalid predictions")
            error = float(np.max(np.abs(p - saved)))
            demand(error <= 5e-5 and np.array_equal(p.argmax(1), saved.argmax(1)), "numeric prediction drift")
            deviations.append(error)
            scores[profile] = score(p, hy)
        work = row["work"]
        demand(set(work) == {"parent", "continued", "wide", "split"}
               and all(v["steps"] == 80 and v["examples"] == 1280 for v in work.values())
               and work["split"]["selected_head_rows"] == 1280
               and len({work[a]["schedule_sha256"] for a in ARMS[1:]}) == 1
               and all(type(v[k]) is int and v[k] >= 0 for v in work.values()
                       for k in ("process_cpu_ns", "wall_ns")), "training work mismatch")
        outcomes[str(seed)] = {"held_scores": scores, "calibration_brier": cal,
            "old_train_brier": old, "selected_research_candidate": chosen,
            "parameter_digests": {a: row["models"][a]["parameter_sha256"] for a in ARMS},
            "resident_scalars": sizes, "optimizer_steps": sum(v["steps"] for v in work.values()),
            "training_cpu_ns": sum(v["process_cpu_ns"] for v in work.values()),
            "training_wall_ns": sum(v["wall_ns"] for v in work.values())}
    return {"schema": SCHEMA + ".numpy-review", "archive_sha256": ARCHIVE_SHA,
        "producer_source_sha256": report["source_sha256"], "prediction_file_sha256": digest(sealed),
        "status": "NUMERIC_REPLAY_NOT_PROSPECTIVE_EFFICACY", "seeds": outcomes,
        "unique_held_cases": 32, "repeated_seeds": 3, "numeric_profiles_recomputed": 18,
        "max_probability_error": max(deviations), "new_encoder_forwards": 0,
        "optimizer_steps_executed_in_producer": 960, "torch_imported_by_reviewer": False,
        "independent_gradient_reexecution": False, "equal_active_flops": False,
        "independent_source_groups_verified": False, "production_authorized": False,
        "prospective_efficacy_verified": False, "deployment_selected": False}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive", required=True)
    p.add_argument("--inputs", required=True)
    p.add_argument("--candidates", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    result = review(a.archive, a.inputs, a.candidates)
    with Path(a.output).open("xb") as stream:
        stream.write(encode(result) + b"\n")
