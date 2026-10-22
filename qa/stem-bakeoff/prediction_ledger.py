"""Bounded prediction evidence and preregistered research screens, never authority.

Rows and pair blocks must come from an independently verified data plan. Hashes
bind supplied evidence; they do not authenticate split custody or independence.
Cluster bootstrap intervals are empirical research diagnostics, not a
distribution-free guarantee (zero observed errors can give a degenerate bound).
"""

from dataclasses import asdict, dataclass
import hashlib
import io
import json
import math
from pathlib import Path
import re
import stat
import zipfile

import numpy as np

MAX_ROWS, MAX_BYTES = 8192, 64 * 1024 * 1024
ARRAYS = ("logits", "labels", "probabilities", "prediction", "accepted",
          "source_ids", "image_group_ids", "pair_block_ids")
HEX = re.compile(r"[0-9a-f]{64}\Z")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class LedgerIdentityV1:
    encoder_sha256: str
    preprocess_sha256: str
    head_sha256: str
    data_sha256: str
    plan_sha256: str

    def validate(self):
        if any(type(v) is not str or HEX.fullmatch(v) is None for v in asdict(self).values()):
            raise ValueError("complete Encoder/Head/data/plan SHA256 identity required")


@dataclass(frozen=True)
class ResearchQualificationV1:
    min_rows: int = 128
    min_image_groups: int = 64
    min_pair_blocks: int = 64
    min_balanced_accuracy: float = 0.70
    min_positive_recall: float = 0.60
    confidence_threshold: float = 0.70
    min_coverage: float = 0.50
    min_accepted: int = 64
    max_selective_risk: float = 0.20
    max_selective_risk_upper: float = 0.30
    bootstrap_replicates: int = 2000
    bootstrap_seed: int = 20261022
    confidence_level: float = 0.95
    min_joint_gain: float = 0.10
    min_intervention_drop: float = 0.10
    require_positive_gain_lower_bound: bool = True

    def validate(self):
        ints = ((self.min_rows, 1, MAX_ROWS), (self.min_image_groups, 1, MAX_ROWS),
                (self.min_pair_blocks, 2, MAX_ROWS), (self.min_accepted, 1, MAX_ROWS),
                (self.bootstrap_replicates, 2000, 10000), (self.bootstrap_seed, 0, 2**32 - 1))
        if (any(type(x) is not int or not lo <= x <= hi for x, lo, hi in ints)
                or self.confidence_threshold != 0.7 or self.confidence_level != 0.95
                or type(self.require_positive_gain_lower_bound) is not bool):
            raise ValueError("invalid preregistered research limits")
        for key, value in asdict(self).items():
            if key.startswith(("min_", "max_")) and key not in (
                    "min_rows", "min_image_groups", "min_pair_blocks", "min_accepted"):
                if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError("invalid research metric threshold")


def _numpy(value):
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    return np.asarray(value)


def _ids(values, rows):
    if (not isinstance(values, (list, tuple, np.ndarray)) or len(values) != rows
            or any(not isinstance(x, (str, int, np.str_, np.integer)) or isinstance(x, bool) for x in values)):
        raise ValueError("one explicit string/integer identity per row required")
    strings = [str(x) for x in values]
    if any(not x or len(x) > 256 for x in strings):
        raise ValueError("row identities exceed limits")
    return np.asarray(strings, dtype=str)


def _probabilities(logits, temperature):
    scaled = logits / temperature
    centered = scaled - scaled.max(axis=1, keepdims=True)
    log_probs = centered - np.log(np.exp(centered).sum(axis=1, keepdims=True))
    return np.exp(log_probs), log_probs


def _digest(metadata, arrays):
    digest = hashlib.sha256(canonical(metadata))
    for name in ARRAYS:
        value = arrays[name]
        digest.update(canonical([name, str(value.dtype), list(value.shape)]))
        digest.update(value.tobytes())
    return digest.hexdigest()


def average_precision(labels, scores):
    """Stepwise PR area: process an entire score tie before updating precision."""
    positives = int(labels.sum())
    if not positives:
        return None
    order = np.argsort(-scores, kind="stable")
    sorted_scores, hits = scores[order], labels[order]
    ends = np.r_[np.flatnonzero(sorted_scores[1:] != sorted_scores[:-1]), len(hits) - 1]
    tp = np.cumsum(hits)[ends]
    return float(np.sum(np.diff(np.r_[0, tp]) / positives * tp / (ends + 1)))


