"""Trained semantic/lexical routing with explicit abstention and checked artifacts."""

import io
import json
from pathlib import Path
import time
import warnings

import numpy as np
from scipy import sparse
from scipy.special import logsumexp
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from threadpoolctl import threadpool_limits

from .encoder import canonical, digest, normalize_request


OPERATIONS = ("current", "history", "semantic", "procedure", "change", "apply")
LABELS = (*OPERATIONS, "reject")
KINDS = ("semantic", "hybrid", "lexical", "hybrid_split", "lexical_split")
NEGATIVE_LABELS = ("mutation", "prediction", "aggregation", "explanation", "external", "other")


def _decision(scores, threshold, margin):
    logits = scores - scores.max(axis=1, keepdims=True)
    probability = np.exp(logits)
    probability /= probability.sum(axis=1, keepdims=True)
    order = np.argsort(-probability, axis=1, kind="stable")
    result = []
    for row, ranking in zip(probability, order):
        label = LABELS[int(ranking[0])]
        score, gap = float(row[ranking[0]]), float(row[ranking[0]] - row[ranking[1]])
        accepted = label != "reject" and score >= threshold and gap >= margin
        result.append(
            {
                "operation": label if accepted else None,
                "raw_operation": label,
                "score": score,
                "margin": gap,
                "score_kind": "logistic-softmax; selection-thresholded, not a population guarantee",
            }
        )
    return result


def measure(rows, decisions):
    known = [i for i, row in enumerate(rows) if row["operation"] != "reject"]
    unknown = [i for i, row in enumerate(rows) if row["operation"] == "reject"]
    correct = sum(decisions[i]["operation"] == rows[i]["operation"] for i in known)
    wrong = sum(decisions[i]["operation"] not in (None, rows[i]["operation"]) for i in known)
    ood = sum(decisions[i]["operation"] is not None for i in unknown)
    languages = {}
    for language in sorted({row["language"] for row in rows}):
        indices = [i for i in known if rows[i]["language"] == language]
        if indices:
            languages[language] = sum(decisions[i]["operation"] == rows[i]["operation"] for i in indices) / len(indices)
    return {
        "known": len(known),
        "known_correct": correct,
        "known_wrong_accepted": wrong,
        "known_correct_rate": correct / max(len(known), 1),
        "known_wrong_rate": wrong / max(len(known), 1),
        "ood": len(unknown),
        "ood_accepted": ood,
        "ood_acceptance_rate": ood / max(len(unknown), 1),
        "language_correct_rates": languages,
    }


