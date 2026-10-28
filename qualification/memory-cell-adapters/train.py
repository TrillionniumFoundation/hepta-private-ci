"""Single-process tensor training; this entry point cannot receive held wording."""

import argparse
import json
import os
from pathlib import Path
import resource
import sys
import time

import numpy as np
import torch
from torch.nn import functional as F

sys.path.insert(0, str(Path(__file__).resolve().parent))

from corpus import POLICIES, PROGRAMS, bits, canonical, digest, source_id
from routing import calibrate, labels
from split import distill_merge, fixed_experts, matched_high_rank, split_pair
from tensor_cell import CellConfig, OutputSpec, TensorCell, unique_parameter_count


SEMANTIC = (OutputSpec("bits", "binary", 12),)
SKILL = tuple(OutputSpec(f"op{i}", "multiclass", 7) for i in range(4))
ROUTER = (OutputSpec("role", "multiclass", 4), OutputSpec("entity", "multiclass", 9),
          OutputSpec("workflow", "multiclass", 9))


def values(kind, indexes, policies=POLICIES):
    if kind == "semantic":
        return {"bits": np.asarray([bits(policies[i]) for i in indexes], dtype=np.float32)}
    return {f"op{k}": np.asarray([PROGRAMS[i][k] for i in indexes]) for k in range(4)}


def take(targets, rows):
    return {name: target[rows] for name, target in targets.items()}


def exact(cell, features, targets):
    predictions = cell.predict(features)
    okay = np.ones(len(features), dtype=bool)
    for name, expected in targets.items():
        same = predictions[name] == expected
        okay &= same.all(axis=1) if same.ndim == 2 else same
    return {"correct": int(okay.sum()), "count": len(okay)}


def partition_from_gradients(cell, features, targets, indexes):
    """Data-driven proposal: group per-entity parameter-gradient directions."""
    began = time.perf_counter()
    gradients = []
    for entity in range(8):
        rows = np.asarray(indexes) == entity
        x = cell._features(features[rows])
        y = cell._targets(take(targets, rows), len(x))
        cell.zero_grad(set_to_none=True)
        loss = cell._loss(cell(x), y)
        gradient = torch.autograd.grad(loss, (cell.A, cell.B))
        vector = torch.cat([g.reshape(-1) for g in gradient]).detach().numpy()
        gradients.append(vector / max(np.linalg.norm(vector), 1e-12))
    points = np.asarray(gradients)
    pairwise = ((points[:, None] - points[None, :]) ** 2).sum(2)
    a, b = np.unravel_index(pairwise.argmax(), pairwise.shape)
    centers = points[[a, b]].copy()
    assignments = np.zeros(8, dtype=np.int64)
    for _ in range(32):
        new = ((points[:, None] - centers[None, :]) ** 2).sum(2).argmin(1)
        if len(set(new.tolist())) < 2:
            # Explicit degenerate proposal, never silently an oracle partition.
            new = np.arange(8) % 2
            reason = "degenerate gradients: deterministic fallback"
            break
        if np.array_equal(new, assignments):
            break
        assignments = new
        centers = np.asarray([points[new == k].mean(0) for k in range(2)])
    else:
        reason = "iteration limit"
    assignments = new
    return assignments, {"method": "two-means on normalized per-entity adapter gradients",
                         "assignments": assignments.tolist(), "gradient_sha256": digest(points.astype("<f4").tobytes()),
                         "wall_seconds": time.perf_counter() - began,
                         "reason": locals().get("reason", "converged"), "held_access": False}