def binomial_risk_upper(errors, accepted, alpha=0.05):
    """One-sided Clopper-Pearson bound; diagnostic only for correlated rows."""
    if accepted == 0:
        return None
    if errors == accepted:
        return 1.0
    if errors == 0:
        return -math.expm1(math.log(alpha) / accepted)
    k = np.arange(errors + 1)
    comb = np.array([math.lgamma(accepted + 1) - math.lgamma(int(j) + 1)
                     - math.lgamma(accepted - int(j) + 1) for j in k])
    low, high = errors / accepted, 1.0
    for _ in range(60):
        p = (low + high) / 2
        terms = comb + k * math.log(p) + (accepted - k) * math.log1p(-p)
        top = terms.max()
        cdf = float(np.exp(terms - top).sum() * math.exp(top))
        if cdf > alpha:
            low = p
        else:
            high = p
    return (low + high) / 2


class PredictionLedgerV1:
    @classmethod
    def from_logits(cls, *, logits, labels, source_ids, image_group_ids, pair_block_ids,
                    identity, split, arm, intervention="paired", temperature=1.0,
                    confidence_threshold=0.7):
        if type(identity) is not LedgerIdentityV1:
            raise ValueError("typed prediction identity required")
        identity.validate()
        if (any(type(x) is not str or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", x)
                for x in (split, arm, intervention)) or confidence_threshold != 0.7
                or type(temperature) not in (float, int) or not math.isfinite(temperature)
                or not 0.01 <= temperature <= 100):
            raise ValueError("invalid split/arm/intervention/temperature/fixed threshold")
        logits, labels = _numpy(logits), _numpy(labels)
        if (logits.ndim != 2 or logits.shape[1] != 2 or not 1 <= len(logits) <= MAX_ROWS
                or logits.dtype.kind not in "fiu" or labels.shape != (len(logits),)
                or labels.dtype.kind not in "iu" or not np.isin(labels, (0, 1)).all()
                or not np.isfinite(logits).all() or np.abs(logits.astype(np.float64)).max() > 1e6):
            raise ValueError("bounded finite binary logits and integer labels required")
        logits = np.array(logits, dtype=np.float64, copy=True)
        probabilities, _ = _probabilities(logits, temperature)
        arrays = {"logits": logits, "labels": labels.astype(np.int64, copy=True),
            "probabilities": probabilities, "prediction": probabilities.argmax(axis=1),
            "accepted": probabilities.max(axis=1) >= confidence_threshold,
            "source_ids": _ids(source_ids, len(logits)),
            "image_group_ids": _ids(image_group_ids, len(logits)),
            "pair_block_ids": _ids(pair_block_ids, len(logits))}
        if len(set(arrays["source_ids"])) != len(logits):
            raise ValueError("duplicate source identity in prediction ledger")
        groups = {}
        for group, block in zip(arrays["image_group_ids"], arrays["pair_block_ids"]):
            if group in groups and groups[group] != block:
                raise ValueError("an image group crosses independent pair blocks")
            groups[group] = block
        if sum(x.nbytes for x in arrays.values()) > MAX_BYTES:
            raise ValueError("prediction tensors exceed byte budget")
        obj = cls()
        obj.identity = identity
        obj._metadata = {"schema": "hepta.prediction-ledger.v1", "identity": asdict(identity),
            "split": split, "arm": arm, "intervention": intervention,
            "temperature": float(temperature), "confidence_threshold": confidence_threshold}
        obj._arrays = arrays
        obj.ledger_sha256 = _digest(obj._metadata, arrays)
        for value in arrays.values():
            value.setflags(write=False)
        return obj

    def verify(self):
        if asdict(self.identity) != self._metadata["identity"] or _digest(self._metadata, self._arrays) != self.ledger_sha256:
            raise ValueError("immutable prediction ledger bytes changed")

    def rows(self):
        self.verify()
        return [{"source_id": str(self._arrays["source_ids"][i]),
            "image_group_id": str(self._arrays["image_group_ids"][i]),
            "pair_block_id": str(self._arrays["pair_block_ids"][i]),
            "label": int(self._arrays["labels"][i]),
            **{key: self._arrays[key][i].tolist() for key in ("logits", "probabilities", "prediction", "accepted")},
            **self._metadata, "identity": asdict(self.identity)} for i in range(len(self._arrays["labels"]))]

    def metrics(self):
        self.verify()
        a = self._arrays
        y, pred, accepted, probs = (a[k] for k in ("labels", "prediction", "accepted", "probabilities"))
        confusion = np.bincount(2 * y + pred, minlength=4).reshape(2, 2)
        tn, fp, fn, tp = confusion.ravel()
        recall = float(tp / (tp + fn)) if tp + fn else None
        specificity = float(tn / (tn + fp)) if tn + fp else None
        count, errors = int(accepted.sum()), int(((pred != y) & accepted).sum())
        confidence, correct = probs.max(axis=1), pred == y
        bins, ece = np.minimum((confidence * 10).astype(int), 9), 0.0
        for b in range(10):
            mask = bins == b
            if mask.any():
                ece += float(mask.mean() * abs(confidence[mask].mean() - correct[mask].mean()))
        _, log_probs = _probabilities(a["logits"], self._metadata["temperature"])
        priors = np.bincount(y, minlength=2) / len(y)
        return {"rows": len(y), "image_groups": len(set(a["image_group_ids"])),
            "pair_blocks": len(set(a["pair_block_ids"])), "confusion_tn_fp_fn_tp": confusion.ravel().tolist(),
            "accuracy": float(correct.mean()), "balanced_accuracy":
            (recall + specificity) / 2 if recall is not None and specificity is not None else None,
            "positive_recall": recall, "negative_recall": specificity,
            "average_precision": average_precision(y, probs[:, 1]),
            "nll": float(-log_probs[np.arange(len(y)), y].mean()),
            "brier_multiclass_sum": float(((probs - np.eye(2)[y]) ** 2).sum(axis=1).mean()),
            "ece10_equal_width": ece, "confidence_threshold": self._metadata["confidence_threshold"],
            "coverage": count / len(y), "accepted_count": count, "accepted_error_count": errors,
            "selective_risk": errors / count if count else None,
            "selective_accuracy": 1 - errors / count if count else None,
            "risk_upper_95_binomial_diagnostic": binomial_risk_upper(errors, count),
            "majority_accuracy": float(priors.max()), "chance_accuracy": 0.5,
            "empirical_prior_nll": float(-sum(p * math.log(p) for p in priors if p))}


