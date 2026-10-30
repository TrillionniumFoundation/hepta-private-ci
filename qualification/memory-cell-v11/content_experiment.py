"""Frozen fresh-data content matrix with actual internal Transformer adapters."""

import argparse
import gc
import hashlib
import importlib.metadata
import json
from pathlib import Path
import resource
import subprocess
import sys
import time
import traceback

import numpy as np
import torch
from torch.nn import functional as F

import models


HERE = Path(__file__).resolve().parent
SOURCE_FILES = ("content_experiment.py", "models.py", "PROTOCOL_content.json", "content_held_templates.json")
TRAIN = ["Inventory policy record: {key}.", "Read the reserve, pack and limit stored for {key}.",
         "What are the three policy numbers assigned to {key}?"]
CALIBRATION = ["Retrieve the saved inventory settings belonging to {key}.",
               "Which reserve amount, package size and stock cap belong to {key}?"]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write(path, obj):
    Path(path).write_text(json.dumps(obj, sort_keys=True, indent=2, allow_nan=False) + "\n")


def read(path):
    return json.loads(Path(path).read_text())


def frozen(args):
    freeze = read(args.output / "FREEZE.json")
    for name, expected in freeze["sources"].items():
        if sha((HERE / name).read_bytes()) != expected:
            raise ValueError("source drift after freeze: " + name)
    return read(HERE / "PROTOCOL_content.json")


def make_records(protocol):
    rng = np.random.default_rng(protocol["dataset_seed"])
    names = [f"{a} {b} Station" for a in ("Alder", "Birch", "Cedar", "Elm", "Fir", "Hazel", "Larch", "Maple")
             for b in ("Brook", "Cliff", "Glen", "Heath", "Marsh", "Ridge", "Shore", "Vale")]
    names = [names[int(i)] for i in rng.permutation(len(names))]
    values = np.random.default_rng(protocol["dataset_seed"] + 101).integers(0, 16, (protocol["capacity"], 3))
    return [dict(index=i, key=name, value=value.tolist(), source_id=sha(json.dumps([name, value.tolist(), protocol["dataset_seed"]]).encode()))
            for i, (name, value) in enumerate(zip(names[:protocol["capacity"]], values, strict=True))], names[protocol["capacity"]:]


def make_queries(records, unused, phase, templates):
    result = [dict(query_id=f"{phase}:{group}:{row['index']}", text=template.format(key=row["key"]),
                   index=row["index"], value=row["value"], source_id=row["source_id"],
                   wording_group=f"{phase}:{group}", known=True)
              for group, template in enumerate(templates) for row in records]
    offset = {"train": 0, "calibration": 4, "held": 8}[phase]
    if phase != "train":
        for i in range(4):
            result.append(dict(query_id=f"{phase}:unknown:{i}",
                text=templates[i % len(templates)].format(key=unused[offset + i]), index=None, value=None, known=False))
            result.append(dict(query_id=f"{phase}:ambiguous:{i}",
                text=templates[i % len(templates)].format(key=records[i]["key"] + " and " + records[-i-1]["key"]),
                index=None, value=None, known=False))
    return result


def bit_targets(rows):
    return np.asarray([[(v >> bit) & 1 for v in row["value"] for bit in range(4)] for row in rows], np.float32)


def new_adapter(args, protocol, seed=0):
    return models.TransformerAdapter(args.encoder, 12, rank=protocol["rank"], seed=seed,
        max_tokens=protocol["max_tokens"], base_identity=protocol["encoder_manifest_sha256"])


def encode(args, protocol, texts):
    start = time.perf_counter()
    model = new_adapter(args, protocol)
    vectors = []
    with torch.no_grad(), model.disabled_adapters():
        for i in range(0, len(texts), protocol["batch_size"]):
            tokens = model.prepare(texts[i:i + protocol["batch_size"]])
            hidden = model.encoder(**tokens).last_hidden_state
            mask = tokens["attention_mask"].unsqueeze(-1).to(hidden.dtype)
            pooled = (hidden * mask).sum(1) / mask.sum(1).clamp_min(1)
            vectors.append(F.normalize(pooled, dim=-1).numpy())
    return np.concatenate(vectors), dict(encoder_manifest_sha256=model.spec["base_identity"],
        texts=len(texts), wall_seconds_including_model_load=time.perf_counter() - start,
        total_encoder_parameters=sum(p.numel() for p in model.encoder.parameters()) -
                                 sum(p.numel() for p in model.encoder.parameters() if p.requires_grad))


