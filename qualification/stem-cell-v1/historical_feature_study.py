"""Train new Cell candidates on a pinned, previously executed Encoder artifact.

This is a separate four-intent cached-feature experiment, NOT new pretrained
inference or the eight-intent BGE job. No network, model loader or owner is added.
Only raw vectors are reused; the old train-fitted normalization is not reused.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import io
import json
from pathlib import Path
import platform
import subprocess
import time
import zipfile

import torch

from development_study_data import StudyConfig, audit_rows, canonical, write_once
from public_structural_data import DATA_BYTES, DATA_GIT_BLOB, DATA_REVISION, text_key
from study import reject_duplicate_evidence_fields, reject_nonstandard_evidence_number, parse_finite_evidence_float

ARTIFACT_ID = 11757461425
ARTIFACT_SHA256 = "2d4cced3f2f40c9d1759b68e0b6b6886454a71a4c6c98a1d70fafc02c4237505"
ARTIFACT_BYTES = 1_797_397
SOURCE_SHA = "66258d5871cd022c0fa13995dd6ba787b4d2359e"
FEATURE_SHA256 = "19214e07bcc84d94694fc98e7920d8b404366efdbed0dc5a6b3e5b07cf8a7063"
MODEL = "jhu-clsp/mmBERT-small"
REVISION = "abc32620dd4f6ab06f5fbe905dc25f310618e09f"
INTENTS = ("alarm", "calendar", "weather", "time")
RUN_SCHEMA = "hepta.stem.cached-feature-run.v1"


def _json(raw):
    return json.loads(raw, object_pairs_hook=reject_duplicate_evidence_fields,
                      parse_constant=reject_nonstandard_evidence_number,
                      parse_float=parse_finite_evidence_float)


def _tensor_digest(value):
    value = value.detach().cpu().contiguous()
    h = hashlib.sha256(str((str(value.dtype), tuple(value.shape))).encode("ascii"))
    h.update(value.reshape(-1).view(torch.uint8).numpy().tobytes())
    return h.hexdigest()


def validate_raw_vectors(payload, events, ids):
    """Independently reproduce source event hashes and old normalization.

    This proves correspondence inside the archived record, not host attestation.
    It never calls the original Encoder or executes the archived Python source.
    """
    names = {"ids", "vectors", "raw_vectors", "normalizer_mean", "normalizer_scale"}
    if type(payload) is not dict or set(payload) != names or payload["ids"] != ids:
        raise ValueError("historical feature identities differ from publisher inventory")
    for name in names - {"ids"}:
        value = payload[name]
        shape = (328, 384) if name in {"vectors", "raw_vectors"} else (384,)
        if (type(value) is not torch.Tensor or value.device.type != "cpu"
                or value.dtype != torch.float32 or tuple(value.shape) != shape
                or not torch.isfinite(value).all()):
            raise ValueError("invalid bounded archived feature tensor")
    raw = payload["raw_vectors"]
    expected_training_ids = ids[:128]
    if events.get("normalizer_training_inputs") != expected_training_ids:
        raise ValueError("historical normalizer training population changed")
    mean, scale = raw[:128].mean(0), raw[:128].std(0).clamp_min(.1)
    if (not torch.allclose(mean, payload["normalizer_mean"], atol=1e-6, rtol=1e-6)
            or not torch.allclose(scale, payload["normalizer_scale"], atol=1e-6, rtol=1e-6)
            or not torch.allclose(((raw - mean) / scale).clamp(-8, 8), payload["vectors"], atol=1e-6, rtol=1e-6)):
        raise ValueError("archived normalized features do not derive from raw training vectors")
    recorded = events.get("events")
    if type(recorded) is not list or len(recorded) != 11:
        raise ValueError("historical physical batch census changed")
    offset = 0
    for event in recorded:
        count = len(event["ids"])
        if (not 1 <= count <= 32 or event["ids"] != ids[offset:offset+count]
                or event["vectors_sha256"] != _tensor_digest(raw[offset:offset+count])):
            raise ValueError("raw vectors differ from original physical forward event")
        offset += count
    if offset != len(ids):
        raise ValueError("incomplete physical forward row coverage")
    return raw.clone()


def load_reference(archive):
    """Accept only the exact downloaded Actions ZIP, then restrict tensor loading."""
    archive = Path(archive)
    if archive.is_symlink() or not archive.is_file() or archive.stat().st_size != ARTIFACT_BYTES:
        raise ValueError("invalid pinned historical archive")
    with archive.open("rb") as handle:
        raw = handle.read(ARTIFACT_BYTES + 1)
    if len(raw) != ARTIFACT_BYTES or hashlib.sha256(raw).hexdigest() != ARTIFACT_SHA256:
        raise ValueError("historical Actions archive SHA256 mismatch")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names = z.namelist()
        if len(names) != len(set(names)):
            raise ValueError("duplicate historical ZIP members")
        def member(name, limit):
            info = z.getinfo(name)
            if not 0 < info.file_size <= limit:
                raise ValueError("oversized historical ZIP member")
            with z.open(info) as handle:
                data = handle.read(limit + 1)
            if len(data) != info.file_size:
                raise ValueError("invalid historical ZIP member length")
            return data
        source = member("real-source.txt", 100).decode().strip()
        publisher = member("real-study/publisher/data/data_full.json", DATA_BYTES)
        license_bytes = member("real-study/publisher/LICENSE", 19_467)
        load = _json(member("real-study/load.json", 100_000))
        summary = _json(member("real-study/physical-summary.json", 10_000))
        events = _json(member("real-study/forward-events.json", 100_000))
        feature_bytes = member("real-study/frozen-features.pt", 2_000_000)
    if (source != SOURCE_SHA or len(publisher) != DATA_BYTES
            or hashlib.sha1(f"blob {len(publisher)}\0".encode() + publisher).hexdigest() != DATA_GIT_BLOB
            or any(r.get("source_sha") != SOURCE_SHA or r.get("model") != MODEL
                   or r.get("revision") != REVISION for r in (load, summary))
            or load.get("publisher_revision") != DATA_REVISION
            or load.get("model_is_frozen") is not True or summary.get("real_weights_executed") is not True
            or summary.get("encoder_rows") != 328 or summary.get("encoder_forwards") != 11
            or hashlib.sha256(feature_bytes).hexdigest() != FEATURE_SHA256
            or summary.get("feature_artifact_sha256") != FEATURE_SHA256):
        raise ValueError("historical model/data/source lineage mismatch")
    if hashlib.sha1(f"blob {len(license_bytes)}\0".encode() + license_bytes).hexdigest() != "1a16e05564d2aaa880bbe9e506a0a0226d8742cc":
        raise ValueError("historical publisher license bytes changed")
    data = _json(publisher)
    inventory = load["input_inventory"]
    expected, ids = {}, []
    for fold, partition, first, end in (("train", "train", 0, 32), ("validation", "val", 0, 10),
                                      ("calibration", "val", 10, 20), ("test", "test", 0, 30)):
        entries = []
        for label in INTENTS:
            selected = [(i, text) for i, (text, y) in enumerate(data[partition]) if y == label][first:end]
            for i, text in selected:
                # Original producer's digest uses UTF-8 JSON with no final newline.
                text_hash = hashlib.sha256(json.dumps(text, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
                entries.append({"id": f"{partition}:{i}", "text": text, "intent": INTENTS.index(label),
                                "source_sha256": text_hash})
        expected[fold] = entries
        ids.extend(r["id"] for r in entries)
    if inventory != expected or len(ids) != 328 or len(set(ids)) != 328:
        raise ValueError("historical input census differs from pinned publisher rows")
    # This is a fixed feature artifact, not a model checkpoint. Never use unsafe
    # pickle loading or add globals. Normal inference remains safetensors-only.
    payload = torch.load(io.BytesIO(feature_bytes), map_location="cpu", weights_only=True)
    features = validate_raw_vectors(payload, events, ids)
    reference = {"artifact_id": ARTIFACT_ID, "archive_sha256": ARTIFACT_SHA256,
        "feature_sha256": FEATURE_SHA256, "source_sha": SOURCE_SHA, "model": MODEL,
        "revision": REVISION, "publisher_git_blob": DATA_GIT_BLOB,
        "feature_input": "original utterance text only; no joint question/options encoding",
        "historical_encoder_forward_calls": 11, "historical_encoded_rows": 328,
        "historical_load_warmup_encoder_cpu_ns": summary["common_load_warmup_encoder_cpu_ns"],
        "historical_cost_is_not_current_run_cost": True, "current_encoder_forward_calls": 0,
        "independent_execution_attestation": False}
    return expected, ids, features, reference, {"publisher": publisher, "license": license_bytes}


def derive_study(inventory, ids, raw_features):
    """16/8/8 of each archived training intent; all 80 val and 120 test retained."""
    assignment = {}
    for label in range(4):
        source = sorted((r for r in inventory["train"] if r["intent"] == label), key=lambda r: text_key(r["text"]))
        for index, row in enumerate(source):
            assignment[row["id"]] = "base" if index < 16 else "adapt" if index < 24 else "extra"
    rows = []
    for fold, entries in inventory.items():
        for entry in entries:
            assigned = assignment[entry["id"]] if fold == "train" else "held_out" if fold == "test" else "calibration"
            rows.append({"sample_id": entry["id"], "source_group": "content:" + text_key(entry["text"]),
                "episode_id": entry["id"], "scope": "public-historical-mmbert-four-intent",
                "language": "en", "split": "train" if fold == "train" else assigned,
                "training_phase": assigned if fold == "train" else None, "observed_at": None,
                "state": entry["text"], "question": "Classify this utterance among the fixed four intentions.",
                "options": list(INTENTS), "label": entry["intent"]})
    config = StudyConfig(classes=4, time_basis="publisher_partition", max_tokens=256, seal_replay=True)
    rows = audit_rows(rows, config)
    positions = {uid: i for i, uid in enumerate(ids)}
    return rows, raw_features[[positions[r["sample_id"]] for r in rows]].clone(), config


def execute(archive, output, source_identity):
    """Compose the existing fitter; caller declares complete vs partial source."""
    from development_study import fit_and_seal, prepare_views

    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    start_cpu, start_wall = time.process_time_ns(), time.perf_counter_ns()
    write_once(output / "plan.json", {"schema": RUN_SCHEMA, "source_identity": source_identity,
        "archive_sha256": ARTIFACT_SHA256, "training_split_per_intent": [16, 8, 8],
        "base_steps": 200, "adaptation_steps": 200, "seed": 7347, "rank": 8,
        "model_inference_this_run": False, "production_authorized": False})
    try:
        inventory, ids, features, reference, original = load_reference(archive)
        # Exercise the eight-intent corpus fix on authentic bytes, separately
        # from this four-intent cached-feature learning population.
        from public_structural_data import GROUPED_PARTITIONS, prepare_dataset
        preflight = output / "public-data-preflight"
        preflight.mkdir()
        (preflight / "publisher.json").write_bytes(original["publisher"])
        (preflight / "CLINC_LICENSE.txt").write_bytes(original["license"])
        try:
            prepare_dataset(preflight / "publisher.json", preflight)
        except ValueError as error:
            write_once(preflight / "strict-refusal.json", {"error_type": type(error).__name__, "message": str(error)})
        else:
            raise ValueError("strict corpus guard no longer rejects the known cross-phase conflict")
        prepare_dataset(preflight / "publisher.json", preflight, partition_policy=GROUPED_PARTITIONS)
        rows, features, config = derive_study(inventory, ids, features)
        reference_sha = write_once(output / "reference.json", reference)
        with (output / "dataset.jsonl").open("xb") as handle:
            for row in rows:
                handle.write(canonical(row))
        dataset_sha = hashlib.sha256((output / "dataset.jsonl").read_bytes()).hexdigest()
        write_once(output / "config.jsonl", asdict(config))
        inputs, labels = prepare_views(rows)
        sealed = fit_and_seal(inputs, labels, features, config, output)
        report = {"schema": RUN_SCHEMA, "source_sha": source_identity["source_sha"],
            "source_identity": source_identity, "dataset_sha256": dataset_sha, "sealed": sealed,
            "reference_sha256": reference_sha, "feature_origin": reference,
            "real_weights_executed": False, "historical_pretrained_features_reused": True,
            "encoder_forward_calls_this_run": 0, "time_basis": config.time_basis,
            "cpu_ns": time.process_time_ns() - start_cpu, "wall_ns": time.perf_counter_ns() - start_wall,
            "python": platform.python_version(), "torch": torch.__version__, "production_authorized": False}
        write_once(output / "run.json", report)
        return report
    except Exception as error:
        write_once(output / "FAILED.json", {"error_type": type(error).__name__, "message": str(error),
                   "production_authorized": False})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--expected-source-sha", required=True)
    args = parser.parse_args()
    root = args.source_root.resolve()
    source = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    import model_runner, study
    directory = root / "qualification/stem-cell-v1"
    if (source != args.expected_source_sha or len(source) != 40
            or any(c not in "0123456789abcdef" for c in source)
            or any(Path(m.__file__).resolve().parent != directory for m in (model_runner, study))
            or Path(__file__).resolve().parent != directory or args.output.resolve().is_relative_to(root)
            or subprocess.check_output(["git", "-C", str(root), "status", "--porcelain", "--", str(directory)], text=True)):
        raise ValueError("requires clean exact source and complete repository imports")
    torch.set_num_threads(2)
    torch.use_deterministic_algorithms(True)
    execute(args.archive, args.output, {"source_sha": source, "complete_repository_imports_verified": True})


if __name__ == "__main__":
    main()
