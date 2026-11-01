"""Audit and summarize a frozen five-task, five-arm, three-seed campaign.

This script does not train, choose checkpoints, or load torch pickles.  It reads
the final prediction archives only when invoked.  Bootstrap sampling units are
whole episodes, or whole actors for AVT, with the same draws in every seed and
arm.  Use --self-test for a small fabricated-data check without reading a run.
"""

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess

import numpy as np


TASKS = ("dynamics", "mqar", "selective", "binding", "avt")
ARMS = ("flow", "diagonal", "gru", "snn", "transformer")
SEEDS = (17, 29, 43)
PRIMARY = ("flow", "diagonal")
HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
NOTES = [
    "Only three independent training seeds: hierarchical bootstrap intervals have low power and uncertain tail coverage.",
    "The fixed primary contrast is flow minus diagonal. Other arm contrasts, stresses, and interventions are exploratory; intervals are not multiplicity adjusted.",
    "Seed draws are paired across arms, and each bootstrap replicate uses the same resampled episodes or actors in every selected seed. Queries are never treated as independent replicates.",
    "Accuracy and cross entropy use archive sample weights. All-query correctness is the runner's unweighted mean over episodes; weighted all-query correctness is reported separately.",
    "For AVT, each episode has one query: unweighted all-query correctness equals unweighted accuracy. Always-negative gives 3/4 unweighted accuracy but 1/2 weighted accuracy. The weighted single-modality and two-modality Bayes oracles are 1/2 and 5/6.",
    "AVT uses two sentences and fixed non-pretrained causal-prefix features; it does not validate a foundation model, general language generation, or all-modal alignment.",
    "Synthetic content irregular stress redraws time from the same distribution. Dynamics irregular stress changes physical time and therefore can change its ground truth.",
    "Missing-observation world labels are retained. In the three synthetic content tasks, target-visible versus target-missing strata distinguish state evolution errors from information deletion; that mask is evaluation-only. Dynamics has no such target-availability mask.",
    "Flow no_marks and factorized_content are interventions on a trained checkpoint, not retrained ablations or proofs of causal necessity. No query-swap experiment is implemented.",
    "Models share information and training steps, but parameter counts and actual compute are unequal. This is not a matched-FLOP or matched-wall-time superiority test.",
    "Inference timing is a full-sequence CPU batch on a shared host, not batch-one latency, an incremental streaming kernel, GPU performance, or measured energy.",
    "Fit totals include their own training and evaluation costs and are counted once. Outer process receipts and feature preparation are separate accounting views, not quantities to add blindly to fit totals.",
    "Process peak RSS is a process-lifetime high-water mark, not an isolated per-fit memory measurement. Persistent state excludes training activations, optimizer state, and temporary kernels.",
    "Finite CTMC reference kernels and task-trained boundaries do not establish the full He-Xiong equity model, optimal stopping, a deep boundary-communicating network, or independent call/put force channels.",
]