def prepare(args, protocol):
    directory = args.output / "data"
    directory.mkdir()
    records, unused = make_records(protocol)
    write(directory / "records.json", dict(records=records, unused_identifiers=unused))
    for phase, templates in (("train", TRAIN), ("calibration", CALIBRATION)):
        rows = make_queries(records, unused, phase, templates)
        write(directory / f"{phase}.json", rows)
        x, receipt = encode(args, protocol, [r["text"] for r in rows])
        np.savez_compressed(directory / f"{phase}_features.npz", features=x)
        write(directory / f"{phase}_encoder.json", receipt)


def train(args, protocol):
    if args.seed not in protocol["training_seeds"] or args.arm not in protocol["arms"]:
        raise ValueError("fit outside frozen grid")
    rows = read(args.output / "data/train.json")
    with np.load(args.output / "data/train_features.npz", allow_pickle=False) as a:
        x = a["features"]
    schedule = np.random.default_rng(args.seed + 90000).integers(len(rows), size=(protocol["steps"], protocol["batch_size"]), dtype=np.int64)
    directory = args.output / "trained" / f"{args.arm}-{args.seed}"
    directory.mkdir(parents=True)
    np.save(directory / "schedule.npy", schedule, allow_pickle=False)
    if args.arm == "transformer_adapter":
        model = new_adapter(args, protocol, args.seed)
        model.head.load_state_dict(models.FeatureMemory("linear", x.shape[1], 12, seed=args.seed).operator.state_dict())
        data = [r["text"] for r in rows]
    else:
        model = models.FeatureMemory(args.arm, x.shape[1], 12, seed=args.seed,
                                    hidden=protocol["hidden"], slots=protocol["slots"])
        data = x
    receipt = models.fit(model, data, bit_targets(rows), protocol["outputs"], schedule,
        lr=protocol["learning_rate"], source_ids=[r["source_id"] for r in rows], label=f"fresh-content-{args.arm}-{args.seed}")
    receipt.update(held_files_read=False, calibration_files_read=False,
                   initial_head_shared_with_linear=args.arm == "transformer_adapter")
    models.save(model, directory / "checkpoint", metadata={"outputs": protocol["outputs"],
        "source_ids": receipt["source_ids"], "protocol_sha256": sha((HERE / "PROTOCOL_content.json").read_bytes())})
    write(directory / "FIT.json", receipt)


def from_logits(raw):
    result = []
    for logits in raw:
        bits = logits >= 0
        value = [sum(int(bits[i * 4 + j]) << j for j in range(4)) for i in range(3)]
        result.append(dict(value=value, score=float(np.min(np.abs(logits))), logits=logits.tolist()))
    return result


def model_predictions(model, rows, x):
    return from_logits(models.predict(model, [r["text"] for r in rows] if model.input_kind == "text" else x))


def summarize(predictions, rows, threshold):
    detailed = []
    for prediction, row in zip(predictions, rows, strict=True):
        accepted = threshold is not None and prediction["value"] is not None and prediction["score"] >= threshold
        detailed.append(dict(query_id=row["query_id"], known=row["known"], expected=row["value"],
            prediction=prediction, accepted=accepted, exact=row["known"] and prediction["value"] == row["value"]))
    known = [r for r in detailed if r["known"]]
    accepted = [r for r in known if r["accepted"]]
    correct = sum(r["exact"] for r in accepted)
    return dict(known_count=len(known), known_raw_exact=sum(r["exact"] for r in known),
                known_accepted=len(accepted), known_correct_accepted=correct,
                known_coverage=len(accepted) / len(known), accepted_known_precision=correct / len(accepted) if accepted else None,
                correct_known_acceptance=correct / len(known),
                unknown_count=len(detailed) - len(known), unknown_accepted=sum(r["accepted"] and not r["known"] for r in detailed),
                threshold=threshold, rows=detailed)


def calibrate(predictions, rows, candidates):
    admissible = []
    for threshold in candidates:
        score = summarize(predictions, rows, threshold)
        if score["unknown_accepted"] == 0:
            admissible.append((score["known_correct_accepted"], threshold))
    return max(admissible)[1] if admissible else None


