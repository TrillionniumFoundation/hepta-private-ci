"""One sealed evaluation on new source pixels and real delivered bytes."""

import json
from pathlib import Path
import shutil
import time

import numpy as np
import torch

from ...v6.data import make_batch, render_tokens
from ...v6.neural import parameter_hash
from ...v6.observer import METRIC_DIGEST, observe_tensors, read_bundle, write_bundle
from ...v6.plan_training import ControlledSnapshot
from ...repair_20261026.joint.train import deploy
from .data import fresh_corpus, historical_corpus
from .protocol import PROTOCOL as P, checksum, write_json
from .run import reference_observer


def joint_ce(table):
    """Mean per-fixed-seed CE over source pairs and repeated conditions."""
    z = -P["gamma"] * np.asarray(table, dtype=np.float64)
    maximum = z.max(axis=(1, 2), keepdims=True)
    return float(np.mean(-(np.log(np.exp(z - maximum).mean(axis=(1, 2)))
                           + maximum[:, 0, 0]) / P["gamma"]))


def analyze(rows):
    tables, summaries = {}, {}
    for split, count, conditions in (("test", P["test_pairs"], P["conditions"]),
                                      ("retention", P["retention_pairs"], ["clean"])):
        for arm in P["arms"]:
            table = np.full((len(P["seeds"]), count, len(conditions)), np.nan)
            selected = [r for r in rows if r["split"] == split and r["arm"] == arm]
            for row in selected:
                idx = P["seeds"].index(row["seed"]), row["pair"], conditions.index(row["condition"])
                if np.isfinite(table[idx]):
                    raise ValueError("Repeated evaluation observation")
                table[idx] = row["audit"]["utility"]
            if not np.isfinite(table).all():
                raise ValueError("Incomplete held-out grid")
            tables[split, arm] = table
            summaries[f"{split}/{arm}"] = {"audit_ce": joint_ce(table), "mean_audit_utility": float(table.mean()),
                "mean_inference_cpu_ms": float(np.mean([r["cpu_ns_per_example"] for r in selected])) / 1e6,
                "mean_inference_wall_ms": float(np.mean([r["wall_ns_per_example"] for r in selected])) / 1e6,
                "plan_counts": np.bincount([r["plan"] for r in selected], minlength=4).tolist()}
    comparisons = []
    rng = np.random.default_rng(P["bootstrap_seed"])
    for split in ("test", "retention"):
        for candidate, baseline in (("joint_risk", "frozen"), ("joint_risk", "joint_uniform"),
                                    ("joint_uniform", "frozen")):
            x, y = tables[split, candidate], tables[split, baseline]
            samples = []
            for _ in range(P["bootstrap_replicates"]):
                indices = rng.integers(x.shape[1], size=x.shape[1])
                samples.append(joint_ce(x[:, indices]) - joint_ce(y[:, indices]))
            alpha = (1 - P["interval"]) / 2
            comparisons.append({"split": split, "comparison": candidate + "-" + baseline,
                "ce_difference": joint_ce(x) - joint_ce(y),
                "paired_97_5_interval": np.quantile(samples, [alpha, 1 - alpha]).tolist(),
                "per_seed_ce_differences": [joint_ce(a[None]) - joint_ce(b[None]) for a, b in zip(x, y)],
                "source_pairs": x.shape[1], "fixed_seeds": P["seeds"]})
    def passes(comparison):
        quality = next(r for r in comparisons if r["split"] == "test" and r["comparison"] == comparison)
        retention = next(r for r in comparisons if r["split"] == "retention" and r["comparison"] == comparison)
        return (quality["paired_97_5_interval"][0] > 0
                and min(quality["per_seed_ce_differences"]) > 0
                and retention["paired_97_5_interval"][0] >= -P["retention_noninferiority_margin"])
    return {"schema": "hepta.ndu.actual-moment-qualification.v1", "summaries": summaries,
        "comparisons": comparisons, "generator_update_gate_passed": passes("joint_risk-frozen"),
        "matched_training_gate_passed": passes("joint_risk-joint_uniform"),
        "all_joint_acceptance_gates_passed": passes("joint_risk-frozen") and passes("joint_risk-joint_uniform"),
        "raw_delivered_bundles": len(rows), "actual_media_files": len(rows) * 2,
        "same_information_compute_comparison": "joint_risk vs joint_uniform; frozen receives no new optimization",
        "writer_population_or_training_seed_population_inference": False,
        "exact_actual_reward_generator_gradient": False, "natural_av_generation": False,
        "native_owner_integration": False, "test_used_for_selection": False,
        "timing": "descriptive one-host batches of32; inference includes encoder, gate, two transitions and decoder; delivery measured separately"}


