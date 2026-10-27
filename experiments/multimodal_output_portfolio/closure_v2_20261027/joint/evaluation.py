"""Sealed qualification of actual compressed PNG/UTF8 delivery containers."""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import time
import zipfile

import numpy as np
from PIL import Image
import torch

from ...v6.data import (SourceCorpus, SourceSplit, _parse_images, _parse_labels,
                       make_batch, render_tokens)
from ...v6.neural import parameter_hash
from ...v6.observer import METRIC_DIGEST, observe_tensors
from ...repair_20261026.joint.train import deploy
from ...continuation_20261027.joint.run import reference_observer
from .actor import LatentActor, LatentSnapshot
from .grid_guard import verify_development_run
from .protocol import PROTOCOL as P, checksum, write_json
from .run import base_model
from .qualification_guard import (QUALIFICATION_CONTRACT as Q, label_pin,
                                  verify_density, verify_source_grid)


def qualification_corpus(assets, allocation):
    manifest = json.loads(allocation.read_text())
    source = assets / "ndu-data"
    raw = source / "t10k-images-idx3-ubyte.gz"
    if checksum(raw) != manifest["official_test_image_sha256"]:
        raise ValueError("Official qualification inputs changed")
    images, hashes = _parse_images(gzip.decompress(raw.read_bytes()))
    label_pin(assets)
    labels = _parse_labels(gzip.decompress((source / "t10k-labels-idx1-ubyte.gz").read_bytes()))
    if len(images) != Q["official_image_count"] or len(labels) != len(images):
        raise ValueError("Official image/label cardinality differs")
    splits = {}
    for split in ("test", "retention"):
        entry = manifest["splits"]["joint_" + split]
        ids = tuple(entry["source_ids"])
        if hashlib.sha256("\n".join(ids).encode()).hexdigest() != entry["identity_sha256"]:
            raise ValueError("Qualification source identities changed")
        indices = [int(value.split(":")[2]) for value in ids]
        for index, identity in zip(indices, ids):
            if identity != f"mnist:test:{index}:{hashes[index]}":
                raise ValueError("Source index/pixel identity mismatch")
        splits[split] = SourceSplit(images[indices], labels[indices], ids,
                                    tuple(hashes[i] for i in indices))
    verify_source_grid(manifest, splits)
    return SourceCorpus(splits, manifest)