def controls(args, phase, x):
    directory = args.output / "data"
    training, rows = read(directory / "train.json"), read(directory / f"{phase}.json")
    records = read(directory / "records.json")["records"]
    with np.load(directory / "train_features.npz", allow_pickle=False) as a:
        train_x = a["features"]
    similarities = x @ train_x.T
    indices = similarities.argmax(axis=1)
    nearest = [dict(value=training[int(j)]["value"], score=float(similarities[i, j]),
                    retrieved_source_id=training[int(j)]["source_id"]) for i, j in enumerate(indices)]
    registry = []
    for row in rows:
        matches = [r for r in records if r["key"].casefold() in row["text"].casefold()]
        registry.append(dict(value=matches[0]["value"] if len(matches) == 1 else None,
                             score=1.0 if len(matches) == 1 else 0.0,
                             matched_keys=[r["key"] for r in matches]))
    coefficients = np.load(args.output / "controls/affine_coefficients.npy", allow_pickle=False)
    affine = from_logits(np.c_[x.astype(np.float64), np.ones(len(x))] @ coefficients)
    return dict(nearest_training_embedding=nearest, explicit_registry=registry, affine_pinv=affine)


def calibration(args, protocol):
    directory = args.output / "calibration"
    directory.mkdir()
    rows = read(args.output / "data/calibration.json")
    with np.load(args.output / "data/calibration_features.npz", allow_pickle=False) as a:
        x = a["features"]
    thresholds = {}
    for seed in protocol["training_seeds"]:
        for arm in protocol["arms"]:
            key = f"{arm}-{seed}"
            model = models.load(args.output / "trained" / key / "checkpoint", encoder_dir=args.encoder)
            predictions = model_predictions(model, rows, x)
            thresholds[key] = calibrate(predictions, rows, protocol["confidence_candidates"])
            write(directory / f"{key}.json", summarize(predictions, rows, thresholds[key]))
            del model
            gc.collect()
    (args.output / "controls").mkdir()
    training = read(args.output / "data/train.json")
    with np.load(args.output / "data/train_features.npz", allow_pickle=False) as a:
        train_x = a["features"].astype(np.float64)
    start = time.perf_counter()
    coefficients = np.linalg.pinv(np.c_[train_x, np.ones(len(train_x))]) @ ((2 * bit_targets(training) - 1) * 8)
    np.save(args.output / "controls/affine_coefficients.npy", coefficients, allow_pickle=False)
    write(args.output / "controls/FIT.json", dict(affine_pinv_seconds=time.perf_counter() - start,
        stored_scalars=int(coefficients.size), training_rows=len(training), held_files_read=False))
    for key, predictions in controls(args, "calibration", x).items():
        candidates = protocol["nearest_confidence_candidates"] if key == "nearest_training_embedding" else protocol["confidence_candidates"]
        thresholds[key] = .5 if key == "explicit_registry" else calibrate(predictions, rows, candidates)
        write(directory / f"{key}.json", summarize(predictions, rows, thresholds[key]))
    write(args.output / "THRESHOLDS.json", thresholds)


def evaluate(args, protocol):
    source = read(args.output / "data/records.json")
    rows = make_queries(source["records"], source["unused_identifiers"], "held", read(HERE / "content_held_templates.json"))
    write(args.output / "data/held.json", rows)
    x, encoding = encode(args, protocol, [r["text"] for r in rows])
    np.savez_compressed(args.output / "data/held_features.npz", features=x)
    write(args.output / "data/held_encoder.json", encoding)
    thresholds = read(args.output / "THRESHOLDS.json")
    training = read(args.output / "data/train.json")
    canonical_rows = training[:protocol["capacity"]]
    with np.load(args.output / "data/train_features.npz", allow_pickle=False) as a:
        canonical_x = a["features"][:protocol["capacity"]]
    report = dict(schema="hepta.memory.v11.fresh-content-result.v1", fitted_before_held_generation=True, arms={}, controls={})
    directory = args.output / "evaluation"
    directory.mkdir()
    for seed in protocol["training_seeds"]:
        for arm in protocol["arms"]:
            key, start = f"{arm}-{seed}", time.perf_counter()
            model = models.load(args.output / "trained" / f"{arm}-{seed}" / "checkpoint", encoder_dir=args.encoder)
            canonical_predictions = model_predictions(model, canonical_rows, canonical_x)
            predictions = model_predictions(model, rows, x)
            result = dict(canonical=summarize(canonical_predictions, canonical_rows, .001),
                          direct_wording=summarize(predictions, rows, thresholds[key]))
            oracle_predictions = [canonical_predictions[r["index"]] for r in rows if r["known"]]
            result["wording_with_oracle_address"] = summarize(oracle_predictions, [r for r in rows if r["known"]], .001)
            if arm == "transformer_adapter":
                with model.disabled_adapters():
                    ablated = model_predictions(model, rows, x)
                    ablated_canonical = model_predictions(model, canonical_rows, canonical_x)
                result["disabled_adapter_direct"] = summarize(ablated, rows, thresholds[key])
                result["disabled_adapter_canonical"] = summarize(ablated_canonical, canonical_rows, .001)
                result["adapter_max_logit_effect"] = max(abs(a-b) for p, q in zip(predictions, ablated, strict=True)
                    for a, b in zip(p["logits"], q["logits"], strict=True))
            result["read_wall_seconds_including_load_and_ablation"] = time.perf_counter() - start
            write(directory / f"{key}.json", result)
            report["arms"][key] = {name: {k: v for k, v in value.items() if k != "rows"} if isinstance(value, dict) else value
                                    for name, value in result.items()}
            print(json.dumps(dict(evaluated=key, canonical=result["canonical"]["known_raw_exact"],
                direct=result["direct_wording"]["known_raw_exact"], accepted=result["direct_wording"]["known_accepted"])), flush=True)
            del model
            gc.collect()
    for key, predictions in controls(args, "held", x).items():
        result = summarize(predictions, rows, thresholds[key])
        write(directory / f"{key}.json", result)
        report["controls"][key] = {k: v for k, v in result.items() if k != "rows"}
    write(args.output / "RESULTS.json", report)