class Router:
    """A shared frozen encoder plus a fitted small classification head.

    This component receives only query text. It never loads memory payloads,
    source values, execution traces, or gold held labels.
    """

    def __init__(self, encoder, kind="hybrid", seed=6001, regularization=3.0):
        if kind not in KINDS or type(seed) is not int or not 0 <= seed < 2**32:
            raise ValueError("invalid router candidate")
        feature_kind = kind.removesuffix("_split")
        if feature_kind != "lexical" and encoder is None:
            raise ValueError("semantic routing requires an admitted encoder")
        if not np.isfinite(regularization) or not 0 < regularization <= 100:
            raise ValueError("invalid inverse regularization")
        self.encoder, self.kind, self.seed = encoder, kind, seed
        self.feature_kind = feature_kind
        self.model_labels = (
            (*OPERATIONS, *("reject:" + x for x in NEGATIVE_LABELS)) if kind.endswith("_split") else LABELS
        )
        self.regularization = float(regularization)
        self.vectorizer = None
        self.coefficients = self.intercept = None
        self.threshold, self.margin = 1.0, 1.0
        self.language_policy = {}
        self.receipt = {}

    def features(self, texts, *, fit=False, dense=None):
        texts = [normalize_request(text) for text in texts]
        blocks = []
        if self.feature_kind != "lexical":
            dense = self.encoder.encode(texts) if dense is None else np.asarray(dense)
            if dense.shape != (len(texts), 384) or not np.isfinite(dense).all():
                raise ValueError("invalid pretrained features")
            blocks.append(sparse.csr_matrix(dense))
        if self.feature_kind != "semantic":
            if fit:
                self.vectorizer = TfidfVectorizer(
                    analyzer="char", ngram_range=(2, 5), max_features=6000, sublinear_tf=True, lowercase=False
                )
                lexical = self.vectorizer.fit_transform(texts)
            else:
                lexical = self.vectorizer.transform(texts)
            blocks.append(lexical)
        return sparse.hstack(blocks, format="csr") / np.sqrt(len(blocks))

    def fit(self, rows, *, dense=None):
        if not 14 <= len(rows) <= 16384 or {row["operation"] for row in rows} != set(LABELS):
            raise ValueError("all declared classes and bounded rows required")
        started, cpu = time.perf_counter(), time.process_time()
        features = self.features([row["text"] for row in rows], fit=True, dense=dense)
        learner = LogisticRegression(
            C=self.regularization,
            class_weight="balanced",
            max_iter=2000,
            solver="lbfgs",
            random_state=self.seed,
            tol=1e-7,
        )
        targets = [
            "reject:" + row["negative_group"]
            if self.kind.endswith("_split") and row["operation"] == "reject"
            else row["operation"]
            for row in rows
        ]
        with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=1):
            warnings.simplefilter("always")
            learner.fit(features, targets)
        indices = [list(learner.classes_).index(label) for label in self.model_labels]
        self.coefficients = np.asarray(learner.coef_[indices], dtype=np.float64)
        self.intercept = np.asarray(learner.intercept_[indices], dtype=np.float64)
        self.receipt = {
            "training_rows": len(rows),
            "training_sha256": digest(canonical(rows)),
            "kind": self.kind,
            "seed": self.seed,
            "C": self.regularization,
            "iterations": learner.n_iter_.tolist(),
            "warning_messages": [str(item.message) for item in caught],
            "head_parameter_bytes": self.coefficients.nbytes + self.intercept.nbytes,
            "wall_seconds": time.perf_counter() - started,
            "cpu_seconds": time.process_time() - cpu,
            "blas_threads": 1,
            "base_updated": False,
            "actual_fit": True,
        }
        return self.receipt

    def scores(self, texts, *, dense=None):
        if self.coefficients is None or not 0 < len(texts) <= 16384:
            raise ValueError("fitted router and bounded nonempty batch required")
        scores = np.asarray(self.features(texts, dense=dense) @ self.coefficients.T) + self.intercept
        if self.kind.endswith("_split"):
            scores = np.column_stack((scores[:, : len(OPERATIONS)], logsumexp(scores[:, len(OPERATIONS) :], axis=1)))
        return scores

    def decisions(self, texts, scores):
        output = []
        for text, row in zip(texts, scores):
            language = "zh" if any("\u3400" <= char <= "\u9fff" for char in text) else "en"
            policy = self.language_policy.get(language, {"threshold": self.threshold, "margin": self.margin})
            output.extend(_decision(row[None, :], policy["threshold"], policy["margin"]))
        return output

    def routes(self, texts):
        return self.decisions(texts, self.scores(texts))

    def route(self, text):
        return self.routes([text])[0]

    def calibrate(self, rows, *, dense=None):
        scores = self.scores([row["text"] for row in rows], dense=dense)
        trials = []
        for threshold in (0.0, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85):
            for margin in (0.0, 0.05, 0.1, 0.2, 0.3):
                metrics = measure(rows, _decision(scores, threshold, margin))
                feasible = metrics["ood_acceptance_rate"] <= 0.05 and metrics["known_wrong_rate"] <= 0.02
                key = (
                    feasible,
                    min(metrics["language_correct_rates"].values()),
                    metrics["known_correct_rate"],
                    -metrics["ood_acceptance_rate"],
                    -threshold,
                    -margin,
                )
                trials.append({"threshold": threshold, "margin": margin, "metrics": metrics, "selection_key": key})
        best = max(trials, key=lambda x: x["selection_key"])
        self.threshold, self.margin = best["threshold"], best["margin"]
        policies = {}
        for language in sorted({row["language"] for row in rows}):
            indices = [i for i, row in enumerate(rows) if row["language"] == language]
            local_rows = [rows[i] for i in indices]
            local = []
            for trial in trials:
                metrics = measure(local_rows, _decision(scores[indices], trial["threshold"], trial["margin"]))
                key = (
                    metrics["ood_acceptance_rate"] <= 0.05 and metrics["known_wrong_rate"] <= 0.02,
                    metrics["known_correct_rate"],
                    -metrics["ood_acceptance_rate"],
                    -trial["threshold"],
                    -trial["margin"],
                )
                local.append((key, {"threshold": trial["threshold"], "margin": trial["margin"]}))
            policies[language] = max(local, key=lambda x: x[0])[1]
        self.language_policy = policies
        metrics = measure(rows, self.decisions([row["text"] for row in rows], scores))
        key = (
            metrics["ood_acceptance_rate"] <= 0.05 and metrics["known_wrong_rate"] <= 0.02,
            min(metrics["language_correct_rates"].values()),
            metrics["known_correct_rate"],
            -metrics["ood_acceptance_rate"],
            -self.threshold,
            -self.margin,
        )
        language_trial = {
            "threshold": self.threshold,
            "margin": self.margin,
            "language_policy": policies,
            "metrics": metrics,
            "selection_key": key,
        }
        if key > tuple(best["selection_key"]):
            best = language_trial
        else:
            self.language_policy = {}
        trials.append(language_trial)
        self.receipt["selection_sha256"] = digest(canonical(rows))
        self.receipt["selection"] = best
        return trials

    def save(self, directory):
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=False)
        arrays = {"coefficients": self.coefficients, "intercept": self.intercept}
        lexical = None
        if self.vectorizer is not None:
            arrays["idf"] = np.asarray(self.vectorizer.idf_, dtype=np.float64)
            lexical = {
                "vocabulary": {word: int(index) for word, index in self.vectorizer.vocabulary_.items()},
                "analyzer": "char",
                "ngram_range": [2, 5],
                "sublinear_tf": True,
                "lowercase": False,
            }
        buffer = io.BytesIO()
        np.savez_compressed(buffer, **arrays)
        raw = buffer.getvalue()
        (root / "weights.npz").write_bytes(raw)
        manifest = {
            "schema": "hepta.memory.v6.router.v1",
            "labels": list(LABELS),
            "model_labels": list(self.model_labels),
            "kind": self.kind,
            "seed": self.seed,
            "C": self.regularization,
            "threshold": self.threshold,
            "margin": self.margin,
            "language_policy": self.language_policy,
            "encoder_digest": None if self.feature_kind == "lexical" else self.encoder.digest,
            "encoder_bytes": 0 if self.feature_kind == "lexical" else self.encoder.base_bytes,
            "weights_sha256": digest(raw),
            "weights_bytes": len(raw),
            "lexical": lexical,
            "training_receipt": self.receipt,
            "numeric_array_bytes": sum(array.nbytes for array in arrays.values()),
        }
        (root / "manifest.json").write_bytes(canonical(manifest) + b"\n")
        return {
            "manifest_sha256": digest((root / "manifest.json").read_bytes()),
            "deployment_bytes_excluding_base": sum(p.stat().st_size for p in root.iterdir()),
            "base_bytes": manifest["encoder_bytes"],
            "numeric_array_bytes": manifest["numeric_array_bytes"],
        }

    @classmethod
    def load(cls, directory, encoder=None, expected_manifest_sha256=None):
        root = Path(directory).absolute()
        paths = [root / "manifest.json", root / "weights.npz"]
        if any(p.is_symlink() for path in paths for p in (path, *path.parents)) or any(
            not p.is_file() or p.stat().st_size > 4_000_000 for p in paths
        ):
            raise ValueError("invalid bounded router artifact files")
        raw_manifest, raw = (p.read_bytes() for p in paths)
        if expected_manifest_sha256 and digest(raw_manifest) != expected_manifest_sha256:
            raise ValueError("router manifest identity differs")
        manifest = json.loads(raw_manifest)
        if (
            manifest["schema"] != "hepta.memory.v6.router.v1"
            or manifest["labels"] != list(LABELS)
            or digest(raw) != manifest["weights_sha256"]
            or len(raw) != manifest["weights_bytes"]
        ):
            raise ValueError("router artifact identity differs")
        obj = cls(encoder, manifest["kind"], manifest["seed"], manifest["C"])
        expected_encoder = None if obj.feature_kind == "lexical" else encoder.digest
        if manifest["encoder_digest"] != expected_encoder:
            raise ValueError("router encoder version differs")
        import zipfile

        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if len(archive.infolist()) not in (2, 3) or sum(item.file_size for item in archive.infolist()) > 4_000_000:
                raise ValueError("expanded router tensor bytes exceed bound")
        with np.load(io.BytesIO(raw), allow_pickle=False) as stored:
            arrays = {name: stored[name].copy() for name in stored.files}
        if manifest["lexical"] is not None:
            lexical = manifest["lexical"]
            vocab = lexical["vocabulary"]
            if len(vocab) > 6000 or sorted(vocab.values()) != list(range(len(vocab))):
                raise ValueError("invalid lexical vocabulary")
            obj.vectorizer = TfidfVectorizer(
                analyzer="char", ngram_range=(2, 5), sublinear_tf=True, lowercase=False, vocabulary=vocab
            )
            obj.vectorizer.idf_ = arrays["idf"]
        elif obj.feature_kind != "semantic":
            raise ValueError("lexical features missing")
        expected_arrays = {"coefficients", "intercept"} | ({"idf"} if obj.vectorizer is not None else set())
        width = (384 if obj.feature_kind != "lexical" else 0) + (
            len(obj.vectorizer.vocabulary) if obj.vectorizer is not None else 0
        )
        if (
            manifest.get("model_labels", list(LABELS)) != list(obj.model_labels)
            or set(arrays) != expected_arrays
            or arrays["coefficients"].shape != (len(obj.model_labels), width)
            or arrays["intercept"].shape != (len(obj.model_labels),)
            or any(a.dtype != np.float64 or not np.isfinite(a).all() for a in arrays.values())
        ):
            raise ValueError("invalid numeric tensor contract")
        obj.coefficients, obj.intercept = arrays["coefficients"], arrays["intercept"]
        obj.threshold, obj.margin = manifest["threshold"], manifest["margin"]
        if any(
            type(x) not in (int, float) or not np.isfinite(x) or not 0 <= x <= 1 for x in (obj.threshold, obj.margin)
        ):
            raise ValueError("invalid acceptance policy")
        obj.language_policy = manifest.get("language_policy", {})
        if set(obj.language_policy) - {"en", "zh"} or any(
            set(p) != {"threshold", "margin"}
            or any(type(x) not in (int, float) or not np.isfinite(x) or not 0 <= x <= 1 for x in p.values())
            for p in obj.language_policy.values()
        ):
            raise ValueError("invalid language policy")
        obj.receipt = manifest["training_receipt"]
        return obj
