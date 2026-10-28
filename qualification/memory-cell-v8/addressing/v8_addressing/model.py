"""Separate supportedness and positive-operation heads with selective readout."""

import hashlib
import io
import json
from pathlib import Path
import time
import warnings
import zipfile

import numpy as np
from scipy.special import expit, softmax
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from threadpoolctl import threadpool_limits

from addressing.capabilities import capability_violation
from addressing.contracts import OPERATIONS, canonical, digest
from addressing.model import IntentModel


SCHEMA = "hepta.memory.v8.selective-intent-model.v1"
MAX_ARTIFACT_BYTES = 16_000_000
SCORE_KIND = "minimum of supportedness and positive-operation scores; not calibrated posterior"


def policy_digest():
    here = Path(__file__).resolve().parent
    qualification = here.parents[2]
    paths = [here / "__init__.py", here / "model.py", here / "policy.py", here.parent / "worker.py",
             here.parent / "qualification_shadow_worker.py", here.parent / "bootstrap.py"]
    paths += [qualification / "memory-cell-v7/addressing" / name for name in (
        "__init__.py", "contracts.py", "capabilities.py", "model.py", "planner.py", "worker.py")]
    paths += [qualification / "memory-cell-v6/v6" / name for name in ("__init__.py", "encoder.py")]
    return digest({path.relative_to(qualification).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in sorted(paths)})


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate model field")
        result[key] = value
    return result


def finite_probability(value):
    return type(value) in (int, float) and np.isfinite(value) and 0 <= value <= 1.01