def evaluate_snapshot(snapshot, corpus, audit, reward, seed, arm, output, stream):
    model, gate = snapshot._base._model, snapshot._gate
    before = parameter_hash(model), parameter_hash(gate)
    rows = []
    for split, count, conditions in (("test", P["test_pairs"], P["conditions"]),
                                      ("retention", P["retention_pairs"], ["clean"])):
        for k, condition in enumerate(conditions):
            for start in range(0, count, 32):
                n = min(32, count - start)
                batch = make_batch(corpus, split, n, P["evaluation_seed"] + start + k * 10000,
                                   corruption=condition, offset=start)
                rng = torch.Generator().manual_seed(seed * 100003 + start + k * 1009)
                noise = torch.randn(n, model.hidden, generator=rng)
                wall, cpu = time.perf_counter_ns(), time.process_time_ns()
                with torch.inference_mode():
                    generated, choices = deploy(model, gate, batch.observation, noise)
                elapsed_wall, elapsed_cpu = time.perf_counter_ns() - wall, time.process_time_ns() - cpu
                decoded, captions, receipts = [], [], []
                delivery_start = time.perf_counter_ns()
                for j in range(n):
                    caption = render_tokens(generated.token_ids[j])
                    paths = write_bundle(output / "outputs" / f"{seed}-{arm}" / split / condition / str(start + j),
                                         caption, generated.image_logits[j].sigmoid())
                    pixels, restored_caption, hashes = read_bundle(paths)
                    decoded.append(pixels)
                    captions.append(restored_caption)
                    receipts.append({"paths": {key: str(Path(value).relative_to(output)) for key, value in paths.items()},
                                     "sha256": hashes})
                delivery_ns = time.perf_counter_ns() - delivery_start
                pixels = torch.cat(decoded)
                audit_scores = observe_tensors(audit, pixels, captions, batch.target.pixels, batch.target.labels)
                reward_scores = observe_tensors(reward, pixels, captions, batch.target.pixels, batch.target.labels)
                for j in range(n):
                    row = {"seed": seed, "arm": arm, "split": split, "condition": condition,
                        "pair": start + j, "source_ids": batch.source_ids[j], "plan": int(choices[j]),
                        "private_labels": batch.target.labels[j].tolist(), "caption": captions[j],
                        "audit": audit_scores[j], "reward": reward_scores[j], "artifacts": receipts[j],
                        "cpu_ns_per_example": elapsed_cpu / n, "wall_ns_per_example": elapsed_wall / n,
                        "delivery_ns_per_example": delivery_ns / n,
                        "logical_budget": {"encoder": 1, "gate": 1, "transitions": 2, "decoder": 1}}
                    stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
                    rows.append(row)
                stream.flush()
    if before != (parameter_hash(model), parameter_hash(gate)):
        raise RuntimeError("Qualification changed inference weights")
    return rows