def _block_counts(ledger):
    ledger.verify()
    a = ledger._arrays
    names, index = np.unique(a["pair_block_ids"], return_inverse=True)
    y, pred, accepted = (a[k] for k in ("labels", "prediction", "accepted"))
    values = np.stack((y == 1, y == 0, (y == 1) & (pred == 1),
        (y == 0) & (pred == 0), accepted, accepted & (pred != y)), axis=1).astype(float)
    counts = np.zeros((len(names), 6))
    np.add.at(counts, index, values)
    return names, counts


def _from_counts(counts):
    pos, neg, tp, tn, accepted, errors = counts.T
    ratio = lambda x, n, missing: np.divide(x, n, out=np.full_like(x, missing), where=n > 0)
    return {"balanced_accuracy": (ratio(tp, pos, 0) + ratio(tn, neg, 0)) / 2,
            "positive_recall": ratio(tp, pos, 0), "accuracy": ratio(tp + tn, pos + neg, 0),
            "coverage": ratio(accepted, pos + neg, 0), "selective_risk": ratio(errors, accepted, 1)}


def _bootstrap(ledger, qualification):
    qualification.validate()
    names, counts = _block_counts(ledger)
    if len(names) < 2:
        raise ValueError("at least two independent pair blocks required")
    rng = np.random.Generator(np.random.PCG64(qualification.bootstrap_seed))
    parts = []
    for start in range(0, qualification.bootstrap_replicates, 32):
        sample = rng.integers(0, len(names), size=(min(32, qualification.bootstrap_replicates - start), len(names)))
        parts.append(counts[sample].sum(axis=1))
    return _from_counts(np.concatenate(parts))


