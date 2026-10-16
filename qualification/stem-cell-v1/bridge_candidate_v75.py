"""Sealed source-bound original-train Bridge feature and Torch-logit handoff.

This is a research-only optional numerical evidence layer for a *completed*
V7.4 cohort. It never labels an input, trains a model, selects a Cell, or
authenticates an Encoder/issuer. The independent checker lives in a separate
stdlib + NumPy process and uses different code for the forward pass.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import io
import json
import math
import os
import stat
import time
import zipfile

import numpy as np

from bridge_gradient_archive_replay import require, read_regular_file
from bridge_numpy_receipt import FEATURE_SCHEMA, OBSERVED_SCHEMA, NAMES, _read_tensor_archive
from bridge_portable_v74 import source_id

SCHEMA = "hepta.bridge.candidate-prelabel-v75.shadow.v1"
PREDICTION_SCHEMA = "hepta.bridge.candidate-logit-seal-v75.v1"
SEEDS = (41, 47, 53)
ARMS = ("joint", "protect_old", "protect_old_guarded")
HEX = frozenset("0123456789abcdef")
MAX_BATCH = 16
MAX_CASES = 128
BATCHES = 8


def _digest(v):
    return sha256(v).hexdigest()


def _hex(x):
    require(type(x) is str and len(x) == 64 and all(y in HEX for y in x),
            "exact lowercase SHA256 field required")
    return x


def _json(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _load(blob):
    def pairs(items):
        out = {}
        for key, v in items:
            require(key not in out, "duplicate original receipt JSON keys")
            out[key] = v
        return out
    return json.loads(blob, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def _write(path, payload):
    path = Path(path)
    require(not path.is_symlink() and not path.exists(), "create-only candidate feature/observation")
    with path.open("xb") as out:
        out.write(payload)
        out.flush()
        os.fsync(out.fileno())
    return _digest(payload)


def _mkdir(path):
    path = Path(path)
    require(not path.exists() and not path.is_symlink(), "new scope-owned immutable directory required")
    path.mkdir(parents=True, exist_ok=False)


def _case_rows(rows):
    require(type(rows) in (list, tuple) and len(rows) == MAX_CASES,
            "complete original 128 binding TRAIN rows required")
    ids = [source_id(r) for r in rows]
    require(len(set(ids)) == MAX_CASES and all(r["source_split"] == "train"
             and type(r["label"]) is int and r["label"] in (0, 1)
             and r["segmentation"] == "synthetic-ownership-storage-v1"
             and type(r["source_hash"]) is str and len(r["source_hash"]) == 64
             for r in rows), "full original binding TRAIN case/label/domain identity required")
    return ids


def _extract_six(batch, n):
    """Convert only public model inputs, never any labels/evidence targets."""
    if hasattr(batch, "features"):
        values = batch.features()
    else:
        values = batch
    require(type(values) in (tuple, list) and len(values) == 6,
            "exact public six-tensor input required")
    items = {}
    for name, value in zip(NAMES, values, strict=True):
        if isinstance(value, np.ndarray):
            v = np.array(value, copy=True, order="C")
        else:
            import torch
            require(isinstance(value, torch.Tensor) and value.device.type == "cpu"
                    and not value.requires_grad, "frozen detached CPU inputs required")
            v = value.detach().contiguous().numpy().copy()
        require(v.dtype == (np.bool_ if name.endswith("mask") else np.float32)
                and v.ndim == (4 if name == "facts" else 3 if name in ("question", "candidate") else
                               3 if name == "fact_mask" else 2)
                and v.shape[0] == n and bool(v.flags.c_contiguous)
                and v.nbytes <= 16_000_000 and all(1 <= x <= 4096 for x in v.shape)
                and (name.endswith("mask") or bool(np.isfinite(v).all())),
                "bounded finite public source features only")
        items[name] = v
    facts, question, candidate = (items[n] for n in ("facts", "question", "candidate"))
    for k, raw in zip(("fact_mask", "question_mask", "candidate_mask"),
                      (facts, question, candidate)):
        require(items[k].shape == raw.shape[:-1], "public input and mask not aligned")
    require(facts.shape[-1] == question.shape[-1] == candidate.shape[-1] == 384,
            "only original Granite 384-channel feature geometry allowed")
    return items


def _npz(arrays):
    """Canonical ZIP with fixed member order and no pickle/compressed expansion."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as z:
        for name in NAMES:
            t = io.BytesIO()
            np.save(t, arrays[name], allow_pickle=False)
            member = zipfile.ZipInfo(name + ".npy", date_time=(1980, 1, 1, 0, 0, 0))
            member.compress_type = zipfile.ZIP_STORED
            member.external_attr = 0o600 << 16
            z.writestr(member, t.getvalue())
    data = buf.getvalue()
    require(len(data) <= 30_000_000, "bounded public source-feature archive")
    return data