def qualify(assets, development, output):
    assets, development, output = Path(assets), Path(development), Path(output)
    completed = json.loads((development / "DEVELOPMENT_COMPLETED.json").read_text())
    if completed["seeds"] != P["seeds"] or completed["steps"] != P["steps"]:
        raise ValueError("Full predeclared development grid required")
    if json.loads((development / "DEVELOPMENT_PROTOCOL.json").read_text()) != P:
        raise ValueError("Development protocol differs from qualification")
    if completed["selection_sha256"] != checksum(development / "SELECTIONS.json"):
        raise ValueError("Frozen selections changed")
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(P["threads"])
    torch.use_deterministic_algorithms(True)
    historical = historical_corpus(assets)
    corpus = fresh_corpus(assets, historical)
    write_json(output / "FRESH_SOURCE_MANIFEST.json", corpus.manifest)
    selected = json.loads((development / "SELECTIONS.json").read_text())
    expected = {(seed, arm) for seed in P["seeds"] for arm in P["arms"][1:]}
    if {(r["seed"], r["arm"]) for r in selected} != expected or len(selected) != len(expected):
        raise ValueError("Incomplete selected model set")
    for choice in selected:
        if checksum(development / choice["selected_path"]) != choice["selected_checkpoint_sha256"]:
            raise ValueError("A selected model changed before the qualification seal")
    restoration = json.loads((development / "RESTORATION.json").read_text())
    if restoration["archive_sha256"] != P["base_archive_sha256"]:
        raise ValueError("Baseline archive receipt changed")
    pins = {row["path"]: row["sha256"] for row in restoration["selected_files"]}
    names = [f"ndu-runs/full-002/seed-{seed}-terminal_entropic_ndu.pt" for seed in P["seeds"]]
    names += [f"ndu-runs/full-002/{name}-observer.pt" for name in ("audit", "reward")]
    reference_pins = {}
    for name in names:
        if checksum(assets / name) != pins[name]:
            raise ValueError("Pinned reference bytes changed before qualification")
        reference_pins[name] = pins[name]
    sources = {p.name: checksum(p) for p in Path(__file__).resolve().parent.glob("*.py")}
    sealed = {"schema": "hepta.ndu.joint-qualification-seal.v1", "protocol": P,
        "selection_sha256": completed["selection_sha256"], "development": str(development),
        "source_sha256": sources, "source_manifest_sha256": checksum(output / "FRESH_SOURCE_MANIFEST.json"),
        "reference_checkpoint_file_sha256": reference_pins, "metric_sha256": METRIC_DIGEST,
        "restoration_receipt_sha256": checksum(development / "RESTORATION.json"),
        "selected_models": [{k: r[k] for k in ("seed", "arm", "selected_path", "selected_checkpoint_sha256")}
                            for r in selected], "test_predictions_computed": False, "audit_observer_loaded": False}
    write_json(output / "QUALIFICATION_SEAL.json", sealed)
    (output / "executed-source").mkdir()
    for path in Path(__file__).resolve().parent.glob("*.py"):
        shutil.copyfile(path, output / "executed-source" / path.name)
    # Selection and source identity are sealed before audit model access.
    audit, reward = reference_observer(assets, "audit"), reference_observer(assets, "reward")
    rows = []
    with (output / "ROWS.jsonl").open("x") as stream:
        for seed in P["seeds"]:
            for arm in P["arms"]:
                if arm == "frozen":
                    model = ControlledSnapshot.load(assets / f"ndu-runs/full-002/seed-{seed}-terminal_entropic_ndu.pt")
                else:
                    choice = next(r for r in selected if r["seed"] == seed and r["arm"] == arm)
                    model = ControlledSnapshot.load(development / choice["selected_path"],
                                                    expected_file_sha256=choice["selected_checkpoint_sha256"])
                current = evaluate_snapshot(model, corpus, audit, reward, seed, arm, output, stream)
                rows.extend(current)
                print(f"qualified seed={seed} arm={arm} actual_bundles={len(current)}", flush=True)
    result = analyze(rows)
    from .oracle import compare_to_oracle, original_oracle
    oracle_rows = original_oracle(assets, corpus, audit, output)
    attribution = compare_to_oracle(rows, oracle_rows)
    result["generator_attribution"] = attribution
    result["all_joint_acceptance_gates_passed"] = bool(result["all_joint_acceptance_gates_passed"] and attribution["attribution_gate_passed"])
    result.update(seal_sha256=checksum(output / "QUALIFICATION_SEAL.json"), rows_sha256=checksum(output / "ROWS.jsonl"),
                  audit_observer_sha256=parameter_hash(audit), reward_observer_sha256=parameter_hash(reward))
    write_json(output / "RESULT.json", result)
    print(json.dumps({"generator_gate": result["generator_update_gate_passed"],
                      "matched_gate": result["matched_training_gate_passed"], "comparisons": result["comparisons"]}), flush=True)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--development", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    qualify(args.assets, args.development, args.output)