def run(args):
    began, cpu = time.perf_counter(), time.process_time()
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    data = json.loads(args.development.read_bytes())
    protocol = json.loads(args.protocol.read_bytes())
    config = protocol["model"]
    features = np.load(args.features, allow_pickle=False)
    X, C = features["train"], features["calibration"]
    original = {kind: features[kind] for kind in ("semantic", "skill")}
    identity = json.loads(args.encoder_receipt.read_bytes())["base_encoder_sha"]
    args.output.mkdir(parents=True, exist_ok=False)
    seed_receipts = []
    for seed in protocol["seeds"]:
        root = args.output / f"seed-{seed}"
        root.mkdir()
        fits = []

        def new(name, outputs, rank=4):
            return TensorCell(CellConfig(name, rank=rank, outputs=outputs, seed=seed), identity)

        def fit(cell, x, y, ids, steps, train_head=None):
            receipt = cell.fit(x, y, source_ids=ids, steps=steps, batch_size=config["batch_size"],
                               lr=config["lr"], seed=seed, train_head=train_head)
            fits.append({"cell_id": cell.config.cell_id, **receipt})
            return receipt

        memories, samples = {}, {}
        for kind, specs in (("semantic", SEMANTIC), ("skill", SKILL)):
            key = "entity" if kind == "semantic" else "workflow"
            selected = [i for i, row in enumerate(data["train"]) if row["role"] == kind]
            indexes = np.asarray(list(range(8)) + [data["train"][i][key] for i in selected])
            x = np.concatenate([original[kind], X[selected]], axis=0)
            y = values(kind, indexes)
            ids = [source_id(kind, int(i)) for i in indexes]
            cell = new(kind, specs)
            cell.source_ids.update(ids)
            cell.save(root / f"{kind}-zero")
            fit(cell, x, y, ids, config["memory_steps"])
            cell.save(root / kind)
            control = cell.without_adapter(f"{kind}-head-only")
            control.save(root / f"{kind}-head-only")
            memories[kind] = cell
            samples[kind] = (x, y, ids, indexes)

        router = new("router", ROUTER)
        fit(router, X, labels(data["train"]), [digest(r["id"].encode()) for r in data["train"]], config["router_steps"])
        router.save(root / "router")
        route_selection = calibrate(router, C, data["calibration"])
        (root / "route-selection.json").write_bytes(canonical(route_selection))

        selected = [i for i, row in enumerate(data["train"]) if row["role"] == "compose"]
        joint_y = {**values("semantic", [data["train"][i]["entity"] for i in selected]),
                   **values("skill", [data["train"][i]["workflow"] for i in selected])}
        # Each task receives half the joint objective, matching the two
        # separately trained task losses; target exposure is equal per task.
        joint = new("joint", (OutputSpec("bits", "binary", 12, weight=4),) + SKILL, rank=8)
        joint.source_ids.update(source_id(kind, i) for kind in ("semantic", "skill") for i in range(8))
        fit(joint, X[selected], joint_y, [digest(data["train"][i]["id"].encode()) for i in selected], config["joint_steps"])
        joint.save(root / "joint")

        parent = memories["semantic"]
        x, _, ids, indexes = samples["semantic"]
        shifted = [tuple(((p[0]+3) % 16, p[1], p[2])) if i < 4 else p for i, p in enumerate(POLICIES)]
        target = values("semantic", indexes, shifted)
        structure_ids = [source_id("semantic", int(i), 2 if i < 4 else 0) for i in indexes]
        assignments, selection = partition_from_gradients(parent, x, target, indexes)
        static = np.arange(8) % 2
        children = split_pair(parent, ("dynamic-0", "dynamic-1"))
        experts = fixed_experts(parent, ("static-0", "static-1"))
        high = matched_high_rank(parent, "rank-8")
        for group, route in ((children, assignments), (experts, static)):
            for k, child in enumerate(group):
                selected_rows = route[indexes] == k
                # Preserve per-row expected exposure as well as total updates.
                allocated = 2*config["structure_steps"]*int(selected_rows.sum())//len(x)
                fit(child, x[selected_rows], take(target, selected_rows),
                    [structure_ids[i] for i in np.flatnonzero(selected_rows)], allocated, False)
                child.save(root / child.config.cell_id)
        fit(high, x, target, structure_ids, 2*config["structure_steps"], False)
        high.save(root / "rank-8")
        parameter_counts = {"dynamic": unique_parameter_count(children),
                            "static": unique_parameter_count(experts), "rank8": high.parameter_counts()}
        assert parameter_counts["dynamic"]["total"] == parameter_counts["static"]["total"] == parameter_counts["rank8"]["total"]
        assert parameter_counts["dynamic"]["trainable"] == parameter_counts["static"]["trainable"] == parameter_counts["rank8"]["trainable"]
        cal_rows = [i for i, row in enumerate(data["calibration"]) if row["role"] == "semantic"]
        cal_indexes = np.asarray([data["calibration"][i]["entity"] for i in cal_rows])
        cal_x, cal_y = C[cal_rows], values("semantic", cal_indexes, shifted)

        def routed_score(cells, routes):
            scores = [exact(cells[k], cal_x[routes[cal_indexes] == k],
                            take(cal_y, routes[cal_indexes] == k)) for k in range(2)]
            return {name: sum(s[name] for s in scores) for name in ("correct", "count")}

        structure_scores = {"dynamic": routed_score(children, assignments),
                            "static": routed_score(experts, static), "rank8": exact(high, cal_x, cal_y)}
        canonical_targets = values("semantic", range(8), shifted)

        def canonical_score(cells, routes):
            scores = [exact(cells[k], original["semantic"][routes == k],
                            take(canonical_targets, routes == k)) for k in range(2)]
            return {name: sum(s[name] for s in scores) for name in ("correct", "count")}

        canonical_scores = {"dynamic": canonical_score(children, assignments),
                            "static": canonical_score(experts, static),
                            "rank8": exact(high, original["semantic"], canonical_targets)}
        admit = (structure_scores["dynamic"]["correct"] > max(structure_scores[k]["correct"] for k in ("static", "rank8"))
                 and canonical_scores["dynamic"]["correct"] >= max(canonical_scores[k]["correct"] for k in ("static", "rank8")))
        merged, merge_fit = distill_merge(children, x, assignments[indexes], source_ids=structure_ids,
                                           cell_id="merged", rank=4, steps=config["merge_steps"],
                                           batch_size=config["batch_size"], lr=config["lr"], seed=seed)
        fits.append({"cell_id": "merged", **merge_fit})
        merged.save(root / "merged")
        merge_score = exact(merged, cal_x, cal_y)
        merge_canonical = exact(merged, original["semantic"], canonical_targets)
        structure = {"selection": selection, "static_assignments": static.tolist(),
                     "parameter_counts": parameter_counts, "calibration": structure_scores,
                     "canonical": canonical_scores,
                     "split_admitted": admit, "split_reason": "strict calibration gain" if admit else "no strict gain over both controls",
                     "merge_calibration": merge_score,
                     "merge_canonical": merge_canonical,
                     "merge_admitted": (merge_score["correct"] >= structure_scores["dynamic"]["correct"]
                                        and merge_canonical["correct"] >= canonical_scores["dynamic"]["correct"]),
                     "shifted_policies": shifted, "held_results_used": False}
        (root / "structure.json").write_bytes(canonical(structure))
        (root / "structure-routing.json").write_bytes(canonical({
            "assignments": assignments.tolist(), "static_assignments": static.tolist(),
            "split_admitted": structure["split_admitted"], "merge_admitted": structure["merge_admitted"]}))

        # Corrections and deletion have independent parameter versions.
        corrected = list(POLICIES)
        corrected[0] = (5, 4, 15)
        changed_ids = [source_id("semantic", int(i), 1 if i == 0 else 0) for i in indexes]
        candidate = TensorCell.load(root / "semantic", identity)
        before = exact(candidate, original["semantic"], values("semantic", range(8), corrected))
        fit(candidate, x, values("semantic", indexes, corrected), changed_ids, config["memory_steps"])
        candidate.save(root / "semantic-corrected")
        correction = {"before": before, "after": exact(candidate, original["semantic"], values("semantic", range(8), corrected)),
                      "retention": exact(candidate, original["semantic"][1:], values("semantic", range(1, 8))),
                      "new_policy": list(corrected[0]), "new_source_id": source_id("semantic", 0, 1)}
        remaining = indexes != 1
        rebuilds = []
        for name in ("semantic-rebuilt", "semantic-independent-clean"):
            clean = new(name, SEMANTIC)
            fit(clean, x[remaining], take(values("semantic", indexes, corrected), remaining),
                [changed_ids[i] for i in np.flatnonzero(remaining)], config["memory_steps"])
            clean.save(root / name)
            rebuilds.append(clean)
        deletion = {"deleted_source": source_id("semantic", 1),
                    "clean_counterfactual_parameter_equal": rebuilds[0].parameter_digest() == rebuilds[1].parameter_digest(),
                    "deleted_source_in_rebuild": source_id("semantic", 1) in rebuilds[0].source_ids,
                    "retained": exact(rebuilds[0], original["semantic"][[0, 2, 3, 4, 5, 6, 7]], values("semantic", [0, 2, 3, 4, 5, 6, 7], corrected))}
        (root / "maintenance.json").write_bytes(canonical({"correction": correction, "deletion": deletion}))
        summary = {"seed": seed, "fits": fits, "router_selection": route_selection,
                   "canonical_memory": {kind: exact(memories[kind], original[kind], values(kind, range(8))) for kind in memories},
                   "structure": structure, "maintenance": {"correction": correction, "deletion": deletion},
                   "model_parameter_counts": {kind: cell.parameter_counts() for kind, cell in {**memories, "router": router, "joint": joint}.items()}}
        (root / "training.json").write_bytes(canonical(summary))
        seed_receipts.append(summary)
    receipt = {"schema": "hepta.memory.adapter-training.v1", "pid": os.getpid(), "held_file_opened": False,
               "protocol_sha256": digest(args.protocol.read_bytes()), "development_sha256": digest(args.development.read_bytes()),
               "features_sha256": digest(args.features.read_bytes()), "encoder_sha": identity,
               "seeds": seed_receipts, "wall_seconds": time.perf_counter()-began,
               "cpu_seconds": time.process_time()-cpu, "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
               "model_files_bytes": sum(p.stat().st_size for p in args.output.rglob("*") if p.is_file())}
    (args.output / "TRAINING.json").write_bytes(canonical(receipt))
    print(json.dumps({k: v for k, v in receipt.items() if k != "seeds"}, sort_keys=True))


def main():
    parser = argparse.ArgumentParser()
    for name in ("development", "features", "protocol", "encoder-receipt", "output"):
        parser.add_argument("--"+name, type=Path, required=True)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