def sha256(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def read_json(path):
    with Path(path).open() as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def fingerprint(*arrays):
    value = hashlib.sha256()
    for array in arrays:
        if array is None:
            value.update(b"none\n")
        else:
            array = np.asarray(array)
            value.update(str(array.dtype).encode() + repr(array.shape).encode())
            value.update(np.ascontiguousarray(array).tobytes())
    return value.hexdigest()


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and np.isfinite(value)


def distribution(values):
    values = [float(x) for x in values if x is not None and finite_number(x)]
    return dict(n=len(values), mean=float(np.mean(values)) if values else None,
                sd=float(np.std(values, ddof=1)) if len(values) > 1 else None,
                min=min(values) if values else None, max=max(values) if values else None,
                values=values)


class Audit:
    def __init__(self):
        self.errors, self.warnings = [], []

    def error(self, code, message, path=None):
        self.errors.append(dict(code=code, message=str(message), path=str(path) if path else None))

    def warn(self, code, message, path=None):
        row = dict(code=code, message=str(message), path=str(path) if path else None)
        if row not in self.warnings:
            self.warnings.append(row)

    def check_hash(self, path, expected, code):
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            self.error(code, "Missing or invalid declared SHA-256", path)
            return None
        if not Path(path).is_file():
            self.error(code, "Missing artifact", path)
            return None
        actual = sha256(path)
        if actual != expected:
            self.error(code, f"SHA-256 mismatch: expected {expected}, observed {actual}", path)
        return actual


@dataclass
class EpisodeStats:
    # All arrays have one row per episode, never one independent row per query.
    columns: dict
    scores: dict
    identity: str
    actor: object = None
    sample_id: object = None


def episode_stats(logits, y, weight, actor=None, sample_id=None, available=None):
    logits, y, weight = np.asarray(logits), np.asarray(y), np.asarray(weight)
    if logits.ndim != 3 or y.shape != logits.shape[:2] or weight.shape != y.shape:
        raise ValueError("Expected logits[N,T,C], y[N,T], weight[N,T]")
    if y.dtype.kind not in "iu" or not np.isfinite(logits).all() or not np.isfinite(weight).all():
        raise ValueError("Nonfinite predictions/weights or noninteger labels")
    valid = y >= 0
    if (weight < 0).any() or (weight[~valid] != 0).any() or (weight[valid] <= 0).any():
        raise ValueError("Weights must be positive exactly at labeled queries")
    if not valid.any(1).all() or (y[valid] >= logits.shape[-1]).any() or (y[~valid] != -100).any():
        raise ValueError("Empty-query episode or label outside class range")
    if actor is not None and np.asarray(actor).shape != (len(y),):
        raise ValueError("actor must have one entry per episode")
    if sample_id is not None:
        sample_id = np.asarray(sample_id)
        if sample_id.shape != (len(y),) or len(np.unique(sample_id)) != len(y):
            raise ValueError("sample_id must uniquely identify episodes")
    correct = (logits.argmax(-1) == y) & valid
    logp = logits.astype(np.float64) - np.logaddexp.reduce(logits.astype(np.float64), axis=-1, keepdims=True)
    ce = -np.take_along_axis(logp, np.maximum(y, 0)[..., None], axis=-1)[..., 0]
    count, total = valid.sum(1).astype(float), weight.sum(1).astype(float)
    all_correct = (correct | ~valid).all(1).astype(float)
    episode_weight = total / count
    columns = dict(correct=(correct * weight).sum(1), weight=total,
                   ce=(ce * weight).sum(1), all_correct=all_correct,
                   episodes=np.ones(len(y)), unweighted_correct=correct.sum(1).astype(float),
                   queries=count, weighted_all_correct=all_correct * episode_weight,
                   episode_weight=episode_weight)
    scores = dict(accuracy=float(columns["correct"].sum() / total.sum()),
                  cross_entropy=float(columns["ce"].sum() / total.sum()),
                  all_queries_correct=float(all_correct.mean()),
                  unweighted_accuracy=float(correct.sum() / valid.sum()),
                  weighted_all_queries_correct=float((all_correct * episode_weight).sum() / episode_weight.sum()),
                  query_count=int(valid.sum()), episodes=len(y), total_sample_weight=float(total.sum()))
    if available is not None:
        available = np.asarray(available)
        if available.dtype.kind != "b" or available.shape != y.shape or available[~valid].any():
            raise ValueError("Invalid evaluation-only target_available mask")
        for name, select in (("visible_target", available & valid), ("missing_target", ~available & valid)):
            numerator = (correct * weight * select).sum(1)
            denominator = (weight * select).sum(1)
            columns[name + "_correct"], columns[name + "_weight"] = numerator, denominator
            scores[name + "_accuracy"] = float(numerator.sum() / denominator.sum()) if denominator.sum() else None
            scores[name + "_query_count"] = int(select.sum())
    return EpisodeStats(columns, scores, fingerprint(y, weight, actor, sample_id, available),
                        None if actor is None else np.asarray(actor), sample_id)


def check_recorded_scores(audit, recorded, stats, path, condition):
    for key in ("accuracy", "cross_entropy", "all_queries_correct", "query_count", "episodes",
                "visible_target_accuracy", "missing_target_accuracy"):
        if key not in stats.scores:
            continue
        expected, actual = recorded.get(key), stats.scores[key]
        if expected is None and actual is None:
            continue
        if not finite_number(expected) or actual is None or not np.isclose(expected, actual, atol=2e-6, rtol=2e-6):
            audit.error("metric_mismatch", f"{condition}/{key}: recorded={expected}, recomputed={actual}", path)


def expected_conditions(task, arm):
    stresses = (("base", "no_audio", "no_video", "no_text") if task == "avt" else
                (("base", "irregular", "missing", "resample") if task == "dynamics" else
                 ("base", "long_delay", "irregular", "missing", "resample")))
    names = ["dev__base"] + ["test__" + stress for stress in stresses]
    if arm == "flow":
        names += ["sensitivity__no_marks", "sensitivity__factorized_content"]
    return names


def load_predictions(path, task, arm, result, audit, evaluation_episodes):
    scores, recovery, resampling = {}, None, None
    with np.load(path, allow_pickle=False) as archive:
        base_logits, base_y = archive["test__base__logits"], archive["test__base__y"]
        for name in expected_conditions(task, arm):
            target = "test__base" if name.startswith("sensitivity__") else name
            logits = archive[name + "__logits"]
            get = lambda suffix: archive[target + "__" + suffix] if target + "__" + suffix in archive else None
            y, weight = get("y"), get("weight")
            actor, ids = get("actor"), get("sample_id")
            if task == "avt" and actor is None:
                raise ValueError("AVT actor identifiers are required for clustered inference")
            if task == "avt" and ids is None:
                audit.warn("pairing_without_sample_id", "AVT archive has no sample_id; only actor/label/weight order can be checked", path)
            stats = episode_stats(logits, y, weight, actor, ids, get("target_available"))
            expected_queries = 1 if task == "avt" else (8 if task == "dynamics" else 4)
            expected_classes = 2 if task == "avt" else (4 if task == "dynamics" else 8)
            if not (stats.columns["queries"] == expected_queries).all() or logits.shape[-1] != expected_classes:
                raise ValueError(f"Unexpected query/class count for {task}")
            if task != "avt" and len(y) != evaluation_episodes:
                raise ValueError("Evaluation episode count differs from the frozen protocol")
            if task == "avt":
                valid = y >= 0
                if not np.array_equal(weight[valid], np.where(y[valid] == 1, 3., 1.)):
                    raise ValueError("AVT labels/weights violate positive=3, negative=1 contract")
                for person in np.unique(actor):
                    selected = (actor == person)[:, None] & valid
                    positive = weight[selected & (y == 1)].sum()
                    negative = weight[selected & (y == 0)].sum()
                    if positive != negative:
                        raise ValueError("AVT weighted classes are not balanced within an actor")
            scores[name] = stats
            check_recorded_scores(audit, result.get("evaluations", {}).get(name, {}), stats, path, name)
            if name == "test__resample":
                if logits.shape[1] != 2 * base_logits.shape[1] or not np.array_equal(y[:, 1::2], base_y):
                    raise ValueError("Resample archive does not preserve original observation/label positions")
                maximum = float(np.max(np.abs(logits[:, 1::2] - base_logits)))
                declared = result["evaluations"][name].get("observed_logit_max_difference")
                if not finite_number(declared) or not np.isclose(maximum, declared, atol=1e-9, rtol=1e-6):
                    audit.error("resample_mismatch", f"Recorded {declared}, recomputed {maximum}", path)
                resampling = dict(max_abs_observed_logit_difference=maximum, tolerance=1e-4,
                                  passed=maximum <= 1e-4)
        if task == "avt" and set(scores["dev__base"].actor.tolist()) & set(scores["test__base"].actor.tolist()):
            raise ValueError("AVT actors overlap between dev and test")
        if task == "dynamics":
            correct = base_logits.argmax(-1) == base_y
            recovery = dict(first_after_jump=float(correct[:, 9].mean()),
                            later_after_jump=float(correct[:, [11, 13, 15]].mean()))
            recorded = result.get("evaluations", {}).get("recovery", {})
            for key, value in recovery.items():
                if not finite_number(recorded.get(key)) or not np.isclose(value, recorded[key], atol=1e-7):
                    audit.error("recovery_mismatch", key, path)
            forcing = recorded.get("forcing_only")
            if not finite_number(forcing) or not 0 <= forcing <= 1:
                audit.error("forcing_baseline_missing", "Missing valid forcing-only accuracy", path)
                forcing = None
            recovery["forcing_only"] = forcing
            recovery["forcing_only_source"] = "Runner's recorded data-side baseline; predictions archive does not contain forcing inputs"
    return scores, recovery, resampling


def paired_bootstrap(left, right, seeds, task, sampling_key, repetitions=2000, random_seed=20261031):
    """Resample seeds, then shared episode/actor clusters; return paired effects."""
    if len(seeds) != 3 or set(seeds) != set(SEEDS):
        raise ValueError("A comparison requires all three preregistered paired seeds")
    identities = [s.identity for s in left + right]
    if len(set(identities)) != 1:
        raise ValueError("Pairing requires identical ordered labels, weights, identities, and availability masks")
    n = len(left[0].columns["episodes"])
    if task == "avt":
        if left[0].actor is None:
            raise ValueError("AVT must bootstrap actors")
        clusters, index = np.unique(left[0].actor, return_inverse=True)
        unit = "actor"
    else:
        clusters, index, unit = np.arange(n), np.arange(n), "episode"
    count = len(clusters)
    metrics = {"accuracy_difference": ("correct", "weight"),
               "all_queries_correct_difference": ("all_correct", "episodes"),
               "weighted_all_queries_correct_difference": ("weighted_all_correct", "episode_weight"),
               "cross_entropy_difference": ("ce", "weight")}
    for name in ("visible_target", "missing_target"):
        if name + "_correct" in left[0].columns:
            metrics[name + "_accuracy_difference"] = (name + "_correct", name + "_weight")
    differences, denominators, output = {}, {}, {}
    for metric, (numerator, denominator) in metrics.items():
        den = np.bincount(index, weights=left[0].columns[denominator], minlength=count)
        if den.sum() == 0:
            output[metric] = None
            continue
        for item in left + right:
            if not np.array_equal(item.columns[denominator], left[0].columns[denominator]):
                raise ValueError("Paired denominator differs across seeds or arms")
        diff = np.stack([np.bincount(index, weights=a.columns[numerator] - b.columns[numerator], minlength=count)
                         for a, b in zip(left, right)])
        differences[metric], denominators[metric] = diff, den
        per_seed = diff.sum(1) / den.sum()
        output[metric] = dict(estimate=float(per_seed.mean()), per_seed=per_seed.tolist())
    # Hashing the sampling key makes this stable across Python processes. The key
    # excludes the comparator, so contrasts on one task/condition share draws.
    key = int.from_bytes(hashlib.sha256(sampling_key.encode()).digest()[:8], "little")
    rng = np.random.default_rng(np.random.SeedSequence([random_seed, key]))
    draws = {metric: np.empty(repetitions, np.float64) for metric in differences}
    for start in range(0, repetitions, 64):
        size = min(64, repetitions - start)
        seed_draw = rng.integers(0, len(seeds), (size, len(seeds)))
        seed_weights = np.stack([(seed_draw == i).sum(1) for i in range(len(seeds))], 1) / len(seeds)
        # Counts are equivalent to drawing 'count' clusters with replacement.
        cluster_weights = rng.multinomial(count, np.full(count, 1 / count), size=size)
        for metric, diff in differences.items():
            num = ((seed_weights @ diff) * cluster_weights).sum(1)
            den = cluster_weights @ denominators[metric]
            draws[metric][start:start + size] = np.divide(num, den, out=np.full(size, np.nan), where=den > 0)
    for metric, sample in draws.items():
        finite = sample[np.isfinite(sample)]
        output[metric].update(ci95=np.quantile(finite, [.025, .975]).tolist() if len(finite) else None,
                              valid_bootstrap_repetitions=int(len(finite)))
    return dict(seeds=list(seeds), independent_training_seeds=len(seeds),
                sampling_unit=unit, clusters=count, episodes=n, repetitions=repetitions,
                random_seed=random_seed, shared_cluster_draws_across_seeds=True,
                method="Paired hierarchical percentile bootstrap: seeds, then whole shared clusters",
                sign_convention="Left minus right; higher is better for accuracy/all-query, lower is better for cross entropy",
                interpretation="Low-power three-seed interval; no multiplicity adjustment", metrics=output)


def find_manifest(run, explicit, names):
    if explicit is not None:
        return Path(explicit)
    found = [run / name for name in names if (run / name).is_file()]
    if len(found) > 1:
        raise ValueError(f"Ambiguous manifests; pass the explicit CLI path: {found}")
    return found[0] if found else None


def verify_sources(protocol, commits, audit, source_manifest=None):
    before = len(audit.errors)
    hashes = protocol.get("source_hashes", {})
    if not hashes:
        audit.error("source_freeze_missing", "Protocol has no source_hashes")
    required = {str((HERE / name).relative_to(REPO)) for name in
                ("runner.py", "models.py", "marked_flow.py", "av_data.py", "synthetic_data.py", "dynamic_data.py")}
    required.add("experiments/hcsn_distributional_v2/distribution_kernel.py")
    if not required.issubset(hashes):
        audit.error("source_freeze_coverage", f"Missing frozen model/data sources: {sorted(required - set(hashes))}")
    result = dict(protocol_source_hashes=hashes, frozen_commits=sorted(commits), files=[])
    manifest = read_json(source_manifest) if source_manifest is not None else None
    if source_manifest is not None:
        result["manifest"] = dict(path=str(source_manifest), sha256=sha256(source_manifest))
        declared = manifest.get("source_hashes")
        if declared is not None and declared != hashes:
            audit.error("source_manifest_mismatch", "Source manifest differs from protocol", source_manifest)
        declared_commit = manifest.get("frozen_commit", manifest.get("commit"))
        if declared_commit is not None and commits != {declared_commit}:
            audit.error("source_commit_mismatch", "Manifest commit differs from fit commits", source_manifest)
    if len(commits) != 1:
        audit.error("source_commit_mismatch", f"Expected one frozen commit, found {sorted(commits)}")
    if any(not re.fullmatch(r"[0-9a-f]{40}", commit) for commit in commits):
        audit.error("invalid_frozen_commit", "A source commit must be a complete 40-character Git SHA")
    remote = manifest is not None and manifest.get("schema") == "hcsn.remote-source-verification.v1"
    remote_files = {}
    if remote:
        result["verification_method"] = manifest.get("method")
        result["repository"] = manifest.get("repository")
        result["tree"] = manifest.get("tree")
        result["local_git_object_available"] = manifest.get("local_git_object_available")
        result["verification_scope"] = "Saved official GitHub connector readback cross-checked against current bytes, Git blob SHA-1, and protocol SHA-256; analyzer makes no new network request"
        if manifest.get("method") != "GitHub connector readback":
            audit.error("remote_source_method", "Unexpected remote verification method", source_manifest)
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", str(manifest.get("repository", ""))):
            audit.error("remote_source_repository", "Invalid repository identity", source_manifest)
        if not re.fullmatch(r"[0-9a-f]{40}", str(manifest.get("tree", ""))):
            audit.error("remote_source_tree", "Invalid remote Git tree identity", source_manifest)
        files = manifest.get("files", [])
        for item in files:
            if not isinstance(item, dict) or item.get("path") in remote_files:
                audit.error("remote_source_files", "Duplicate or malformed source record", source_manifest)
                continue
            remote_files[item.get("path")] = item
        if set(remote_files) != set(hashes):
            audit.error("remote_source_coverage", "Remote source paths differ from protocol", source_manifest)
    else:
        result["verification_method"] = "Local Git commit blob readback"
    for relative, expected in sorted(hashes.items()):
        path = REPO / relative
        row = dict(path=relative, expected_sha256=expected, working_tree_matches=None, git_commit_matches={})
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
            audit.error("source_path", f"Unsafe source path {relative}")
            continue
        if path.is_file():
            row["working_tree_matches"] = sha256(path) == expected
            if not row["working_tree_matches"]:
                if remote:
                    audit.error("working_source_drift", "Current bytes differ from the remote frozen source receipt", path)
                else:
                    audit.warn("working_source_drift", "Current source differs; frozen Git version remains authoritative", path)
        elif remote:
            audit.error("working_source_missing", "Remote receipt requires the corresponding local frozen bytes", path)
        if remote:
            declared = remote_files.get(relative, {})
            contents = path.read_bytes() if path.is_file() else b""
            git_blob_sha = hashlib.sha1(b"blob " + str(len(contents)).encode() + b"\0" + contents).hexdigest()
            pinned_url = (f"https://api.github.com/repos/{manifest.get('repository')}/contents/"
                          f"{relative}?ref={manifest.get('commit')}")
            matches = (path.is_file() and row["working_tree_matches"] is True
                       and declared.get("sha256") == expected
                       and declared.get("git_blob_sha") == git_blob_sha
                       and declared.get("remote_blob_sha") == git_blob_sha
                       and declared.get("api_url") == pinned_url and declared.get("verified") is True)
            row.update(git_blob_sha=git_blob_sha, remote_blob_sha=declared.get("remote_blob_sha"),
                       api_url=declared.get("api_url"), remote_receipt_matches=matches)
            if not matches:
                audit.error("remote_source_blob_mismatch", "Remote/local Git blob or SHA-256 binding failed", path)
            result["files"].append(row)
            continue
        for commit in sorted(commits):
            if not re.fullmatch(r"[0-9a-f]{40}", commit):
                audit.error("invalid_frozen_commit", str(commit))
                continue
            try:
                completed = subprocess.run(["git", "-C", str(REPO), "show", f"{commit}:{relative}"],
                                           capture_output=True, timeout=20, check=False)
                matches = completed.returncode == 0 and hashlib.sha256(completed.stdout).hexdigest() == expected
            except (OSError, subprocess.TimeoutExpired):
                matches = False
            row["git_commit_matches"][commit] = matches
            if not matches:
                audit.error("frozen_git_source_mismatch", f"Cannot verify {commit}:{relative} against protocol", path)
        result["files"].append(row)
    result["verified"] = bool(hashes) and len(commits) == 1 and len(audit.errors) == before and all(
        row.get("remote_receipt_matches", False) if remote else
        (all(row["git_commit_matches"].values()) and bool(row["git_commit_matches"])) for row in result["files"])
    return result


def validate_fit(run, task, arm, seed, protocol, protocol_hash, candidate, candidate_hash, audit):
    key = f"{task}__{arm}__{seed}"
    directory, path = run / key, run / key / "result.json"
    result = read_json(path)
    if (result.get("task"), result.get("arm"), result.get("seed")) != (task, arm, seed) or result.get("status") != "completed":
        raise ValueError("Result identity/status does not match expected completed fit")
    if result.get("protocol_sha256") != protocol_hash:
        audit.error("protocol_hash", "Result uses a different protocol", path)
    audit.check_hash(directory / "checkpoint.pt", result.get("checkpoint_sha256"), "checkpoint_hash")
    audit.check_hash(directory / "predictions.npz", result.get("predictions_sha256"), "predictions_hash")
    training_path = directory / "training.json"
    training = read_json(training_path) if training_path.is_file() else None
    if training is not None:
        for name, expected in (("protocol_sha256", protocol_hash), ("frozen_commit", result.get("frozen_commit")),
                               ("checkpoint_sha256", result.get("checkpoint_sha256")), ("task", task),
                               ("arm", arm), ("seed", seed), ("status", "trained")):
            if training.get(name) != expected:
                audit.error("training_identity", f"Training receipt field mismatch: {name}", training_path)
        for name, filename in (("training_curve_sha256", "training_curve.npy"), ("loss_log_sha256", "losses.jsonl")):
            audit.check_hash(directory / filename, training.get(name), "training_artifact_hash")
        curve_path = directory / "training_curve.npy"
        if curve_path.is_file():
            curve = np.load(curve_path, allow_pickle=False)
            if (curve.shape != (protocol["steps"], 3) or not np.isfinite(curve).all()
                    or not np.array_equal(curve[:, 0], np.arange(protocol["steps"]))):
                audit.error("training_budget", "Training curve differs from the frozen step budget", curve_path)
        if training.get("training", {}).get("examples") != protocol["steps"] * protocol["batch_size"]:
            audit.error("training_budget", "Training examples differ from the frozen budget", training_path)
        if result.get("training") != training.get("training"):
            audit.error("training_cost_identity", "Evaluation changed the training cost receipt", path)
    if result.get("candidate_freeze_sha256") is not None or candidate is not None:
        if candidate is None or result.get("candidate_freeze_sha256") != candidate_hash:
            audit.error("candidate_freeze_hash", "Missing or different candidate freeze", path)
        else:
            if candidate.get("frozen_commit") != result.get("frozen_commit"):
                audit.error("candidate_source_commit", "Candidate and result frozen commits differ", path)
            declared = candidate.get("checkpoints", {}).get(key, {})
            if declared.get("checkpoint_sha256") != result.get("checkpoint_sha256"):
                audit.error("candidate_checkpoint", "Checkpoint is not the frozen candidate", path)
            if not training_path.is_file() or declared.get("training_receipt_sha256") != sha256(training_path):
                audit.error("candidate_training_receipt", "Candidate training receipt identity mismatch", path)
    elif training is not None:
        audit.error("candidate_freeze_missing", "Separate training/evaluation requires a candidate freeze", path)
    inference = result.get("inference", {})
    timings = inference.get("wall_seconds", [])
    if len(timings) != 9 or not all(finite_number(t) and t > 0 for t in timings):
        audit.error("inference_timing", "Expected nine positive measured batch timings", path)
    elif not np.isclose(np.median(timings), inference.get("median_seconds", -1), rtol=1e-6, atol=1e-9):
        audit.error("inference_timing", "Reported median does not match raw timings", path)
    return result


def fit_cost(result, audit, path):
    training, evaluation = result.get("training", {}), result.get("evaluation", {})
    cost = {}
    for clock in ("cpu", "wall"):
        field = clock + "_seconds"
        train, evaluate = training.get(field), evaluation.get(field)
        total = result.get("total_fit_" + field)
        if total is None and finite_number(train) and finite_number(evaluate):
            total = train + evaluate
        for name, value in (("training", train), ("evaluation", evaluate), ("total_fit", total)):
            if value is not None and (not finite_number(value) or value < 0):
                audit.error("invalid_cost", f"Invalid {name} {clock} seconds", path)
            cost[name + "_" + field] = float(value) if finite_number(value) else None
        if finite_number(total) and finite_number(train) and total + 1e-6 < train:
            audit.error("cost_scope", f"Fit total is smaller than training {clock} cost", path)
        if all(finite_number(v) for v in (total, train, evaluate)) and not np.isclose(total, train + evaluate, atol=.05, rtol=1e-4):
            audit.error("cost_scope", f"Separated train+evaluation differs from declared fit total ({clock})", path)
    cost["energy_joules"] = None
    return cost


def receipt_view(paths, kind, audit):
    """Independent accounting view; never added to the already inclusive fits."""
    files = []
    for supplied in paths:
        supplied = Path(supplied)
        if supplied.is_file():
            files.append(supplied)
        elif supplied.is_dir():
            directory = supplied / "preparation_receipts" if (supplied / "preparation_receipts").is_dir() else supplied
            files.extend(sorted(directory.glob("*.json")))
        else:
            audit.warn("receipt_missing", f"Missing {kind} receipt path", supplied)
    rows = []
    for path in sorted(set(p.resolve() for p in files)):
        try:
            raw = read_json(path)
            cpu, wall = raw.get("cpu_seconds", raw.get("total_cpu_seconds")), raw.get("wall_seconds")
            if cpu is None and all(finite_number(raw.get(k)) for k in ("user_cpu_seconds", "system_cpu_seconds")):
                cpu = raw["user_cpu_seconds"] + raw["system_cpu_seconds"]
            rows.append(dict(path=str(path), sha256=sha256(path),
                             cpu_seconds=float(cpu) if finite_number(cpu) else None,
                             wall_seconds=float(wall) if finite_number(wall) else None,
                             receipt=raw))
        except (ValueError, OSError) as error:
            audit.warn("receipt_unreadable", str(error), path)
    cpu_values = [r["cpu_seconds"] for r in rows if r["cpu_seconds"] is not None]
    wall_values = [r["wall_seconds"] for r in rows if r["wall_seconds"] is not None]
    return dict(kind=kind, receipts=rows,
                cpu_seconds_sum_of_explicit_fields=sum(cpu_values) if cpu_values else None,
                wall_seconds_sum_of_explicit_fields=sum(wall_values) if wall_values else None,
                available=bool(rows), energy_joules=None,
                accounting="Separate audit view. May contain nested/overlapping costs; not added to fit totals.")


def aggregate_fit_rows(rows):
    result = {}
    for task in TASKS:
        result[task] = {}
        for arm in ARMS:
            subset = [row for row in rows if row["task"] == task and row["arm"] == arm and row["integrity_valid"]]
            conditions = sorted({name for row in subset for name in row["metrics"]})
            aggregate = dict(seeds=[row["seed"] for row in subset], metrics={})
            for name in conditions:
                names = sorted({metric for row in subset for metric in row["metrics"].get(name, {})})
                aggregate["metrics"][name] = {metric: distribution([row["metrics"].get(name, {}).get(metric) for row in subset])
                                               for metric in names}
            for name in ("training_cpu_seconds", "training_wall_seconds", "evaluation_cpu_seconds", "evaluation_wall_seconds",
                         "total_fit_cpu_seconds", "total_fit_wall_seconds"):
                aggregate[name] = distribution([row["cost"].get(name) for row in subset])
            for name in ("batch_median_latency_seconds", "amortized_seconds_per_episode", "episodes_per_second",
                         "parameters", "persistent_state_scalars", "process_peak_rss_kib"):
                aggregate[name] = distribution([row.get(name) for row in subset])
            aggregate["state_note"] = "Conceptual persistent state; Transformer K/V estimate. Reference implementation is not an incremental cache benchmark."
            result[task][arm] = aggregate
    return result


def build_comparisons(statistics, audit, repetitions, random_seed):
    comparisons, sensitivities = [], []
    for task in TASKS:
        conditions = [name for name in expected_conditions(task, "diagonal") if name.startswith("test__")]
        for condition in conditions:
            for baseline in ARMS[1:]:
                keys = [(task, arm, seed, condition) for arm in ("flow", baseline) for seed in SEEDS]
                if not all(key in statistics for key in keys):
                    continue
                left = [statistics[task, "flow", seed, condition] for seed in SEEDS]
                right = [statistics[task, baseline, seed, condition] for seed in SEEDS]
                try:
                    row = paired_bootstrap(left, right, SEEDS, task, task + "/" + condition, repetitions, random_seed)
                    row.update(task=task, condition=condition, contrast="flow - " + baseline,
                               designation="primary" if baseline == "diagonal" and condition == "test__base" else "exploratory")
                    comparisons.append(row)
                except ValueError as error:
                    audit.error("comparison_pairing", f"{task}/{condition}/flow-{baseline}: {error}")
        for name in ("no_marks", "factorized_content"):
            keys = [(task, "flow", seed, condition) for condition in ("test__base", "sensitivity__" + name) for seed in SEEDS]
            if not all(key in statistics for key in keys):
                continue
            try:
                row = paired_bootstrap([statistics[task, "flow", seed, "test__base"] for seed in SEEDS],
                                       [statistics[task, "flow", seed, "sensitivity__" + name] for seed in SEEDS],
                                       SEEDS, task, task + "/test__base", repetitions, random_seed)
                row.update(task=task, contrast="full flow - " + name, designation="exploratory trained-checkpoint sensitivity")
                sensitivities.append(row)
            except ValueError as error:
                audit.error("sensitivity_pairing", f"{task}/{name}: {error}")
    return comparisons, sensitivities


def summarize(args):
    run, audit = args.run.resolve(), Audit()
    protocol_path = run / "PROTOCOL.json"
    protocol, protocol_hash = read_json(protocol_path), sha256(protocol_path)
    for name, expected in (("tasks", TASKS), ("arms", ARMS), ("seeds", SEEDS)):
        if set(protocol.get(name, [])) != set(expected):
            audit.error("protocol_design", f"Expected {name}={list(expected)}, found {protocol.get(name)}", protocol_path)
    candidate_path = find_manifest(run, args.candidate_freeze, (
        "CHECKPOINT_FREEZE__dynamics_mqar_selective_binding_avt.json",
        "CANDIDATE_FREEZE.json", "CANDIDATES.json", "CHECKPOINT_FREEZE.json"))
    candidate = read_json(candidate_path) if candidate_path else None
    candidate_hash = sha256(candidate_path) if candidate_path else None
    if candidate is not None:
        expected_keys = {f"{t}__{a}__{s}" for t in TASKS for a in ARMS for s in SEEDS}
        if set(candidate.get("checkpoints", {})) != expected_keys:
            audit.error("candidate_completeness", "Candidate freeze must contain exactly 75 expected checkpoints", candidate_path)
        if candidate.get("protocol_sha256", protocol_hash) != protocol_hash:
            audit.error("candidate_protocol", "Candidate protocol hash differs", candidate_path)
        for name, expected in (("tasks", TASKS), ("arms", ARMS), ("seeds", SEEDS)):
            if set(candidate.get(name, [])) != set(expected):
                audit.error("candidate_design", f"Candidate {name} do not match full frozen design", candidate_path)
    rows, statistics, missing, invalid, commits = [], {}, [], [], set()
    for task in TASKS:
        for arm in ARMS:
            for seed in SEEDS:
                key = f"{task}__{arm}__{seed}"
                path = run / key / "result.json"
                if not path.is_file():
                    missing.append(key)
                    continue
                before = len(audit.errors)
                try:
                    result = validate_fit(run, task, arm, seed, protocol, protocol_hash, candidate, candidate_hash, audit)
                    frozen = result.get("frozen_commit")
                    if isinstance(frozen, str):
                        commits.add(frozen)
                    else:
                        audit.error("frozen_commit_missing", key, path)
                    stats, recovery, resampling = load_predictions(path.parent / "predictions.npz", task, arm, result, audit,
                                                                  protocol["evaluation_episodes"])
                    cost = fit_cost(result, audit, path)
                    inference, shape = result.get("inference", {}), result.get("shape", {})
                    latency, batch = inference.get("median_seconds"), inference.get("batch_size")
                    row = dict(task=task, arm=arm, seed=seed, result_sha256=sha256(path),
                        checkpoint_sha256=result.get("checkpoint_sha256"), predictions_sha256=result.get("predictions_sha256"),
                        protocol_sha256=protocol_hash, candidate_freeze_sha256=result.get("candidate_freeze_sha256"),
                        cost=cost, metrics={name: item.scores for name, item in stats.items()},
                        batch_median_latency_seconds=latency,
                        amortized_seconds_per_episode=latency / batch if finite_number(latency) and finite_number(batch) and batch > 0 else None,
                        inference_batch_size=batch, inference_sequence_length=inference.get("sequence_length"),
                        inference_raw_batch_seconds=inference.get("wall_seconds"), episodes_per_second=inference.get("episodes_per_second"),
                        parameters=shape.get("parameters"), persistent_state_scalars=shape.get("persistent_state_scalars"),
                        shape=shape, recovery=recovery, resampling=resampling,
                        process_peak_rss_kib=result.get("process_peak_rss_kib"),
                        final_training_loss=result.get("final_training_loss"), data_identities=result.get("data_identities"),
                        integrity_valid=len(audit.errors) == before)
                    rows.append(row)
                    if row["integrity_valid"]:
                        for condition, item in stats.items():
                            statistics[task, arm, seed, condition] = item
                    else:
                        invalid.append(key)
                except (ValueError, KeyError, OSError, TypeError, IndexError) as error:
                    invalid.append(key)
                    audit.error("fit_unreadable", f"{type(error).__name__}: {error}", path)
    for key in missing:
        audit.error("fit_missing", key, run / key)
    source_manifest = find_manifest(run, args.source_freeze, ("REMOTE_SOURCE_VERIFICATION.json", "SOURCE_FREEZE.json", "SOURCE_MANIFEST.json"))
    sources = verify_sources(protocol, commits, audit, source_manifest)
    failures = []
    for path in sorted((run / "failures").glob("*.json")):
        try:
            failures.append(dict(path=str(path), sha256=sha256(path), **read_json(path)))
        except (ValueError, OSError) as error:
            audit.error("failure_receipt_unreadable", str(error), path)
    comparisons, sensitivities = build_comparisons(statistics, audit, args.repetitions, args.bootstrap_seed)
    aggregate = aggregate_fit_rows(rows)
    feature_paths = args.feature_prep or [path for path in (
        run.parent / "avt_prepare_trainval.receipt.json", run.parent / "avt_prepare_test.receipt.json") if path.is_file()]
    outer_paths = args.outer_receipt or [path for path in (
        run.parent / (run.name + "_train.receipt.json"), run.parent / (run.name + "_evaluate.receipt.json")) if path.is_file()]
    preparation = receipt_view(feature_paths, "feature preparation", audit)
    outer = receipt_view(outer_paths, "outer process", audit)
    totals = {name: sum(row["cost"][name] for row in rows if row["cost"][name] is not None)
              for name in ("training_cpu_seconds", "training_wall_seconds", "evaluation_cpu_seconds", "evaluation_wall_seconds",
                           "total_fit_cpu_seconds", "total_fit_wall_seconds")}
    totals["fit_cost_rows"] = len(rows)
    totals["fit_cost_complete"] = all(row["cost"]["total_fit_cpu_seconds"] is not None and
                                      row["cost"]["total_fit_wall_seconds"] is not None for row in rows) and len(rows) == 75
    totals["failure_attempt_cpu_seconds"] = sum(f["cpu_seconds"] for f in failures if finite_number(f.get("cpu_seconds")))
    totals["failure_attempt_wall_seconds"] = sum(f["wall_seconds"] for f in failures if finite_number(f.get("wall_seconds")))
    totals["failure_accounting"] = "Reported separately: failed evaluation attempts may already include costs represented by retained training receipts. Do not add without checking attempt scopes."
    totals["energy_joules"] = None
    expected = {f"{t}__{a}__{s}" for t in TASKS for a in ARMS for s in SEEDS}
    unexpected = sorted(path.parent.name for path in run.glob("*/result.json") if path.parent.name not in expected)
    if unexpected:
        audit.warn("unexpected_results", f"Excluded unexpected fit directories: {unexpected}")
    return dict(schema="hcsn-four-stage.analysis.v1", generated_utc=datetime.now(timezone.utc).isoformat(),
                run=str(run), analysis_source_sha256=sha256(__file__), protocol_sha256=protocol_hash,
                protocol=protocol, source_freeze=sources,
                candidate_freeze=dict(path=str(candidate_path), sha256=candidate_hash) if candidate_path else None,
                validation=dict(passed=not audit.errors and len(rows) == 75, expected_completed=75,
                                readable_completed=len(rows), individually_valid_completed=sum(row["integrity_valid"] for row in rows),
                                missing_fits=missing, invalid_fits=invalid, unexpected_fits=unexpected,
                                failure_attempt_count=len(failures), failures=failures,
                                errors=audit.errors, warnings=audit.warnings),
                fit_records=rows, by_task_arm=aggregate, paired_comparisons=comparisons,
                flow_sensitivity=sensitivities,
                dynamics_recovery={arm: {name: distribution([row["recovery"].get(name) for row in rows
                    if row["task"] == "dynamics" and row["arm"] == arm and row["recovery"] and row["integrity_valid"]])
                    for name in ("first_after_jump", "later_after_jump", "forcing_only")} for arm in ARMS},
                resampling=[dict(task=row["task"], arm=row["arm"], seed=row["seed"], **row["resampling"])
                            for row in rows if row["resampling"] and row["integrity_valid"]],
                cost=dict(fits=totals, feature_preparation=preparation, outer_process_receipts=outer,
                          complete_deployment_energy_joules=None, historical_media_acquisition_cost=None),
                query_swap_implemented=False, scope_and_limitations=NOTES)


def number(value, digits=3):
    return f"{value:.{digits}f}" if finite_number(value) else "NA"


def mean_sd(summary, scale=1, digits=3):
    if summary.get("mean") is None:
        return "NA"
    mean = number(summary["mean"] * scale, digits)
    sd = "NA" if summary.get("sd") is None else number(summary["sd"] * scale, digits)
    return f"{mean} ± {sd}"


def effect(metric):
    if not metric or metric.get("ci95") is None:
        return "NA"
    lo, hi = metric["ci95"]
    return f"{metric['estimate'] * 100:.2f} [{lo * 100:.2f}, {hi * 100:.2f}]"


def markdown(summary):
    validation = summary["validation"]
    lines = ["# Four-stage campaign analysis", "",
             f"Run: `{summary['run']}`", "",
             f"Integrity: **{'PASS' if validation['passed'] else 'INCOMPLETE / FAILED'}**. "
             f"Readable completed fits: {validation['readable_completed']}/75; individually valid: "
             f"{validation['individually_valid_completed']}/75; retained failed attempts: {validation['failure_attempt_count']}.", "",
             f"Protocol SHA-256: `{summary['protocol_sha256']}`. Analysis SHA-256: `{summary['analysis_source_sha256']}`.", "",
             "## Interpretation and metric definitions", ""]
    lines += ["- " + note for note in summary["scope_and_limitations"]]
    if validation["errors"] or validation["warnings"]:
        lines += ["", "## Integrity findings", ""]
        lines += [f"- **ERROR {row['code']}**: {row['message']}" for row in validation["errors"]]
        lines += [f"- Warning {row['code']}: {row['message']}" for row in validation["warnings"]]
    if validation["failures"]:
        lines += ["", "### Retained failed attempts", ""]
        for failure in validation["failures"]:
            reason = str(failure.get("traceback", failure.get("error", "See receipt"))).strip().splitlines()[-1]
            lines.append(f"- `{Path(failure['path']).name}`: {reason}; CPU {number(failure.get('cpu_seconds'))} s, wall {number(failure.get('wall_seconds'))} s.")
    lines += ["", "## Base-test quality", "",
              "Mean ± sample SD across three training seeds. Accuracy and weighted all-query use sample weights; AQ is the unweighted all-query episode rate. Values are percentages except CE.", "",
              "| Task | Arm | Seeds | Weighted accuracy | CE | AQ | Weighted AQ | Unweighted accuracy |",
              "|---|---|---:|---:|---:|---:|---:|---:|"]
    for task in TASKS:
        for arm in ARMS:
            item = summary["by_task_arm"][task][arm]
            score = item["metrics"].get("test__base", {})
            cells = [mean_sd(score.get(key, {}), 1 if key == "cross_entropy" else 100)
                     for key in ("accuracy", "cross_entropy", "all_queries_correct", "weighted_all_queries_correct", "unweighted_accuracy")]
            lines.append(f"| {task} | {arm} | {len(item['seeds'])} | " + " | ".join(cells) + " |")
    for designation, heading in (("primary", "Primary contrast: flow − diagonal"), ("exploratory", "Exploratory base-test contrasts")):
        lines += ["", "## " + heading, "",
                  "Paired differences in percentage points with 95% hierarchical percentile intervals. Three seeds provide limited uncertainty resolution; no multiplicity adjustment.", "",
                  "| Task | Contrast | Cluster unit/count | Weighted accuracy Δ [95% CI] | AQ Δ [95% CI] |",
                  "|---|---|---|---:|---:|"]
        for row in summary["paired_comparisons"]:
            if row["designation"] != designation or row["condition"] != "test__base":
                continue
            lines.append(f"| {row['task']} | {row['contrast']} | {row['sampling_unit']} / {row['clusters']} | "
                         f"{effect(row['metrics']['accuracy_difference'])} | {effect(row['metrics']['all_queries_correct_difference'])} |")
    lines += ["", "## Stress conditions", "",
              "Weighted accuracy / unweighted all-query rate, each in percent and averaged across seeds. Full seed SDs, CE, and paired exploratory intervals are in SUMMARY.json.", "",
              "| Task | Arm | Condition | Accuracy | AQ | Visible-target accuracy | Missing-target accuracy |",
              "|---|---|---|---:|---:|---:|---:|"]
    for task in TASKS:
        for arm in ARMS:
            for condition, score in summary["by_task_arm"][task][arm]["metrics"].items():
                if not condition.startswith("test__") or condition == "test__base":
                    continue
                values = [number(score.get(key, {}).get("mean") * 100) if score.get(key, {}).get("mean") is not None else "NA"
                          for key in ("accuracy", "all_queries_correct", "visible_target_accuracy", "missing_target_accuracy")]
                lines.append(f"| {task} | {arm} | {condition.removeprefix('test__')} | " + " | ".join(values) + " |")
    lines += ["", "## Flow sensitivities", "",
              "Full trained flow minus its inference intervention; these are exploratory sensitivities. Positive Δ indicates the intervention worsens that metric.", "",
              "| Task | Intervention contrast | Weighted accuracy Δ [95% CI] | AQ Δ [95% CI] |",
              "|---|---|---:|---:|"]
    for row in summary["flow_sensitivity"]:
        lines.append(f"| {row['task']} | {row['contrast']} | {effect(row['metrics']['accuracy_difference'])} | "
                     f"{effect(row['metrics']['all_queries_correct_difference'])} |")
    lines += ["", "## Dynamics recovery", "",
              "First query after the jump is position 9; later queries are positions 11, 13, and 15 (zero-based). Forcing-only is the runner's recorded quantized-forcing baseline; the archive does not contain its input values for independent reconstruction.", "",
              "| Arm | First after jump (%) | Later after jump (%) | Forcing-only query accuracy (%) |",
              "|---|---:|---:|---:|"]
    for arm, row in summary["dynamics_recovery"].items():
        lines.append(f"| {arm} | " + " | ".join(mean_sd(row[name], 100) for name in ("first_after_jump", "later_after_jump", "forcing_only")) + " |")
    lines += ["", "## Resampling consistency", "",
              "Maximum absolute logit difference at original observation positions, taking the worst of the three seeds; the declared threshold is 1e-4. This numerical gate is separate from accuracy.", "",
              "| Task | Arm | Worst difference | All three seeds pass |", "|---|---|---:|---|"]
    for task in TASKS[:-1]:
        for arm in ARMS:
            rows = [r for r in summary["resampling"] if r["task"] == task and r["arm"] == arm]
            maximum = max((r["max_abs_observed_logit_difference"] for r in rows), default=None)
            lines.append(f"| {task} | {arm} | {number(maximum, 8)} | {len(rows) == 3 and all(r['passed'] for r in rows)} ({len(rows)}/3 seeds) |")
    lines += ["", "## Compute and state", "",
              "Training CPU and total-fit CPU are per-seed mean ± SD, in seconds. Batch latency is the mean of each seed's nine-repeat median; the batch size is recorded per fit in JSON. Amortized latency is a throughput ratio, not single-episode latency.", "",
              "| Task | Arm | Parameters | State scalars | Training CPU (s) | Total fit CPU (s) | Batch latency (ms) | Amortized ms/episode |",
              "|---|---|---:|---:|---:|---:|---:|---:|"]
    for task in TASKS:
        for arm in ARMS:
            row = summary["by_task_arm"][task][arm]
            values = [number(row["parameters"]["mean"], 0), number(row["persistent_state_scalars"]["mean"], 0),
                      mean_sd(row["training_cpu_seconds"]), mean_sd(row["total_fit_cpu_seconds"]),
                      mean_sd(row["batch_median_latency_seconds"], 1000), mean_sd(row["amortized_seconds_per_episode"], 1000)]
            lines.append(f"| {task} | {arm} | " + " | ".join(values) + " |")
    cost = summary["cost"]
    lines += ["", "### Cost accounting", "",
              f"- Completed-fit CPU total, counted once: {number(cost['fits']['total_fit_cpu_seconds'])} s; summed per-fit wall time: {number(cost['fits']['total_fit_wall_seconds'])} s. Summed wall time is not necessarily campaign elapsed time.",
              f"- Training CPU subtotal inside those fits: {number(cost['fits']['training_cpu_seconds'])} s; it is not added again.",
              f"- Failure-attempt receipts: CPU {number(cost['fits']['failure_attempt_cpu_seconds'])} s, wall {number(cost['fits']['failure_attempt_wall_seconds'])} s. {cost['fits']['failure_accounting']}",
              f"- Feature-preparation receipts available: {cost['feature_preparation']['available']}; explicit CPU total {number(cost['feature_preparation']['cpu_seconds_sum_of_explicit_fields'])} s; wall total {number(cost['feature_preparation']['wall_seconds_sum_of_explicit_fields'])} s.",
              f"- Outer-process receipts available: {cost['outer_process_receipts']['available']}; explicit CPU total {number(cost['outer_process_receipts']['cpu_seconds_sum_of_explicit_fields'])} s; wall total {number(cost['outer_process_receipts']['wall_seconds_sum_of_explicit_fields'])} s. These receipts may contain the fit/preparation costs already shown.",
              "- Energy: unmeasured (`null`). Historical media acquisition cost: unknown (`null`). CPU seconds are not converted to joules.", ""]
    return "\n".join(lines)


def self_test():
    triples = np.array([[i >> 2, (i >> 1) & 1, i & 1] for i in range(8)])
    labels = (triples.min(1) == triples.max(1)).astype(np.int64)[:, None]
    weights = np.where(labels == 1, 3., 1.)
    negative = np.zeros((8, 1, 2)); negative[..., 0] = 2
    perfect = np.zeros_like(negative)
    perfect[np.arange(8), 0, labels[:, 0]] = 2
    actor = np.array(["a"] * 4 + ["b"] * 4)
    a = episode_stats(perfect, labels, weights, actor)
    b = episode_stats(negative, labels, weights, actor)
    assert b.scores["accuracy"] == .5 and b.scores["all_queries_correct"] == .75
    same = paired_bootstrap([a] * 3, [a] * 3, SEEDS, "avt", "fabricated", 2000)
    assert same["metrics"]["accuracy_difference"]["ci95"] == [0., 0.]
    paired = paired_bootstrap([a] * 3, [b] * 3, SEEDS, "avt", "fabricated", 2000)
    assert paired["clusters"] == 2 and paired["sampling_unit"] == "actor"
    assert paired["metrics"]["accuracy_difference"]["estimate"] == .5
    assert paired["metrics"]["all_queries_correct_difference"]["estimate"] == .25
    assert paired == paired_bootstrap([a] * 3, [b] * 3, SEEDS, "avt", "fabricated", 2000)
    duplicate_a = episode_stats(np.tile(perfect, (2, 1, 1)), np.tile(labels, (2, 1)),
                                np.tile(weights, (2, 1)), np.tile(actor, 2))
    duplicate_b = episode_stats(np.tile(negative, (2, 1, 1)), np.tile(labels, (2, 1)),
                                np.tile(weights, (2, 1)), np.tile(actor, 2))
    duplicate = paired_bootstrap([duplicate_a] * 3, [duplicate_b] * 3, SEEDS, "avt", "fabricated", 2000)
    assert duplicate["clusters"] == paired["clusters"]
    for metric in ("accuracy_difference", "all_queries_correct_difference"):
        assert duplicate["metrics"][metric] == paired["metrics"][metric]
    available = np.ones_like(labels, dtype=bool); available[0] = False
    visible = episode_stats(perfect, labels, weights, actor, available=available)
    assert visible.scores["missing_target_query_count"] == 1
    mismatch = episode_stats(perfect, labels[::-1], weights[::-1], actor)
    mismatch.identity = "mismatch"
    try:
        paired_bootstrap([a] * 3, [mismatch] * 3, SEEDS, "avt", "fabricated", 10)
    except ValueError:
        pass
    else:
        raise AssertionError("Mismatched paired identities were accepted")
    print(json.dumps(dict(status="passed", scope="fabricated arrays only; no campaign or held-out data read",
                          checks=["AV weighted/unweighted distinction", "actor clustering", "paired effects",
                                  "identical models zero interval", "deterministic sampling", "duplicated rows do not create actors", "availability stratum",
                                  "reject mismatched pairing"])))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--candidate-freeze", type=Path)
    parser.add_argument("--source-freeze", type=Path)
    parser.add_argument("--outer-receipt", type=Path, action="append")
    parser.add_argument("--feature-prep", type=Path, action="append")
    parser.add_argument("--repetitions", type=int, default=2000)
    parser.add_argument("--bootstrap-seed", type=int, default=20261031)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.run is None or args.out is None:
        parser.error("--run and --out are required unless --self-test is selected")
    if args.repetitions != 2000:
        parser.error("The frozen analysis uses exactly 2000 bootstrap repetitions")
    args.out.mkdir(parents=True, exist_ok=True)
    destinations = [args.out / "SUMMARY.json", args.out / "SUMMARY.md"]
    if any(path.exists() for path in destinations):
        parser.error("Analysis output already exists; choose a fresh --out directory")
    summary = summarize(args)
    with destinations[0].open("x") as stream:
        json.dump(summary, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    with destinations[1].open("x") as stream:
        stream.write(markdown(summary))
    print(json.dumps(dict(status="passed" if summary["validation"]["passed"] else "incomplete_or_failed",
                          completed=summary["validation"]["readable_completed"], expected=75,
                          errors=len(summary["validation"]["errors"]), out=str(args.out))))
    if not summary["validation"]["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