def seal_features(output, rows, batches, *, model_sha, tokenizer_sha, preprocess_sha,
                  principal_sha, purpose_sha, origin, generation=1):
    """Write ONLY original source-derived, no-label 128-case feature batches.

    `batches` is a bounded iterable returning one previously encoded TokenBatch
    per consecutive 16 original cases. The caller owns Encoder provenance.
    Synthetic tests must set `origin='synthetic_test_only'` and cannot claim
    real-pretrained readiness or admission.
    """
    start_cpu, start_wall = time.process_time_ns(), time.perf_counter_ns()
    ids = _case_rows(rows)
    for v in (model_sha, tokenizer_sha, preprocess_sha, principal_sha, purpose_sha):
        _hex(v)
    require(type(generation) is int and generation >= 1, "positive generation required")
    require(origin in ("exact_historical_cache", "new_pretrained_physical_encoding",
                       "synthetic_test_only"), "registered original feature origin required")
    output = Path(output)
    # Material from a caller is not independently authenticated by this layer.
    _mkdir(output)
    entries = []
    stream = iter(batches)
    for i in range(BATCHES):
        selected = rows[i * MAX_BATCH:(i + 1) * MAX_BATCH]
        try:
            batch = next(stream)
        except StopIteration as error:
            raise ValueError("incomplete eight-batch original source features") from error
        arrs = _extract_six(batch, MAX_BATCH)
        folder = output / f"batch-{i:03d}"
        _mkdir(folder)
        packed = _npz(arrs)
        packed_sha = _write(folder / "features.npz", packed)
        manifest = dict(schema=FEATURE_SCHEMA, labels_present=False,
            production_authorized=False, case_ids=ids[i*MAX_BATCH:(i+1)*MAX_BATCH],
            case_source_sha256=[r["source_hash"] for r in selected],
            encoder_digest=model_sha, tokenizer_digest=tokenizer_sha,
            preprocessor_digest=preprocess_sha, principal_digest=principal_sha,
            purpose_digest=purpose_sha, generation=generation,
            tensor_archive_sha256=packed_sha,
            tensors={name:{"dtype":"bool" if name.endswith("mask") else "float32",
                 "shape":list(arrs[name].shape), "raw_sha256":_digest(arrs[name].tobytes(order="C"))}
                 for name in NAMES})
        manifest_sha = _write(folder / "manifest.json", _json(manifest))
        entries.append(dict(batch=i, case_ids=manifest["case_ids"],
            case_source_sha256=manifest["case_source_sha256"],
            feature_sha256=packed_sha, manifest_sha256=manifest_sha))
    try:
        next(stream)
    except StopIteration:
        pass
    else:
        raise ValueError("unregistered extra source features after 128 cases")
    index = dict(schema=SCHEMA, status="sealed", origin=origin, generation=generation,
        old_train_count=MAX_CASES, batches=entries,
        training_labels_available_to_source_builder=True,
        serialized_class_targets=False,
        model_sha256=model_sha, tokenizer_sha256=tokenizer_sha,
        preprocess_sha256=preprocess_sha,
        original_source_case_ids_sha256=_digest(_json(ids)),
        issuer_authenticated=False, independent_pretrained_features_verified=False,
        production_authorized=False,
        seal_cpu_ns=time.process_time_ns()-start_cpu,
        seal_wall_ns=time.perf_counter_ns()-start_wall)
    _write(output / "index.json", _json(index))
    return index


def seal_logits(input_dir, output, *, seed, arm, checkpoint, torch_predict):
    """Seal a frozen Torch candidate's actual 3-hop logits, never NumPy labels.

    torch_predict(features_dict) must execute an independently implemented
    frozen *Torch* Reader; a NumPy forward does NOT satisfy the producer role.
    The caller/runner must substantiate the actual producer independently.
    """
    start_cpu, start_wall = time.process_time_ns(), time.perf_counter_ns()
    require(seed in SEEDS and arm in ARMS, "registered seed/arm required")
    require(callable(torch_predict), "independent Torch frozen-model callback required")
    checkpoint = Path(checkpoint)
    checkpoint_raw = read_regular_file(checkpoint)
    checkpoint_sha = _digest(checkpoint_raw)
    input_dir = Path(input_dir)
    original = _load(read_regular_file(input_dir / "index.json"))
    require(original["schema"] == SCHEMA and original["old_train_count"] == MAX_CASES
            and len(original["batches"]) == BATCHES and original["status"] == "sealed",
            "only canonical 128-case presealed source feature inventory")
    output = Path(output)
    _mkdir(output)
    commits = []
    for i, entry in enumerate(original["batches"]):
        folder = input_dir / f"batch-{i:03d}"
        npz_raw = read_regular_file(folder / "features.npz", maximum=30_000_000)
        manifest_raw = read_regular_file(folder / "manifest.json")
        require(_digest(npz_raw) == entry["feature_sha256"] and
                _digest(manifest_raw) == entry["manifest_sha256"],
                "source-pinned feature bytes changed before external logits seal")
        features = _read_tensor_archive(npz_raw)
        out = torch_predict(features)
        if not isinstance(out, np.ndarray):
            import torch
            require(isinstance(out, torch.Tensor) and out.device.type == "cpu"
                    and not out.requires_grad, "actual detached Torch prediction required")
            out = out.detach().contiguous().numpy()
        require(type(out) is np.ndarray and out.shape == (MAX_BATCH, 2)
                and out.dtype == np.float32 and bool(np.isfinite(out).all()),
                "finite original 3-hop Torch logits required")
        record = dict(schema=OBSERVED_SCHEMA, labels_present=False,
            checkpoint_sha256=checkpoint_sha, tensor_archive_sha256=entry["feature_sha256"],
            case_ids=entry["case_ids"], logits=out.tolist(),
            production_authorized=False)
        name = f"batch-{i:03d}.json"
        candidate_sha = _write(output / name, _json(record))
        commits.append(dict(batch=i, name=name, sha256=candidate_sha,
                            manifest_sha256=entry["manifest_sha256"],
                            feature_sha256=entry["feature_sha256"],
                            case_ids_sha256=_digest(_json(entry["case_ids"]))))
    index = dict(schema=PREDICTION_SCHEMA,status="sealed",seed=seed,arm=arm,
                 original_features_index_sha256=_digest(read_regular_file(input_dir / "index.json")),
                 checkpoint_sha256=checkpoint_sha,
                 batches=commits,payload_contains_targets=False,
                 producer_label_isolation_independently_proven=False,
                 production_authorized=False,
                 torch_producer_self_reported=True, actual_host_attested=False,
                 cost_cpu_ns=time.process_time_ns()-start_cpu,
                 cost_wall_ns=time.perf_counter_ns()-start_wall)
    _write(output / "index.json", _json(index))
    return index