def deliver_batch(path, output):
    """Close the actual file before reopening its PNG and UTF8 members."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for index in range(len(output.token_ids)):
            array = (output.image_logits[index].sigmoid().detach().cpu().squeeze().numpy() * 255).round()
            if array.shape != (28, 56) or not np.isfinite(array).all() or array.min() < 0 or array.max() > 255:
                raise ValueError("Invalid generated pixels")
            stream = io.BytesIO()
            Image.fromarray(array.astype(np.uint8)).save(stream, format="PNG")
            archive.writestr(f"{index}/image.png", stream.getvalue())
            archive.writestr(f"{index}/caption.txt", render_tokens(output.token_ids[index]).encode("utf-8"))
    pixels, captions, receipts = [], [], []
    with zipfile.ZipFile(path) as archive:
        if len(archive.namelist()) != 2 * len(output.token_ids) or archive.testzip() is not None:
            raise ValueError("Delivery container member grid or CRC differs")
        for index in range(len(output.token_ids)):
            members = {kind: f"{index}/{name}" for kind, name in (("image", "image.png"), ("text", "caption.txt"))}
            raw = {kind: archive.read(member) for kind, member in members.items()}
            with Image.open(io.BytesIO(raw["image"])) as image:
                if image.format != "PNG" or image.mode != "L" or image.size != (56, 28):
                    raise ValueError("Invalid delivered PNG contract")
                pixels.append(torch.from_numpy(np.array(image, copy=True)).float()[None, None] / 255)
            captions.append(raw["text"].decode("utf-8"))
            receipts.append({"members": members, "sha256": {k: hashlib.sha256(v).hexdigest() for k, v in raw.items()}})
    return torch.cat(pixels), captions, receipts


def evaluate(base, actor, corpus, reward, audit, seed, arm, directory, stream):
    rows = []
    for split, count, conditions in (("test", P["test_pairs"], P["conditions"]),
                                      ("retention", P["retention_pairs"], ["clean"])):
        for ci, condition in enumerate(conditions):
            for start in range(0, count, 32):
                n = min(32, count - start)
                batch = make_batch(corpus, split, n, Q["corruption_seed_offset"] + P["evaluation_seed"] + start + ci * 10000,
                                   corruption=condition, offset=start)
                noise_seed = Q["generator_seed_offset"] + seed * 100003 + start + ci * 1009
                rng = torch.Generator().manual_seed(noise_seed)
                noise = torch.randn(n, base._base._model.hidden, generator=rng)
                residual_noise = torch.randn(n, P["dimensions"], generator=rng)
                started_wall, started_cpu = time.perf_counter_ns(), time.process_time_ns()
                with torch.inference_mode():
                    if actor is None:
                        generated, plans = deploy(base._base._model, base._gate, batch.observation, noise)
                        mean = torch.zeros_like(residual_noise)
                    else:
                        generated, plans, mean = actor.generate(batch.observation, noise, residual_noise)
                model_wall, model_cpu = time.perf_counter_ns() - started_wall, time.process_time_ns() - started_cpu
                path = directory / "outputs" / f"{seed}-{arm}" / f"{split}-{condition}-{start}.zip"
                decoded, captions, receipts = deliver_batch(path, generated)
                delivered_wall, delivered_cpu = time.perf_counter_ns() - started_wall, time.process_time_ns() - started_cpu
                # Evaluation observers run only after actual delivery and readback.
                reward_scores = observe_tensors(reward, decoded, captions, batch.target.pixels, batch.target.labels)
                audit_scores = observe_tensors(audit, decoded, captions, batch.target.pixels, batch.target.labels)
                for j in range(n):
                    row = {"seed": seed, "arm": arm, "split": split, "condition": condition,
                        "pair": start + j, "source_ids": batch.source_ids[j], "plan": int(plans[j]),
                        "private_labels": batch.target.labels[j].tolist(), "caption": captions[j],
                        "audit": audit_scores[j], "reward": reward_scores[j],
                        "delivery": {"archive": str(path.relative_to(directory)), **receipts[j]},
                        "latent_mean": mean[j].tolist(), "latent_noise_seed": noise_seed,
                        "model_cpu_ns_per_example": model_cpu / n, "model_wall_ns_per_example": model_wall / n,
                        "delivered_cpu_ns_per_example": delivered_cpu / n, "delivered_wall_ns_per_example": delivered_wall / n,
                        "logical_budget": {"encoder": 1, "gate": 1, "transitions": 2, "decoder": 1,
                            "actor": int(actor is not None), "latent_gaussian_dimensions": P["dimensions"]}}
                    stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
                    rows.append(row)
                stream.flush()
    return rows


def qualify(assets, prior, development, allocation, directory):
    completed = json.loads((development / "COMPLETED.json").read_text())
    if completed["steps_per_run"] != P["steps"] or completed["seeds"] != P["seeds"] or completed["total_steps_per_seed_per_objective"] != 2 * P["steps"]:
        raise ValueError("The complete fixed training budget is required")
    if completed["grid_specification_sha256"] != checksum(Path(__file__).with_name("STUDY_GRID.json")):
        raise ValueError("The pretest candidate grid changed")
    for run in completed["runs"]:
        source_run = Path(run["path"])
        if checksum(source_run / "PROTOCOL.json") != run["protocol_sha256"] or checksum(source_run / "SELECTIONS.json") != run["selection_sha256"]:
            raise ValueError("Candidate protocol/selection bytes changed")
        if verify_development_run(source_run) != run["development_pins"]:
            raise ValueError("The scored development checkpoint binding changed")
    if checksum(development / "SELECTIONS.json") != completed["selection_sha256"]:
        raise ValueError("Selection bytes changed")
    if checksum(development / "BUDGET_ACCOUNTING.json") != completed["budget_sha256"]:
        raise ValueError("Matched information/compute accounting changed")
    choices = json.loads((development / "SELECTIONS.json").read_text())
    expected = {(seed, arm) for seed in P["seeds"] for arm in ("direct_mean", "direct_risk")}
    if len(choices) != len(expected) or {(r["seed"], r["arm"]) for r in choices} != expected:
        raise ValueError("Selected model grid differs")
    for row in choices:
        if not row["selected_eligible"]:
            raise ValueError("No retained-capability model passed validation; do not spend a new test set")
        if row["kind"] == "stochastic_actor" and checksum(development / row["selected_path"]) != row["selected_sha256"]:
            raise ValueError("Selected actor bytes changed")
    references = {str(seed): base_model(prior, seed)[1] for seed in P["seeds"]}
    if references != json.loads((development / "BASELINES.json").read_text()):
        raise ValueError("Strong baseline differs from training")
    density_pins = {}
    for row in choices:
        if row["kind"] == "original_fallback":
            density_pins[f"{row['seed']}/{row['arm']}"] = {"kind": "original_fallback", "sigma": 0.}
            continue
        base, _ = base_model(prior, row["seed"])
        actor = LatentSnapshot.load(development / row["selected_path"], base)
        density_pins[f"{row['seed']}/{row['arm']}"] = verify_density(actor, Path(row["source_run"]), row["seed"])
        if actor.sigma != row["sigma"]:
            raise ValueError("Selected and recorded latent sigma differ")
    official_labels = label_pin(assets)
    directory.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).resolve().parent
    (directory / "executed-source").mkdir()
    for path in source.glob("*.py"):
        shutil.copyfile(path, directory / "executed-source" / path.name)
    seal = {"schema": "hepta.ndu.direct-gradient-qualification-seal.v1", "protocol": P,
        "protocol_scope": "Algorithm defaults per run; actual selected sigma and the two-run total budget are specified below, not by the default sigma/steps alone.",
        "training_grid": completed,
        "training_grid_completed_sha256": checksum(development / "COMPLETED.json"),
        "training_budget_sha256": checksum(development / "BUDGET_ACCOUNTING.json"),
        "pretest_grid_specification_sha256": checksum(source / "STUDY_GRID.json"),
        "total_steps_per_seed_per_trained_objective": completed["total_steps_per_seed_per_objective"],
        "selection_sha256": checksum(development / "SELECTIONS.json"), "qualification_contract": Q,
        "official_label_pin": official_labels, "density_pins": density_pins,
        "development": str(development), "prior": str(prior), "allocation": str(allocation),
        "allocation_sha256": checksum(allocation), "base_checkpoints": references,
        "selected": [{k: r[k] for k in ("seed", "arm", "kind", "sigma", "source_run", "selected_path", "selected_sha256", "selected_step")} for r in choices],
        "metric_sha256": METRIC_DIGEST,
        "observer_files": {name: checksum(assets / f"ndu-runs/full-002/{name}-observer.pt") for name in ("reward", "audit")},
        "source_sha256": {p.name: checksum(p) for p in source.glob("*.py")},
        "new_test_predictions_computed": False, "audit_observer_loaded": False,
        "deployed_distribution_matches_training": True, "baseline_additional_training_budget": 0,
        "noise_control_additional_training_budget": 0,
        "equal_information_training_budget_pair": ["direct_risk", "direct_mean"]}
    write_json(directory / "QUALIFICATION_SEAL.json", seal)
    torch.set_num_threads(P["threads"])
    torch.use_deterministic_algorithms(True)
    corpus = qualification_corpus(assets, allocation)
    reward, audit = reference_observer(assets, "reward"), reference_observer(assets, "audit")
    rows = []
    for seed in P["seeds"]:
        base, _ = base_model(prior, seed)
        for arm in P["arms"]:
            if arm == "original":
                actor = None
            elif arm == "noise_control":
                chosen = next(r for r in choices if r["seed"] == seed and r["arm"] == "direct_risk")
                if chosen["kind"] == "original_fallback":
                    actor = None
                else:
                    reference = LatentSnapshot.load(development / chosen["selected_path"], base)
                    torch.manual_seed(seed * 73 + 19)
                    actor = LatentSnapshot(base, LatentActor(4 * base._base._model.hidden, P["dimensions"], P["hidden"]),
                                           reference.basis, chosen["sigma"])
            else:
                chosen = next(r for r in choices if r["seed"] == seed and r["arm"] == arm)
                actor = (LatentSnapshot.load(development / chosen["selected_path"], base)
                         if chosen["kind"] == "stochastic_actor" else None)
            if actor is not None:
                verify_density(actor, Path(chosen["source_run"]), seed)
            before = parameter_hash(base._base._model), parameter_hash(base._gate), parameter_hash(actor.actor) if actor else None
            with (directory / f"ROWS-{seed}-{arm}.jsonl").open("x") as stream:
                rows.extend(evaluate(base, actor, corpus, reward, audit, seed, arm, directory, stream))
            after = parameter_hash(base._base._model), parameter_hash(base._gate), parameter_hash(actor.actor) if actor else None
            if before != after:
                raise RuntimeError("Qualification changed deployed weights")
            print(f"direct qualified {seed} {arm}", flush=True)
    from .statistics import analyze
    result = analyze(rows)
    result.update(seal_sha256=checksum(directory / "QUALIFICATION_SEAL.json"),
                  row_files={p.name: checksum(p) for p in directory.glob("ROWS-*.jsonl")})
    write_json(directory / "RESULT.json", result)
    print(json.dumps(result["comparisons"], sort_keys=True), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("assets", "prior", "development", "allocation", "directory"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    qualify(args.assets, args.prior, args.development, args.allocation, args.directory)
