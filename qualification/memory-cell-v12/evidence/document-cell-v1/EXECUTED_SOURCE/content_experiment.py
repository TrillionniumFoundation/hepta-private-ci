"""Actual learned field-content memory with matched exposure and complete ledgers.

Inference receives only parameters, a shared label codebook and public addresses.
The exact registry and original-document parser are explicitly source-reading
controls. Authored paraphrases and an explicit scope resolver bound the claim.
"""

import argparse
from collections import Counter
import hashlib
import json
import lzma
import math
from pathlib import Path
import re
import shutil
import sys
import time
import zlib

import numpy as np

from corpus import build_corpus
from learned import MLP, canonical, features, predict_export, train_mlp


FIELDS = ("owner", "deputy", "lifecycle")
WIDTHS = (5, 4, 1)
TEMPLATES = {
    "train": ("State the owner, deputy, and lifecycle of {module}.",
              "Which owner and deputy are assigned to {module}, and what is its lifecycle?",
              "For {module}, report its owner team, deputy team, and lifecycle."),
    "calibration": ("Identify the responsible owner, backup deputy, and lifecycle for {module}.",
                    "Give {module}'s owner, its deputy, and the declared lifecycle."),
    "test": ("For {module}, name the responsible team, its alternate, and its implementation status.",
             "I need the accountable team, backup team, and lifecycle of {module}."),
}


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value) + b"\n")
    return path.stat().st_size


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def normalize(text):
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def resolve(text, modules):
    """Public address/operation parser; no target values or source records."""
    words = " " + normalize(text) + " "
    found = [m for m in modules if " " + normalize(m) + " " in words]
    fields = (("owner", "responsible", "accountable"), ("deputy", "alternate", "backup"),
              ("lifecycle", "implementation status"))
    supported = all(any(" " + term + " " in words for term in terms) for terms in fields)
    if len(found) != 1 or not supported:
        return None
    return found[0]


def encode(values, codebook):
    return [float((codebook[field].index(values[field]) >> bit) & 1)
            for field, width in zip(FIELDS, WIDTHS) for bit in range(width)]


def decode(logits, codebook):
    result, offset = {}, 0
    for field, width in zip(FIELDS, WIDTHS):
        index = sum(int(logits[offset + bit] >= 0) << bit for bit in range(width))
        if index >= len(codebook[field]):
            return None
        result[field] = codebook[field][index]
        offset += width
    return result


def queries(metadata, all_metadata):
    result = []
    modules = {m["module"] for m in metadata}
    for item in metadata:
        for split, templates in TEMPLATES.items():
            for index, template in enumerate(templates):
                name = item["module"].replace(".", " ") if index % 2 else item["module"]
                result.append(dict(text=template.format(module=name), split=split,
                                   module=item["module"], target=dict(item["fields"]), kind="supported"))
        for split, question in (("calibration", "the maintainer's telephone and birthday"),
                                ("test", "the private street address for its owner")):
            result.append(dict(text=f"For {item['module']}, provide {question}.", split=split,
                               module=item["module"], target=None, kind="unsupported_fields"))
    absent = [m["module"] for m in all_metadata if m["module"] not in modules][:3]
    for split, unknown in (("calibration", "cosmic.network"), ("test", "stellar.scheduler")):
        for name in [unknown, *absent]:
            result.append(dict(text=f"State the owner, deputy, and lifecycle of {name}.", split=split,
                               module=name, target=None, kind="absent_module"))
    for number, row in enumerate(result):
        row["id"] = hashlib.sha256(canonical([number, row["text"], row["split"]])).hexdigest()
    return result


def predict(models, X, texts, modules, codebook):
    """No metadata, target map, record IDs or source text enters this function."""
    logits = np.empty((len(texts), sum(WIDTHS)), dtype=np.float64)
    addresses = [resolve(text, modules) for text in texts]
    if len(models) == 1:
        logits[:] = models[0].predict(X)
    else:
        assignment = {name: i % len(models) for i, name in enumerate(modules)}
        for cell, model in enumerate(models):
            positions = [i for i, m in enumerate(addresses) if assignment.get(m, 0) == cell]
            if positions:
                logits[positions] = model.predict(X[positions])
    confidence = (1 / (1 + np.exp(-np.clip(np.abs(logits), 0, 60)))).min(axis=1)
    return [dict(module=module, fields=decode(row, codebook), confidence=float(conf), logits=row.tolist())
            for module, row, conf in zip(addresses, logits, confidence)]