def cluster_intervals(ledger, qualification=None):
    q = qualification or ResearchQualificationV1()
    samples = _bootstrap(ledger, q)
    return {"method": "pair-block-percentile-bootstrap", "replicates": q.bootstrap_replicates,
        "seed": q.bootstrap_seed, "confidence_level": q.confidence_level,
        "zero_accepted_resample_risk": 1.0, "independence_authenticated": False,
        "distribution_free_guarantee": False,
        "bounds": {key: {"lower_one_sided_95": float(np.quantile(value, 0.05)),
                          "upper_one_sided_95": float(np.quantile(value, 0.95))}
                   for key, value in samples.items()}}


def paired_intervention_summary(reference, comparison, *, comparison_kind="intervention", qualification=None):
    reference.verify()
    comparison.verify()
    q = qualification or ResearchQualificationV1()
    fields = ("encoder_sha256", "preprocess_sha256", "data_sha256", "plan_sha256")
    if (comparison_kind not in ("intervention", "modality", "head")
            or any(getattr(reference.identity, k) != getattr(comparison.identity, k) for k in fields)
            or reference._metadata["split"] != comparison._metadata["split"]
            or (comparison_kind == "intervention" and
                (reference.identity.head_sha256 != comparison.identity.head_sha256
                 or reference._metadata["temperature"] != comparison._metadata["temperature"]))):
        raise ValueError("unbound paired comparison")
    left, right = reference._arrays, comparison._arrays
    lookup = {str(value): i for i, value in enumerate(right["source_ids"])}
    if set(lookup) != set(left["source_ids"]):
        raise ValueError("paired source IDs differ")
    indices = np.array([lookup[str(value)] for value in left["source_ids"]])
    if any(not np.array_equal(left[key], right[key][indices]) for key in ("labels", "image_group_ids", "pair_block_ids")):
        raise ValueError("paired labels or source groups differ")
    a, b = reference.metrics(), comparison.metrics()
    sa, sb = _bootstrap(reference, q), _bootstrap(comparison, q)
    deltas = {k: {"reference_minus_comparison": a[k] - b[k] if a[k] is not None and b[k] is not None else None,
                  "lower_one_sided_95": float(np.quantile(sa[k] - sb[k], 0.05)) if a[k] is not None and b[k] is not None else None,
                  "upper_one_sided_95": float(np.quantile(sa[k] - sb[k], 0.95)) if a[k] is not None and b[k] is not None else None} for k in sa}
    ca, cb = left["prediction"] == left["labels"], right["prediction"][indices] == left["labels"]
    return {"reference_ledger_sha256": reference.ledger_sha256, "comparison_ledger_sha256": comparison.ledger_sha256,
        "comparison_kind": comparison_kind, "paired_rows": len(ca), "pair_blocks": a["pair_blocks"],
        "reference_only_correct": int((ca & ~cb).sum()), "comparison_only_correct": int((~ca & cb).sum()),
        "both_correct": int((ca & cb).sum()), "both_wrong": int((~ca & ~cb).sum()),
        "nll_comparison_minus_reference": b["nll"] - a["nll"], "paired_deltas": deltas,
        "bootstrap_replicates": q.bootstrap_replicates, "bootstrap_seed": q.bootstrap_seed,
        "authority": "DENY_ALL", "production_activation_allowed": False}


