"""Bounded, exact-identity numerical artifacts; no pickle or executable payloads."""

import hashlib
import io
import json
from pathlib import Path
import zipfile

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from addressing.contracts import OPERATIONS, canonical, digest
from .identity import MAX_ARTIFACT_BYTES, SCHEMA, policy_digest, unique_object


def finite_probability(value):
    return type(value) in (int, float) and np.isfinite(value) and 0 <= value <= 1.01


def save(model, directory):
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=False)
    arrays, lexical = dict(model.arrays), {}
    for name, vectorizer in model.vectorizers.items():
        arrays[name + "_idf"] = np.asarray(vectorizer.idf_, dtype=np.float64)
        lexical[name] = {"vocabulary": {key: int(value) for key, value in vectorizer.vocabulary_.items()}}
    buffer = io.BytesIO()
    np.savez_compressed(buffer, **arrays)
    weights = buffer.getvalue()
    manifest = {"schema": SCHEMA, "policy_digest": policy_digest(), "kind": model.kind, "C": model.regularization,
                "operations": list(OPERATIONS), "joint_classes": [*OPERATIONS, "reject"],
                "compatibility_classes": list(OPERATIONS), "encoder_digest": model.encoder.digest,
                "encoder_bytes": model.encoder.base_bytes, "lexical": lexical, "policies": model.policies,
                "calibration": model.calibration, "receipt": model.receipt,
                "weights_sha256": hashlib.sha256(weights).hexdigest(), "weights_bytes": len(weights),
                "numeric_array_bytes": sum(value.nbytes for value in arrays.values())}
    raw = canonical(manifest) + b"\n"
    if len(raw) > MAX_ARTIFACT_BYTES or len(weights) > MAX_ARTIFACT_BYTES:
        raise ValueError("model artifact exceeds bound")
    with (root / "manifest.json").open("xb") as handle:
        handle.write(raw)
    with (root / "weights.npz").open("xb") as handle:
        handle.write(weights)
    model.identity = hashlib.sha256(raw).hexdigest()
    return {"manifest_sha256": model.identity, "deployment_bytes_excluding_base": len(raw) + len(weights),
            "base_bytes": model.encoder.base_bytes}


def load(model_class, directory, encoder, expected_digest):
    root = Path(directory).absolute()
    paths = [root / name for name in ("manifest.json", "weights.npz")]
    if any(path.is_symlink() for item in paths for path in (item, *item.parents)) or any(
        not path.is_file() or path.stat().st_size > MAX_ARTIFACT_BYTES for path in paths
    ):
        raise ValueError("invalid bounded model artifact")
    raw, weights = (path.read_bytes() for path in paths)
    if hashlib.sha256(raw).hexdigest() != expected_digest:
        raise ValueError("model manifest identity differs")
    manifest = json.loads(raw, object_pairs_hook=unique_object,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite model field")))
    required = {"schema", "policy_digest", "kind", "C", "operations", "joint_classes", "compatibility_classes",
                "encoder_digest", "encoder_bytes", "lexical", "policies", "calibration", "receipt",
                "weights_sha256", "weights_bytes", "numeric_array_bytes"}
    if set(manifest) != required or manifest["schema"] != SCHEMA or manifest["policy_digest"] != policy_digest():
        raise ValueError("model schema or runtime policy differs")
    if (manifest["operations"] != list(OPERATIONS) or manifest["joint_classes"] != [*OPERATIONS, "reject"]
            or manifest["compatibility_classes"] != list(OPERATIONS)):
        raise ValueError("model class convention differs")
    if manifest["encoder_digest"] != encoder.digest or manifest["encoder_bytes"] != encoder.base_bytes:
        raise ValueError("encoder identity differs")
    if len(weights) != manifest["weights_bytes"] or hashlib.sha256(weights).hexdigest() != manifest["weights_sha256"]:
        raise ValueError("model weight identity differs")
    with zipfile.ZipFile(io.BytesIO(weights)) as archive:
        entries = archive.infolist()
        if (len(entries) not in (4, 6) or len({item.filename for item in entries}) != len(entries)
                or sum(item.file_size for item in entries) > MAX_ARTIFACT_BYTES):
            raise ValueError("expanded model tensors exceed bounds")
    with np.load(io.BytesIO(weights), allow_pickle=False) as saved:
        arrays = {name: saved[name].copy() for name in saved.files}
    result = model_class(encoder, manifest["kind"], manifest["C"])
    expected = {name + ending for name in ("joint", "compat") for ending in ("_coef", "_intercept")}
    if result.kind == "hybrid":
        if set(manifest["lexical"]) != {"char", "word"}:
            raise ValueError("lexical blocks differ")
        for name, maximum, ngrams in (("char", 6000, (2, 5)), ("word", 3000, (1, 2))):
            vocabulary = manifest["lexical"][name]["vocabulary"]
            if not isinstance(vocabulary, dict) or not 1 <= len(vocabulary) <= maximum or any(
                not isinstance(key, str) or not key or len(key.encode()) > 8192 or type(value) is not int
                for key, value in vocabulary.items()
            ) or sorted(vocabulary.values()) != list(range(len(vocabulary))):
                raise ValueError("invalid vocabulary")
            vectorizer = TfidfVectorizer(analyzer=name, ngram_range=ngrams, sublinear_tf=True,
                                         lowercase=False, vocabulary=vocabulary)
            idf = arrays.get(name + "_idf")
            if idf is None or idf.shape != (len(vocabulary),) or np.any(idf < 1):
                raise ValueError("invalid lexical IDF")
            vectorizer.idf_ = idf
            result.vectorizers[name] = vectorizer
            expected.add(name + "_idf")
    elif manifest["lexical"]:
        raise ValueError("unexpected lexical blocks")
    width = 384 + sum(len(item.vocabulary) for item in result.vectorizers.values())
    if set(arrays) != expected or any(array.dtype != np.float64 or not np.isfinite(array).all() for array in arrays.values()):
        raise ValueError("invalid model tensors")
    for name, classes in (("joint", len(OPERATIONS) + 1), ("compat", len(OPERATIONS))):
        if arrays[name + "_coef"].shape != (classes, width) or arrays[name + "_intercept"].shape != (classes,):
            raise ValueError("invalid classifier dimensions")
    if manifest["numeric_array_bytes"] != sum(array.nbytes for array in arrays.values()):
        raise ValueError("array accounting differs")
    policies = manifest["policies"]
    if not isinstance(policies, dict) or set(policies) != set(OPERATIONS) or any(
        not isinstance(value, dict) or set(value) != {"threshold", "margin"}
        or not all(finite_probability(number) for number in value.values()) for value in policies.values()
    ):
        raise ValueError("invalid per-operation admission policy")
    calibration = manifest["calibration"]
    if calibration is not None and (
        not isinstance(calibration, dict)
        or calibration.get("schema") != "hepta.memory.v9.empirical-admission.v1"
        or type(calibration.get("empirical_gate_passed")) is not bool
        or calibration.get("population_risk_established") is not False
        or calibration.get("selected_policy_sha256") != digest(policies)
        or calibration.get("calibration_used_for_weights") is not False
        or calibration.get("candidate_reselected") is not False
    ):
        raise ValueError("invalid or mismatched independent calibration record")
    result.arrays = {name: value for name, value in arrays.items() if not name.endswith("_idf")}
    result.policies, result.calibration, result.receipt, result.identity = policies, calibration, manifest["receipt"], expected_digest
    return result