def check_source_bindings(source_dir, rows, *, allow_synthetic=False):
    ids = _case_rows(rows)
    data = _load(read_regular_file(Path(source_dir)/"index.json"))
    require(data.get("schema") == SCHEMA and data.get("status") == "sealed"
            and data.get("old_train_count") == MAX_CASES
            and type(data.get("batches")) is list and len(data["batches"]) == BATCHES,
            "complete exact source-first sealed feature index")
    require(data.get("origin") in ("exact_historical_cache", "new_pretrained_physical_encoding",
                                   "synthetic_test_only") and
            (allow_synthetic or data["origin"] != "synthetic_test_only"),
            "synthetic tokens cannot enter actual pretrained qualification")
    require(data.get("training_labels_available_to_source_builder") is True
            and data.get("serialized_class_targets") is False
            and data.get("production_authorized") is False,
            "original TRAIN labels are available to builder but forbidden in artifacts")
    require(data.get("original_source_case_ids_sha256") == _digest(_json(ids)),
            "original source-case census differs from seal")
    for key in ("model_sha256","tokenizer_sha256","preprocess_sha256"):
        _hex(data[key])
    for i, entry in enumerate(data["batches"]):
        expected=rows[i*MAX_BATCH:(i+1)*MAX_BATCH]
        require(entry["batch"] == i
                and entry["case_ids"] == ids[i*MAX_BATCH:(i+1)*MAX_BATCH]
                and entry["case_source_sha256"] == [row["source_hash"] for row in expected],
                "feature partition or immutable original source ID drift")
        for key in ("feature_sha256","manifest_sha256"):
            _hex(entry[key])
    return data


def seal_scope_receipt(features_dir, predictions_root, *, output, original_rows,
                       allow_synthetic=False):
    """Non-authorizing assembly. Missing any of nine models is NOT a PASS."""
    features_index=check_source_bindings(features_dir, original_rows,
        allow_synthetic=allow_synthetic)
    original_digest=_digest(read_regular_file(Path(features_dir)/"index.json"))
    inventory={}
    for seed in SEEDS:
        for arm in ARMS:
            folder=Path(predictions_root)/f"seed-{seed}"/arm
            obj=_load(read_regular_file(folder/"index.json"))
            require(obj.get("schema")==PREDICTION_SCHEMA and obj.get("status")=="sealed"
                    and obj.get("seed")==seed and obj.get("arm")==arm
                    and obj.get("original_features_index_sha256")==original_digest
                    and len(obj.get("batches",[]))==BATCHES
                    and obj.get("payload_contains_targets") is False
                    and obj.get("producer_label_isolation_independently_proven") is False
                    and obj.get("production_authorized") is False,
                    "candidate missing/incomplete or changed source-first logits")
            inventory[f"{seed}/{arm}"] = _digest(read_regular_file(folder/"index.json"))
    receipt=dict(schema="hepta.bridge.v75.prelabel-assembly.shadow.v1",status="sealed",
        features_index_sha256=original_digest,original_case_count=MAX_CASES,
        predictions=inventory,number_of_models=9,
        model_selection_authorized=False,source_disjoint_future_windows=0,
        production_authorized=False,labels_in_published_artifacts=False,
        training_labels_accessible_to_source_builder=True,
        label_isolation_independently_established=False,
        original_encoder_issuer_authenticated=False,
        tokenbank_authenticity_proven=False,
        synthetic_test_only=features_index["origin"]=="synthetic_test_only",
        full_lifecycle_compute_equal=False)
    _write(output,_json(receipt))
    return receipt