def assess_research_qualification(ledger, plan):
    ledger.verify()
    if sha(canonical(plan)) != ledger.identity.plan_sha256:
        raise ValueError("qualification plan does not match ledger's prior plan SHA")
    q = ResearchQualificationV1(**plan["research_qualification"])
    q.validate()
    if ledger._metadata["split"] != "test" or ledger._metadata["intervention"] != "paired":
        raise ValueError("research qualification scores the untouched paired test arm only")
    m = ledger.metrics()
    ci = cluster_intervals(ledger, q) if m["pair_blocks"] >= 2 else None
    requirements = {"rows": (m["rows"], q.min_rows), "image_groups": (m["image_groups"], q.min_image_groups),
        "pair_blocks": (m["pair_blocks"], q.min_pair_blocks), "balanced_accuracy": (m["balanced_accuracy"], q.min_balanced_accuracy),
        "positive_recall": (m["positive_recall"], q.min_positive_recall), "coverage": (m["coverage"], q.min_coverage),
        "accepted_count": (m["accepted_count"], q.min_accepted)}
    checks = {k: value is not None and value >= limit for k, (value, limit) in requirements.items()}
    checks["selective_risk"] = m["selective_risk"] is not None and m["selective_risk"] <= q.max_selective_risk
    checks["cluster_risk_upper"] = ci is not None and ci["bounds"]["selective_risk"]["upper_one_sided_95"] <= q.max_selective_risk_upper
    insufficient = any(not checks[k] for k in ("rows", "image_groups", "pair_blocks", "accepted_count"))
    return {"status": "INSUFFICIENT" if insufficient else "PASS_RESEARCH_SCREEN" if all(checks.values()) else "FAIL_RESEARCH_SCREEN",
        "checks": checks, "metrics": m, "cluster_intervals": ci, "plan_sha256": ledger.identity.plan_sha256,
        "multimodal_gain_qualified": False, "source_independence_authenticated": False,
        "authority": "DENY_ALL", "mode": "SHADOW_ONLY", "production_activation_allowed": False}


def assess_multimodal_research(joint, *, unimodal, interventions, plan):
    """Require matched controls and paired sensitivities in addition to one arm."""
    if set(unimodal) != {"text_only", "image_only"} or set(interventions) != {
            "shuffled_image", "missing_image", "missing_text"}:
        raise ValueError("both unimodal controls and three fixed interventions required")
    screen = assess_research_qualification(joint, plan)
    q = ResearchQualificationV1(**plan["research_qualification"])
    if joint.metrics()["balanced_accuracy"] is None:
        return {"status": "INSUFFICIENT", "joint_screen": screen,
                "blockers": ["binary test requires both classes"],
                "multimodal_gain_research_screen_passed": False,
                "production_activation_allowed": False, "authority": "DENY_ALL", "mode": "SHADOW_ONLY"}
    controls = {k: paired_intervention_summary(joint, v, comparison_kind="modality", qualification=q)
                for k, v in unimodal.items()}
    changes = {k: paired_intervention_summary(joint, v, qualification=q)
               for k, v in interventions.items()}
    if (any(v._metadata["intervention"] != "paired" for v in unimodal.values())
            or any(v._metadata["intervention"] != k for k, v in interventions.items())):
        raise ValueError("intervention ledgers are not bound to declared conditions")
    joint_ba = joint.metrics()["balanced_accuracy"]
    best_ba = max(v.metrics()["balanced_accuracy"] for v in unimodal.values())
    resampled_best = np.maximum(*[_bootstrap(v, q)["balanced_accuracy"] for v in unimodal.values()])
    gain_lower = float(np.quantile(_bootstrap(joint, q)["balanced_accuracy"] - resampled_best, 0.05))
    gain = joint_ba - best_ba
    checks = {"joint_arm_screen": screen["status"] == "PASS_RESEARCH_SCREEN",
              "gain_vs_best_unimodal": gain >= q.min_joint_gain,
              "paired_gain_lower_positive": not q.require_positive_gain_lower_bound or gain_lower > 0}
    for key, result in changes.items():
        delta = result["paired_deltas"]["balanced_accuracy"]
        checks[key + "_drop"] = delta["reference_minus_comparison"] >= q.min_intervention_drop
        checks[key + "_lower_positive"] = not q.require_positive_gain_lower_bound or delta["lower_one_sided_95"] > 0
    return {"status": "PASS_RESEARCH_SCREEN" if all(checks.values()) else "FAIL_RESEARCH_SCREEN",
        "checks": checks, "joint_screen": screen, "modality_comparisons": controls,
        "paired_interventions": changes, "gain_vs_best_unimodal": gain,
        "gain_lower_one_sided_95": gain_lower,
        "shuffled_original_labels_are_sensitivity_only": True,
        "multimodal_gain_research_screen_passed": all(checks.values()),
        "production_activation_allowed": False, "authority": "DENY_ALL", "mode": "SHADOW_ONLY"}


