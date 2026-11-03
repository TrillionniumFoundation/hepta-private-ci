"""Factorized intent and answer-shape heads over fixed multilingual features."""

import hashlib
import io
import json
from pathlib import Path
import time
import warnings
import zipfile

import numpy as np
from scipy import sparse
from scipy.special import softmax
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from threadpoolctl import threadpool_limits

from .contracts import OPERATIONS, OP_SHAPE, SHAPES, canonical, digest, normalize
from .capabilities import capability_violation


NEGATIVES = (
    "mutation",
    "prediction",
    "aggregation",
    "explanation",
    "external",
    "arithmetic",
    "counterfactual",
    "time_composition",
    "multiple_outputs",
    "other",
)
LABELS = (*OPERATIONS, *("reject:" + name for name in NEGATIVES))
KINDS = ("semantic", "hybrid")


def policy_digest():
    root = Path(__file__).resolve().parent
    return digest(
        {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in ("model.py", "capabilities.py", "contracts.py", "planner.py")
        }
    )


class IntentModel:
    """Outputs an execution hypothesis, never a memory value or an authority.

    Intent and expected answer shape are trained separately. Their combined
    score is a ranking score; independent calibration controls the threshold.
    The encoder is fixed, and only the two small linear heads are fitted.
    """

    def __init__(self, encoder, kind="hybrid", regularization=8.0):
        if kind not in KINDS or not 0 < regularization <= 100 or encoder is None:
            raise ValueError("invalid intent model configuration")
        self.encoder, self.kind, self.regularization = (
            encoder,
            kind,
            float(regularization),
        )
        self.vectorizers, self.arrays, self.receipt = {}, {}, {}
        self.threshold, self.margin = 1.0, 1.0
        self.calibration, self.identity = None, None

    def input_supported(self, value):
        if not isinstance(value, str) or not value or len(value.encode()) > 8192:
            return False
        return not self.encoder.tokenizer.encode(normalize(value)).overflowing

    def features(self, texts, *, fit=False, dense=None):
        texts = [normalize(value) for value in texts]
        if not 1 <= len(texts) <= 16384 or any(
            not self.input_supported(value) for value in texts
        ):
            raise ValueError("empty, unbounded or truncated text")
        dense = self.encoder.encode(texts) if dense is None else np.asarray(dense)
        if dense.shape != (len(texts), 384) or not np.isfinite(dense).all():
            raise ValueError("invalid fixed semantic features")
        blocks = [sparse.csr_matrix(dense)]
        if self.kind == "hybrid":
            for name, options in (
                (
                    "char",
                    {"analyzer": "char", "ngram_range": (2, 5), "max_features": 6000},
                ),
                (
                    "word",
                    {"analyzer": "word", "ngram_range": (1, 2), "max_features": 3000},
                ),
            ):
                if fit:
                    self.vectorizers[name] = TfidfVectorizer(
                        **options, sublinear_tf=True, lowercase=False
                    )
                vectorizer = self.vectorizers[name]
                block = (
                    vectorizer.fit_transform(texts)
                    if fit
                    else vectorizer.transform(texts)
                )
                blocks.append(block)
        return sparse.hstack(blocks, format="csr") / np.sqrt(len(blocks))

    def fit(self, rows, *, dense=None):
        if not 32 <= len(rows) <= 16384:
            raise ValueError("bounded nontrivial training corpus required")
        features = self.features([row["text"] for row in rows], fit=True, dense=dense)
        labels = [
            row["operation"]
            if row["operation"] != "reject"
            else "reject:" + row["negative_group"]
            for row in rows
        ]
        shapes = [
            OP_SHAPE[OPERATIONS.index(row["operation"])]
            if row["operation"] != "reject"
            else "unsupported"
            for row in rows
        ]
        if set(labels) != set(LABELS) or set(shapes) != set(SHAPES):
            raise ValueError("every intent and shape class must have training evidence")
        receipts = []
        for name, targets, order in (
            ("intent", labels, LABELS),
            ("shape", shapes, SHAPES),
        ):
            started, cpu = time.perf_counter(), time.process_time()
            learner = LogisticRegression(
                C=self.regularization,
                class_weight="balanced",
                max_iter=2000,
                solver="lbfgs",
                random_state=7103,
                tol=1e-7,
            )
            with (
                warnings.catch_warnings(record=True) as caught,
                threadpool_limits(limits=1),
            ):
                warnings.simplefilter("always")
                learner.fit(features, targets)
            positions = [list(learner.classes_).index(label) for label in order]
            self.arrays[name + "_coef"] = np.asarray(
                learner.coef_[positions], dtype=np.float64
            )
            self.arrays[name + "_intercept"] = np.asarray(
                learner.intercept_[positions], dtype=np.float64
            )
            receipts.append(
                {
                    "head": name,
                    "actual_fit": True,
                    "cpu_seconds": time.process_time() - cpu,
                    "wall_seconds": time.perf_counter() - started,
                    "iterations": learner.n_iter_.tolist(),
                    "warnings": [str(item.message) for item in caught],
                }
            )
        self.receipt = {
            "training_rows": len(rows),
            "training_sha256": digest(rows),
            "heads": receipts,
            "base_updated": False,
            "blas_threads": 1,
            "seed_interpretation": "deterministic optimization, not independent language replication",
        }
        return self.receipt

    def hypotheses(self, texts, *, dense=None):
        violations = [capability_violation(value) for value in texts]
        eligible = [index for index, reason in enumerate(violations) if reason is None]
        output = [
            {
                "raw_operation": "reject",
                "score": 1.0,
                "margin": 1.0,
                "score_kind": "explicit registered-capability boundary",
                "capability_reason": reason,
            }
            for reason in violations
        ]
        if not eligible:
            return output
        features = self.features(
            [texts[index] for index in eligible],
            dense=None if dense is None else np.asarray(dense)[eligible],
        )
        probabilities = {}
        for name in ("intent", "shape"):
            logits = (
                np.asarray(features @ self.arrays[name + "_coef"].T)
                + self.arrays[name + "_intercept"]
            )
            probabilities[name] = softmax(logits, axis=1)
        intent, shape = probabilities["intent"], probabilities["shape"]
        supported = (
            intent[:, : len(OPERATIONS)]
            * shape[:, [SHAPES.index(value) for value in OP_SHAPE]]
        )
        rejected = (
            intent[:, len(OPERATIONS) :].sum(axis=1)
            + shape[:, SHAPES.index("unsupported")]
        )
        scores = np.column_stack((supported, rejected))
        scores /= scores.sum(axis=1, keepdims=True)
        for index, values in zip(eligible, scores):
            order = np.argsort(-values, kind="stable")
            top = int(order[0])
            output[index] = {
                "raw_operation": (*OPERATIONS, "reject")[top],
                "score": float(values[top]),
                "margin": float(values[top] - values[order[1]]),
                "score_kind": "factorized intent/shape ranking score; not calibrated posterior",
                "capability_reason": None,
            }
        return output

    def decide(self, hypothesis):
        accepted = (
            hypothesis["raw_operation"] in OPERATIONS
            and hypothesis["score"] >= self.threshold
            and hypothesis["margin"] >= self.margin
        )
        return {
            **hypothesis,
            "operation": hypothesis["raw_operation"] if accepted else None,
            "threshold": self.threshold,
            "required_margin": self.margin,
        }

    def save(self, directory):
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=False)
        arrays, lexical = dict(self.arrays), {}
        for name, vectorizer in self.vectorizers.items():
            arrays[name + "_idf"] = np.asarray(vectorizer.idf_, dtype=np.float64)
            lexical[name] = {
                "vocabulary": {
                    key: int(value) for key, value in vectorizer.vocabulary_.items()
                }
            }
        buffer = io.BytesIO()
        np.savez_compressed(buffer, **arrays)
        weights = buffer.getvalue()
        manifest = {
            "schema": "hepta.memory.v7.intent-model.v1",
            "policy_digest": policy_digest(),
            "kind": self.kind,
            "C": self.regularization,
            "labels": list(LABELS),
            "shapes": list(SHAPES),
            "encoder_digest": self.encoder.digest,
            "encoder_bytes": self.encoder.base_bytes,
            "lexical": lexical,
            "threshold": self.threshold,
            "margin": self.margin,
            "calibration": self.calibration,
            "receipt": self.receipt,
            "weights_sha256": hashlib.sha256(weights).hexdigest(),
            "weights_bytes": len(weights),
            "numeric_array_bytes": sum(value.nbytes for value in arrays.values()),
        }
        raw = canonical(manifest) + b"\n"
        (root / "manifest.json").write_bytes(raw)
        (root / "weights.npz").write_bytes(weights)
        self.identity = hashlib.sha256(raw).hexdigest()
        return {
            "manifest_sha256": self.identity,
            "deployment_bytes_excluding_base": len(raw) + len(weights),
            "base_bytes": self.encoder.base_bytes,
        }

    @classmethod
    def load(cls, directory, encoder, expected_digest):
        root = Path(directory).absolute()
        paths = [root / name for name in ("manifest.json", "weights.npz")]
        if any(
            path.is_symlink() for item in paths for path in (item, *item.parents)
        ) or any(
            not path.is_file() or path.stat().st_size > 8_000_000 for path in paths
        ):
            raise ValueError("invalid bounded model artifact")
        raw, weights = (path.read_bytes() for path in paths)
        if hashlib.sha256(raw).hexdigest() != expected_digest:
            raise ValueError("intent model manifest identity differs")
        manifest = json.loads(raw)
        if (
            manifest["schema"] != "hepta.memory.v7.intent-model.v1"
            or manifest.get("policy_digest") != policy_digest()
            or manifest["labels"] != list(LABELS)
            or manifest["shapes"] != list(SHAPES)
            or manifest["encoder_digest"] != encoder.digest
        ):
            raise ValueError("model schema or encoder identity differs")
        if (
            len(weights) != manifest["weights_bytes"]
            or hashlib.sha256(weights).hexdigest() != manifest["weights_sha256"]
        ):
            raise ValueError("model weight identity differs")
        with zipfile.ZipFile(io.BytesIO(weights)) as archive:
            if (
                len(archive.infolist()) not in (4, 6)
                or sum(item.file_size for item in archive.infolist()) > 8_000_000
            ):
                raise ValueError("expanded model tensors exceed bounds")
        with np.load(io.BytesIO(weights), allow_pickle=False) as saved:
            arrays = {name: saved[name].copy() for name in saved.files}
        result = cls(encoder, manifest["kind"], manifest["C"])
        expected = {
            name + ending
            for name in ("intent", "shape")
            for ending in ("_coef", "_intercept")
        }
        if result.kind == "hybrid":
            if set(manifest["lexical"]) != {"char", "word"}:
                raise ValueError("lexical blocks differ")
            for name, maximum, ngrams in (
                ("char", 6000, (2, 5)),
                ("word", 3000, (1, 2)),
            ):
                vocabulary = manifest["lexical"][name]["vocabulary"]
                if not 1 <= len(vocabulary) <= maximum or sorted(
                    vocabulary.values()
                ) != list(range(len(vocabulary))):
                    raise ValueError("invalid vocabulary")
                vectorizer = TfidfVectorizer(
                    analyzer=name,
                    ngram_range=ngrams,
                    sublinear_tf=True,
                    lowercase=False,
                    vocabulary=vocabulary,
                )
                idf = arrays[name + "_idf"]
                if idf.shape != (len(vocabulary),) or np.any(idf < 1):
                    raise ValueError("invalid lexical IDF")
                vectorizer.idf_ = idf
                result.vectorizers[name] = vectorizer
                expected.add(name + "_idf")
        elif manifest["lexical"]:
            raise ValueError("unexpected lexical blocks")
        width = 384 + sum(len(item.vocabulary) for item in result.vectorizers.values())
        if set(arrays) != expected or any(
            array.dtype != np.float64 or not np.isfinite(array).all()
            for array in arrays.values()
        ):
            raise ValueError("invalid model tensor set")
        for name, classes in (("intent", len(LABELS)), ("shape", len(SHAPES))):
            if arrays[name + "_coef"].shape != (classes, width) or arrays[
                name + "_intercept"
            ].shape != (classes,):
                raise ValueError("invalid classifier dimensions")
        result.arrays = {
            name: array for name, array in arrays.items() if not name.endswith("_idf")
        }
        result.threshold, result.margin = manifest["threshold"], manifest["margin"]
        if any(
            type(value) not in (int, float)
            or not np.isfinite(value)
            or not 0 <= value <= 1.01
            for value in (result.threshold, result.margin)
        ):
            raise ValueError("invalid acceptance policy")
        result.calibration, result.receipt, result.identity = (
            manifest["calibration"],
            manifest["receipt"],
            expected_digest,
        )
        return result