def select_threshold(rows, predictions, thresholds):
    choices = []
    for threshold in thresholds:
        correct = wrong = 0
        for row, pred in zip(rows, predictions):
            if row["split"] != "calibration":
                continue
            accepted = pred["module"] is not None and pred["fields"] is not None and pred["confidence"] >= threshold
            correct += int(accepted and row["target"] == pred["fields"])
            wrong += int(accepted and row["target"] != pred["fields"])
        if wrong == 0:
            choices.append((correct, -threshold, threshold))
    if not choices:
        raise AssertionError("preregistered reject-all threshold is missing")
    return max(choices)[2]


def score(rows, predictions, threshold):
    metrics, evidence = {}, []
    for row, pred in zip(rows, predictions):
        positive = row["target"] is not None
        exact = positive and pred["fields"] == row["target"]
        accepted = pred["module"] is not None and pred["fields"] is not None and pred["confidence"] >= threshold
        evidence.append(dict(query=row, prediction=pred, threshold=threshold, raw_exact=exact,
                             accepted=accepted, accepted_correct=accepted and exact,
                             wrong_accept=accepted and not exact))
    for split in TEMPLATES:
        part = [x for x in evidence if x["query"]["split"] == split]
        positives = [x for x in part if x["query"]["target"] is not None]
        negatives = [x for x in part if x["query"]["target"] is None]
        metrics[split] = dict(positive_queries=len(positives), unknown_queries=len(negatives),
                             raw_exact=sum(x["raw_exact"] for x in positives),
                             accepted_correct=sum(x["accepted_correct"] for x in positives),
                             wrong_accept=sum(x["wrong_accept"] for x in part),
                             unknown_wrong_accept=sum(x["accepted"] for x in negatives),
                             unknown_rejected=sum(not x["accepted"] for x in negatives),
                             accepted=sum(x["accepted"] for x in part),
                             rejected=sum(not x["accepted"] for x in part))
    return metrics, evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("evidence") / "content")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    package = Path(__file__).parent
    protocol = json.loads((package / "CONTENT_PROTOCOL.json").read_text())
    sources = ["content_experiment.py", "content_tests.py", "CONTENT_PROTOCOL.json", "learned.py", "corpus.py"]
    source_hashes = {name: sha(package / name) for name in sources}
    for name in sources:
        (out / "EXECUTED_SOURCE").mkdir(exist_ok=True)
        shutil.copyfile(package / name, out / "EXECUTED_SOURCE" / name)
    corpus_cpu = time.process_time()
    corpus = build_corpus(args.repo)
    corpus_cpu = time.process_time() - corpus_cpu
    metadata = sorted(corpus["metadata"], key=lambda m: m["module"])
    if len(metadata) != 40 or corpus["source_commit"] != protocol["source_commit"]:
        raise ValueError("frozen 40-document source corpus required")
    codebook = {field: sorted({m["fields"][field] for m in metadata}) for field in FIELDS}
    if any(len(codebook[f]) > 2**w for f, w in zip(FIELDS, WIDTHS)):
        raise ValueError("frozen content encoding cannot represent the source vocabulary")
    codebook_bytes = save(out / "codebook.json", codebook)
    source_bytes = {}
    for item in metadata:
        target = out / "sources" / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.repo / item["path"], target)
        source_bytes[item["module"]] = target.stat().st_size
    save(out / "PLAN.json", dict(protocol=protocol, source_hashes=source_hashes,
                                 corpus_sha256=corpus["corpus_sha256"], provenance=corpus["provenance"],
                                 templates=TEMPLATES, vocabulary_cardinality={k: len(v) for k, v in codebook.items()},
                                 corpus_build_cpu_seconds=corpus_cpu, frozen_before_training=True))
    all_results, counters = [], Counter()
    for size in protocol["execution_sizes"]:
        selected = metadata[:size]
        modules = [m["module"] for m in selected]
        rows = queries(selected, metadata)
        folder = out / f"n{size:03d}"
        address_bytes = save(folder / "addresses.json", modules)
        provenance_bytes = save(folder / "provenance.json", [{k: v for k, v in m.items() if k != "fields"} for m in selected])
        dataset_bytes = save(folder / "queries-with-scorer-targets.json", rows)
        registry = {m["module"]: m["fields"] for m in selected}
        registry_raw = canonical(registry)
        baseline_cost = {}
        for kind, compressor, decompressor in (("zlib", lambda x: zlib.compress(x, 9), zlib.decompress),
                                                ("lzma", lambda x: lzma.compress(x, preset=6), lzma.decompress)):
            cpu = time.process_time()
            packed = compressor(registry_raw)
            compress_cpu = time.process_time() - cpu
            (folder / ("registry." + kind)).write_bytes(packed)
            cpu = time.process_time()
            restored = json.loads(decompressor(packed))
            predictions = [dict(module=resolve(r["text"], modules),
                                 fields=restored.get(resolve(r["text"], modules)), confidence=1.0) for r in rows]
            inference_cpu = time.process_time() - cpu
            metrics, evidence = score(rows, predictions, 0)
            evidence_bytes = save(folder / (kind + "-predictions.json"), evidence)
            baseline_cost[kind] = dict(serialized_registry_bytes=len(packed), uncompressed_registry_bytes=len(registry_raw),
                                       decompressed_json_bytes=len(canonical(restored)), compression_cpu_seconds=compress_cpu,
                                       cold_decode_and_inference_cpu_seconds=inference_cpu, prediction_evidence_bytes=evidence_bytes)
            all_results.append(dict(size=size, arm="exact_registry_" + kind, seed=None, metrics=metrics,
                                    costs=baseline_cost[kind], exact_supported_service=True))
        cpu = time.process_time()
        original = {m["module"]: (args.repo / m["path"]).read_text() for m in selected}
        parsed_predictions = []
        for row in rows:
            module = resolve(row["text"], modules)
            fields = ({f: re.search(r"\*\*" + f.title() + r":\*\*\s*`([^`]+)`", original[module]).group(1)
                       for f in FIELDS} if module else None)
            parsed_predictions.append(dict(module=module, fields=fields, confidence=1.0))
        parse_cpu = time.process_time() - cpu
        metrics, evidence = score(rows, parsed_predictions, 0)
        save(folder / "source-parse-predictions.json", evidence)
        all_results.append(dict(size=size, arm="source_structured_parse", seed=None, metrics=metrics,
                                costs=dict(source_bytes=sum(source_bytes[m] for m in modules), cold_read_parse_cpu_seconds=parse_cpu),
                                exact_supported_service=True))
        cpu = time.process_time()
        X = features([r["text"] for r in rows], protocol["dimension"])
        feature_cpu = time.process_time() - cpu
        train_positions = [i for i, row in enumerate(rows) if row["split"] == "train"]
        Y = np.asarray([encode(rows[i]["target"], codebook) for i in train_positions], dtype=np.float32)
        for seed in protocol["seeds"]:
            for arm in ("single", "sharded"):
                arm_folder = folder / (str(seed) + "-" + arm)
                spec = protocol[arm]
                count = spec.get("cells", 1)
                models, checkpoint_bytes, training_state_bytes = [], 0, 0
                wall, cpu = time.perf_counter(), time.process_time()
                for cell in range(count):
                    positions = [j for j, i in enumerate(train_positions) if count == 1 or modules.index(rows[i]["module"]) % count == cell]
                    indices = [train_positions[j] for j in positions]
                    model = train_mlp(X[indices], Y[positions], hidden=spec.get("hidden", spec.get("hidden_each")),
                                      steps=spec.get("steps", spec.get("steps_each")), seed=seed + cell * 100003,
                                      batch_size=spec["batch_size"], learning_rate=protocol["learning_rate"])
                    models.append(model)
                    checkpoint_bytes += save(arm_folder / f"cell-{cell}.json", model.export())
                    training_state_bytes += save(arm_folder / f"cell-{cell}-training-state.json", model.export(include_optimizer=True))
                train_cpu, train_wall = time.process_time() - cpu, time.perf_counter() - wall
                fixed = protocol["fixed_migration_selection"]
                if (size, seed, arm) == (fixed["size"], fixed["seed"], fixed["arm"]):
                    exported = models[0].export()
                    probe_positions = [i for i, r in enumerate(rows) if r["split"] == "test"][:8]
                    inputs = X[probe_positions].astype(np.float64)
                    expected = predict_export(exported, inputs)
                    train_predictions = models[0].predict(inputs)
                    if not np.allclose(expected, train_predictions, atol=1e-5, rtol=1e-5):
                        raise AssertionError("independent serving export differs from actual model")
                    save(out / "model.json", exported)
                    save(out / "probes.json", dict(schema="hepta.memory.v12.probes.v1", inputs=inputs.tolist(),
                         expected_logits=expected.tolist(), tolerance=dict(atol=1e-5, rtol=1e-5),
                         model_parameter_sha256=exported["parameter_sha256"]))
                    save(out / "FIXED_SELECTION.json", dict(selection=fixed, source_hashes=source_hashes,
                         corpus_sha256=corpus["corpus_sha256"], model_sha256=sha(out / "model.json"),
                         probes_sha256=sha(out / "probes.json"), selected_before_held_scoring=True,
                         train_vs_export_max_abs_error=float(np.max(np.abs(expected - train_predictions)))))
                    print("MIGRATION_CHECKPOINT_READY " + str(out / "model.json"), flush=True)
                cpu = time.process_time()
                predictions = predict(models, X, [r["text"] for r in rows], modules, codebook)
                inference_cpu = time.process_time() - cpu
                threshold = select_threshold(rows, predictions, protocol["thresholds"])
                metrics, evidence = score(rows, predictions, threshold)
                evidence_bytes = save(arm_folder / "predictions.json", evidence)
                selector_bytes = save(arm_folder / "selection.json", dict(threshold=threshold, modules=modules,
                                      router="ordinal_modulo_cells" if count > 1 else "single", cells=count))
                receipts = [m.receipt for m in models]
                presentations = sum(r["sample_presentations"] for r in receipts)
                if presentations != protocol["training_presentations_each_arm"]:
                    raise AssertionError("training exposure budget mismatch")
                costs = dict(serving_model_json_bytes=checkpoint_bytes, raw_parameter_bytes=sum(r["parameter_bytes"] for r in receipts),
                             codebook_bytes=codebook_bytes, address_index_bytes=address_bytes, selector_bytes=selector_bytes,
                             provenance_bytes=provenance_bytes, source_bytes=sum(source_bytes[m] for m in modules),
                             dataset_evidence_bytes=dataset_bytes, prediction_evidence_bytes=evidence_bytes,
                             retained_training_state_json_bytes=training_state_bytes,
                             raw_optimizer_bytes=sum(r["optimizer_bytes"] for r in receipts),
                             trainable_parameters=sum(r["trainable_parameters"] for r in receipts),
                             sample_presentations=presentations, train_cpu_seconds=train_cpu, train_wall_seconds=train_wall,
                             feature_encode_cpu_seconds=feature_cpu, inference_cpu_seconds=inference_cpu,
                             feature_matrix_bytes=int(X.nbytes), target_matrix_bytes=int(Y.nbytes))
                costs["declared_serving_state_bytes"] = checkpoint_bytes + codebook_bytes + address_bytes + selector_bytes
                costs["declared_maintainable_state_bytes"] = costs["declared_serving_state_bytes"] + costs["source_bytes"] + provenance_bytes
                all_results.append(dict(size=size, seed=seed, arm=arm, metrics=metrics, threshold=threshold,
                                        costs=costs, training_receipts=receipts, learned_output="field-value bits, not record IDs"))
                save(out / "RESULTS.partial.json", all_results)
                print(json.dumps(dict(size=size, seed=seed, arm=arm, test=metrics["test"], train_cpu_seconds=train_cpu)), flush=True)
    if source_hashes != {name: sha(package / name) for name in sources}:
        raise RuntimeError("executed source changed during experiment")
    final_corpus = build_corpus(args.repo)
    if final_corpus["corpus_sha256"] != corpus["corpus_sha256"]:
        raise RuntimeError("source corpus changed during experiment")
    runtime = dict(python_version=sys.version, numpy_version=np.__version__,
                   python_executable_bytes=Path(sys.executable).resolve().stat().st_size,
                   numpy_package_bytes=sum(p.stat().st_size for p in Path(np.__file__).parent.rglob("*") if p.is_file()),
                   shared_runtime_not_in_per_checkpoint_bytes=True,
                   complete_process_rss_not_isolated_by_arm=True,
                   experiment_source_bytes=sum((package / n).stat().st_size for n in sources))
    save(out / "RESULTS.json", dict(protocol_sha256=source_hashes["CONTENT_PROTOCOL.json"], source_hashes=source_hashes,
          corpus_sha256=corpus["corpus_sha256"], rows=all_results, runtime=runtime,
          total_wall_seconds=time.perf_counter() - start_wall, total_cpu_seconds=time.process_time() - start_cpu,
          limitations=protocol["limitations"], source_stable=True, production_activation_allowed=False,
          unknown_rejection_is_explicit_resolver=True))
    inventory = {p.relative_to(out).as_posix(): dict(bytes=p.stat().st_size, sha256=sha(p))
                 for p in out.rglob("*") if p.is_file()}
    save(out / "INVENTORY.json", dict(files=inventory, bytes=sum(v["bytes"] for v in inventory.values()),
                                      self_excluded=True))
    print("CONTENT_EXPERIMENT_COMPLETE " + str(out / "RESULTS.json"), flush=True)


if __name__ == "__main__":
    main()