def save_prediction_ledger(ledger, directory):
    ledger.verify()
    stream = io.BytesIO()
    np.savez(stream, **ledger._arrays)
    payload = stream.getvalue()
    if len(payload) > MAX_BYTES:
        raise ValueError("serialized ledger exceeds byte budget")
    manifest = {"metadata": ledger._metadata, "ledger_sha256": ledger.ledger_sha256,
                "arrays_file": "predictions.npz", "arrays_sha256": sha(payload)}
    raw = canonical(manifest)
    path = Path(directory)
    path.mkdir(parents=False, exist_ok=False, mode=0o700)
    (path / "predictions.npz").write_bytes(payload)
    (path / "manifest.json").write_bytes(raw)
    return {"directory": str(path), "manifest_sha256": sha(raw), "arrays_sha256": sha(payload),
            "ledger_sha256": ledger.ledger_sha256}


def load_prediction_ledger(directory, *, expected_manifest_sha256, expected_identity):
    path = Path(directory)
    if (path.is_symlink() or not path.is_dir() or type(expected_manifest_sha256) is not str
            or HEX.fullmatch(expected_manifest_sha256) is None):
        raise ValueError("real directory and external manifest SHA256 required")
    payloads = {}
    for name, limit in (("manifest.json", 32768), ("predictions.npz", MAX_BYTES)):
        file = path / name
        info = file.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
            raise ValueError("linked, irregular or oversized ledger artifact")
        payloads[name] = file.read_bytes()
        if len(payloads[name]) > limit:
            raise ValueError("ledger grew during bounded read")
    if sha(payloads["manifest.json"]) != expected_manifest_sha256:
        raise ValueError("retained ledger manifest hash mismatch")
    manifest = json.loads(payloads["manifest.json"])
    meta = manifest["metadata"]
    identity = LedgerIdentityV1(**meta["identity"])
    if (identity != expected_identity or manifest["arrays_file"] != "predictions.npz"
            or sha(payloads["predictions.npz"]) != manifest["arrays_sha256"]):
        raise ValueError("ledger identity or tensor bytes mismatch")
    with zipfile.ZipFile(io.BytesIO(payloads["predictions.npz"])) as zipped:
        entries = zipped.infolist()
        if (len(entries) != len(ARRAYS) or {x.filename for x in entries} != {x + ".npy" for x in ARRAYS}
                or sum(x.file_size for x in entries) > MAX_BYTES
                or any(x.compress_type != zipfile.ZIP_STORED for x in entries)):
            raise ValueError("unexpected or oversized NPZ tensor entries")
        for entry in entries:
            key = entry.filename[:-4]
            with zipped.open(entry) as stream:
                if np.lib.format.read_magic(stream) != (1, 0):
                    raise ValueError("unexpected NPY header version")
                shape, fortran, dtype = np.lib.format.read_array_header_1_0(stream)
                wanted = 2 if key in ("logits", "probabilities") else 1
                expected_dtype = np.float64 if wanted == 2 else np.bool_ if key == "accepted" else np.int64
                strings = key.endswith("_ids")
                if (len(shape) != wanted or not 1 <= shape[0] <= MAX_ROWS
                        or (wanted == 2 and shape[1] != 2) or fortran or dtype.hasobject
                        or (strings and (dtype.kind != "U" or not 0 < dtype.itemsize <= 1024))
                        or (not strings and dtype != expected_dtype)
                        or stream.tell() + math.prod(shape) * dtype.itemsize != entry.file_size):
                    raise ValueError("invalid, oversized or truncated NPY tensor header")
    with np.load(io.BytesIO(payloads["predictions.npz"]), allow_pickle=False) as archive:
        arrays = {key: archive[key] for key in ARRAYS}
    result = PredictionLedgerV1.from_logits(**{key: arrays[key] for key in
        ("logits", "labels", "source_ids", "image_group_ids", "pair_block_ids")},
        identity=identity, **{key: meta[key] for key in ("split", "arm", "intervention", "temperature", "confidence_threshold")})
    if (meta != result._metadata or result.ledger_sha256 != manifest["ledger_sha256"]
            or any(not np.array_equal(arrays[key], result._arrays[key]) for key in ARRAYS)):
        raise ValueError("stored derived probabilities/predictions or ledger digest disagree")
    return result