def controller(args, protocol):
    args.output.mkdir(parents=True, exist_ok=False)
    identity = models.verify_base(args.encoder, protocol["encoder_manifest_sha256"])
    write(args.output / "FREEZE.json", dict(schema="hepta.memory.v11.content-local-freeze.v1",
        sources={name: sha((HERE / name).read_bytes()) for name in SOURCE_FILES},
        encoder_manifest_sha256=identity, protocol=protocol, remote_publication_verified=False,
        dependencies={name: importlib.metadata.version(name) for name in ("numpy", "torch", "transformers", "tokenizers")}))
    plan = [("prepare", None, None)] + [("train", arm, seed) for seed in protocol["training_seeds"] for arm in protocol["arms"]]
    plan += [("calibration", None, None), ("evaluate", None, None)]
    processes = []
    for stage, arm, seed in plan:
        name = stage + (f"-{arm}-{seed}" if arm else "")
        command = [sys.executable, str(Path(__file__).resolve()), stage, "--encoder", str(args.encoder), "--output", str(args.output)]
        if arm:
            command += ["--arm", arm, "--seed", str(seed)]
        print(json.dumps(dict(starting=name)), flush=True)
        start = time.perf_counter()
        with (args.output / f"{name}.stdout").open("x") as out, (args.output / f"{name}.stderr").open("x") as err:
            result = subprocess.run(command, stdout=out, stderr=err)
        processes.append(dict(stage=name, command=command, returncode=result.returncode,
                              wall_seconds=time.perf_counter() - start))
        write(args.output / "PROCESSES.json", processes)
        if result.returncode:
            raise RuntimeError("worker failed; partial evidence preserved: " + name)
    inventory = [dict(path=str(p.relative_to(args.output)), bytes=p.stat().st_size, sha256=sha(p.read_bytes()))
                 for p in args.output.rglob("*") if p.is_file()]
    write(args.output / "ARTIFACTS.json", dict(files=inventory, retained_file_bytes=sum(r["bytes"] for r in inventory),
        inventory_scope="files at controller completion; excludes ARTIFACTS.json itself and the final run.RESOURCE.json",
        shared_encoder_bytes=sum(r["bytes"] for r in read(args.encoder / "MODEL_IDENTITY.json")["files"])))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["run", "prepare", "train", "calibration", "evaluate"])
    parser.add_argument("--encoder", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--arm")
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()
    protocol = read(HERE / "PROTOCOL_content.json") if args.stage == "run" else frozen(args)
    torch.set_num_threads(protocol["threads"])
    start, cpu, failure = time.perf_counter(), time.process_time(), None
    try:
        {"run": controller, "prepare": prepare, "train": train, "calibration": calibration, "evaluate": evaluate}[args.stage](args, protocol)
    except Exception:
        failure = traceback.format_exc()
        raise
    finally:
        if args.output.exists():
            name = args.stage + (f"-{args.arm}-{args.seed}" if args.arm else "")
            usage = resource.getrusage(resource.RUSAGE_SELF)
            write(args.output / f"{name}.RESOURCE.json", dict(stage=name, failed=failure is not None, error=failure,
                wall_seconds=time.perf_counter() - start, self_cpu_seconds=time.process_time() - cpu,
                self_max_rss_kib=usage.ru_maxrss, scope="this process only; child stages have separate receipts"))


if __name__ == "__main__":
    main()