class SelectiveIntentModel(IntentModel):
    """Train the rejection task separately from choosing among valid operations.

    Frozen V7 supplies bounded feature extraction and explicit capability checks.
    This changes actual fitted targets and parameter inference. It neither looks
    up phrases nor turns a softmax value into a population-risk guarantee.
    """

    def __init__(self, encoder, kind="hybrid", regularization=8.0):
        super().__init__(encoder, kind, regularization)
        self.policies = {operation: {"threshold": 1.01, "margin": 0.0} for operation in OPERATIONS}

    def fit(self, rows, *, dense=None):
        if not 32 <= len(rows) <= 16_384:
            raise ValueError("bounded nontrivial training rows required")
        labels = [row["operation"] for row in rows]
        if set(labels) != {*OPERATIONS, "reject"}:
            raise ValueError("six positive operations and rejection examples required")
        features = self.features([row["text"] for row in rows], fit=True, dense=dense)
        positive = np.array([label != "reject" for label in labels])
        receipts = []
        for name, matrix, targets, order in (
            ("operation", features[positive], [label for label in labels if label != "reject"], OPERATIONS),
            ("support", features, ["supported" if value else "reject" for value in positive], ("reject", "supported")),
        ):
            started, cpu = time.perf_counter(), time.process_time()
            learner = LogisticRegression(C=self.regularization, class_weight="balanced", max_iter=2000,
                                         solver="lbfgs", random_state=8103, tol=1e-7)
            with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=1):
                warnings.simplefilter("always")
                learner.fit(matrix, targets)
            if name == "support":
                if list(learner.classes_) != list(order) or learner.coef_.shape[0] != 1:
                    raise ValueError("binary supportedness class convention differs")
                coefficients, intercepts = learner.coef_, learner.intercept_
            else:
                positions = [list(learner.classes_).index(label) for label in order]
                coefficients, intercepts = learner.coef_[positions], learner.intercept_[positions]
            self.arrays[name + "_coef"] = np.asarray(coefficients, dtype=np.float64)
            self.arrays[name + "_intercept"] = np.asarray(intercepts, dtype=np.float64)
            receipts.append({"head": name, "actual_fit": True, "training_rows": len(targets),
                             "cpu_seconds": time.process_time() - cpu, "wall_seconds": time.perf_counter() - started,
                             "iterations": learner.n_iter_.tolist(), "warnings": [str(item.message) for item in caught]})
        self.receipt = {"training_rows": len(rows), "training_sha256": digest(rows), "heads": receipts,
                        "base_updated": False, "blas_threads": 1,
                        "seed_interpretation": "deterministic optimization; not independent language replication"}
        return self.receipt

    def hypotheses(self, texts, *, dense=None):
        reasons = [capability_violation(value) for value in texts]
        eligible = [index for index, reason in enumerate(reasons) if reason is None]
        output = [{"raw_operation": "reject", "score": 1.0, "margin": 1.0,
                   "score_kind": "explicit registered-capability boundary", "capability_reason": reason}
                  for reason in reasons]
        if not eligible:
            return output
        features = self.features([texts[index] for index in eligible],
                                 dense=None if dense is None else np.asarray(dense)[eligible])
        operation = softmax(np.asarray(features @ self.arrays["operation_coef"].T)
                            + self.arrays["operation_intercept"], axis=1)
        support = expit((np.asarray(features @ self.arrays["support_coef"].T)
                         + self.arrays["support_intercept"]).reshape(-1))
        for index, probabilities, supported in zip(eligible, operation, support):
            order = np.argsort(-probabilities, kind="stable")
            first, second = int(order[0]), int(order[1])
            score = min(float(probabilities[first]), float(supported))
            margin = max(0.0, min(float(probabilities[first] - probabilities[second]), 2 * float(supported) - 1))
            output[index] = {"raw_operation": OPERATIONS[first], "score": score, "margin": margin,
                             "score_kind": SCORE_KIND, "capability_reason": None}
        return output

    def decide(self, hypothesis):
        raw = hypothesis["raw_operation"]
        policy = self.policies.get(raw, {"threshold": 1.01, "margin": 0.0})
        accepted = raw in OPERATIONS and hypothesis["score"] >= policy["threshold"] and hypothesis["margin"] >= policy["margin"]
        # Exactly the eight existing host fields: no hidden scores or labels
        # can become unrecognized executable fields at the worker boundary.
        return {**hypothesis, "operation": raw if accepted else None,
                "threshold": policy["threshold"], "required_margin": policy["margin"]}

    def save(self, directory):
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=False)
        arrays, lexical = dict(self.arrays), {}
        for name, vectorizer in self.vectorizers.items():
            arrays[name + "_idf"] = np.asarray(vectorizer.idf_, dtype=np.float64)
            lexical[name] = {"vocabulary": {key: int(value) for key, value in vectorizer.vocabulary_.items()}}
        buffer = io.BytesIO()
        np.savez_compressed(buffer, **arrays)
        weights = buffer.getvalue()
        manifest = {"schema": SCHEMA, "policy_digest": policy_digest(), "kind": self.kind, "C": self.regularization,
                    "operations": list(OPERATIONS), "support_classes": ["reject", "supported"],
                    "encoder_digest": self.encoder.digest, "encoder_bytes": self.encoder.base_bytes,
                    "lexical": lexical, "policies": self.policies, "calibration": self.calibration,
                    "receipt": self.receipt, "weights_sha256": hashlib.sha256(weights).hexdigest(),
                    "weights_bytes": len(weights), "numeric_array_bytes": sum(value.nbytes for value in arrays.values())}
        raw = canonical(manifest) + b"\n"
        if len(raw) > MAX_ARTIFACT_BYTES or len(weights) > MAX_ARTIFACT_BYTES:
            raise ValueError("model artifact exceeds bound")
        (root / "manifest.json").write_bytes(raw)
        (root / "weights.npz").write_bytes(weights)
        self.identity = hashlib.sha256(raw).hexdigest()
        return {"manifest_sha256": self.identity, "deployment_bytes_excluding_base": len(raw) + len(weights),
                "base_bytes": self.encoder.base_bytes}

    @classmethod
    def load(cls, directory, encoder, expected_digest):
        root = Path(directory).absolute()
        paths = [root / name for name in ("manifest.json", "weights.npz")]
        if any(path.is_symlink() for item in paths for path in (item, *item.parents)) or any(
            not path.is_file() or path.stat().st_size > MAX_ARTIFACT_BYTES for path in paths
        ):
            raise ValueError("invalid bounded model artifact")
        raw, weights = (path.read_bytes() for path in paths)
        if hashlib.sha256(raw).hexdigest() != expected_digest:
            raise ValueError("model manifest identity differs")
        manifest = json.loads(raw, object_pairs_hook=unique_object)
        required = {"schema", "policy_digest", "kind", "C", "operations", "support_classes", "encoder_digest",
                    "encoder_bytes", "lexical", "policies", "calibration", "receipt", "weights_sha256", "weights_bytes", "numeric_array_bytes"}
        if set(manifest) != required or manifest["schema"] != SCHEMA or manifest["policy_digest"] != policy_digest():
            raise ValueError("model schema or runtime policy differs")
        if manifest["operations"] != list(OPERATIONS) or manifest["support_classes"] != ["reject", "supported"]:
            raise ValueError("model class convention differs")
        if manifest["encoder_digest"] != encoder.digest or manifest["encoder_bytes"] != encoder.base_bytes:
            raise ValueError("encoder identity differs")
        if len(weights) != manifest["weights_bytes"] or hashlib.sha256(weights).hexdigest() != manifest["weights_sha256"]:
            raise ValueError("model weight identity differs")
        with zipfile.ZipFile(io.BytesIO(weights)) as archive:
            entries = archive.infolist()
            if len(entries) not in (4, 6) or len({item.filename for item in entries}) != len(entries) or sum(item.file_size for item in entries) > MAX_ARTIFACT_BYTES:
                raise ValueError("expanded model tensors exceed bounds")
        with np.load(io.BytesIO(weights), allow_pickle=False) as saved:
            arrays = {name: saved[name].copy() for name in saved.files}
        result = cls(encoder, manifest["kind"], manifest["C"])
        expected = {name + ending for name in ("operation", "support") for ending in ("_coef", "_intercept")}
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
        for name, classes in (("operation", len(OPERATIONS)), ("support", 1)):
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
            or calibration.get("schema") != "hepta.memory.v8.empirical-admission.v1"
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
