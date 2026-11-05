"""Offline candidate admission and reversible local artifact selection.

Admission uses a frozen source census and a bounded, one-sided Hoeffding test
for each seed/condition endpoint. It is conservative and conditional on original
source independence, valid return bounds, and the declared measurement scope.
It is not a general safe-RL or conditional OOD guarantee. No target enters live
action selection. Failure to establish benefit preserves the active artifact.
"""

from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile

from .measured_cost import Tariff, nonnegative


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _time(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Collection and freeze times require a timezone")
    return parsed


def assess(protocol, rows):
    """Recompute admission from paired observations, never from a pass flag.

    A row is one original source, with a fixed number of paired emission draws.
    Every endpoint is a separate trained seed/condition; none may be dropped.
    For gamma>0 the bounded variable is exp(-gamma*(R_base-low)) minus
    exp(gamma*margin)*exp(-gamma*(R_candidate-low)). Its positive expectation implies
    CE(candidate)-CE(base)>margin. This is not CE of paired return differences.
    """
    if protocol.get("schema") != "hepta.v6.safe-update.v1":
        raise ValueError("Unknown admission protocol")
    for name in ("candidate_id", "baseline_id"):
        if not isinstance(protocol[name], str) or not re.fullmatch("[0-9a-f]{64}", protocol[name]):
            raise ValueError("Artifacts must be bound to SHA-256 identities")
    if protocol["candidate_id"] == protocol["baseline_id"]:
        raise ValueError("Candidate and frozen baseline must differ")
    gamma = nonnegative(protocol["gamma"], "gamma")
    margin = nonnegative(protocol["minimum_effect"], "minimum effect")
    alpha = nonnegative(protocol["alpha"], "alpha")
    if not 0 < alpha < 1 or type(protocol["draws"]) is not int or protocol["draws"] < 1:
        raise ValueError("Invalid confidence level or draw census")
    low, high = protocol["return_bounds"]
    if not all(type(v) in (int, float) and math.isfinite(v) for v in (low, high)) or low >= high:
        raise ValueError("Finite ordered return bounds required")
    if not math.isfinite(high - low):
        raise ValueError("Return range is not representable")
    if gamma and max(abs(gamma * low), abs(gamma * high), gamma * margin) > 300:
        raise ValueError("Risk profile exceeds the declared numeric envelope")
    census = protocol["source_census"]
    if not isinstance(census, dict) or not census:
        raise ValueError("A frozen nonempty endpoint census is required")
    if any(not isinstance(sources, list) or not sources or
           any(not isinstance(s, str) or not s for s in sources) or
           len(sources) != len(set(sources)) for sources in census.values()):
        raise ValueError("Empty or duplicate source census")
    expected = {(endpoint, source) for endpoint, sources in census.items() for source in sources}
    if any(not isinstance(x, str) or not x for key in expected for x in key):
        raise ValueError("Endpoint/source identities must be nonempty strings")
    exclusion = protocol["training_and_selection_sources"]
    if (not isinstance(exclusion, list) or any(not isinstance(s, str) or not s for s in exclusion)
            or len(exclusion) != len(set(exclusion))):
        raise ValueError("Training/source exclusion must be an explicit unique list")
    excluded = set(exclusion)
    if any(source in excluded for _, source in expected):
        raise ValueError("Evaluation source was used for training or selection")
    sources = {source for _, source in expected}
    manifest = protocol["source_content_sha256"]
    if not isinstance(manifest, dict) or set(manifest) != sources:
        raise ValueError("Frozen content manifest must cover the exact source census")
    for hashes in manifest.values():
        if (not isinstance(hashes, list) or not hashes or len(hashes) != len(set(hashes))
                or any(not isinstance(h, str) or not re.fullmatch("[0-9a-f]{64}", h) for h in hashes)):
            raise ValueError("Original source content hashes must be explicit and unique")
    excluded_hashes = protocol["training_and_selection_content_sha256"]
    if (not isinstance(excluded_hashes, list) or any(not isinstance(h, str) or
            not re.fullmatch("[0-9a-f]{64}", h) for h in excluded_hashes)):
        raise ValueError("Training content exclusions require explicit hashes")
    if set(excluded_hashes).intersection(h for hashes in manifest.values() for h in hashes):
        raise ValueError("Evaluation content overlaps training/selection content")
    for panel in census.values():
        pixels = [h for source in panel for h in manifest[source]]
        if len(set(pixels)) != len(pixels):
            raise ValueError("Distinct source clusters share original content")
    tariff = Tariff(**protocol["tariff"])
    budget = protocol["budget"]
    budget_metrics = {"cpu_seconds": "cpu_seconds", "wall_seconds": "wall_seconds",
                      "gpu_seconds": "gpu_seconds", "owned_bytes": "peak_owned_bytes",
                      "joules": "joules"}
    if (not isinstance(budget, dict) or not budget or
            not set(budget) <= set(budget_metrics) | {"work", "service_cost"}):
        raise ValueError("Unknown or empty resource budget")
    for name, value in budget.items():
        nonnegative(value, name + " budget")
    nonnegative(protocol["max_wall_seconds"], "deadline")
    if type(protocol["max_owned_bytes"]) is not int or protocol["max_owned_bytes"] < 0:
        raise ValueError("Owned-memory limit must be a nonnegative integer")
    if not isinstance(protocol["required_cost_stages"], list) or not protocol["required_cost_stages"]:
        raise ValueError("Measured cost scope must be declared before evaluation")
    amortization = nonnegative(protocol["candidate_extra_training_cost"], "extra training cost")
    deployments = protocol["amortization_deployments"]
    if type(deployments) is not int or deployments < 1:
        raise ValueError("A positive declared amortization deployment count is required")
    amortization /= deployments
    reasons, seen, grouped = [], set(), {endpoint: [] for endpoint in census}
    if protocol["evidence_role"] != "prospective_confirmation":
        reasons.append("development_or_historical_evidence")
    if protocol["candidate_frozen_at"] != protocol["protocol_frozen_at"]:
        if _time(protocol["candidate_frozen_at"]) > _time(protocol["protocol_frozen_at"]):
            raise ValueError("Candidate changed after evaluation protocol freeze")
    for row in rows:
        key = row["endpoint"], row["source_id"]
        if key not in expected or key in seen:
            raise ValueError("Unexpected, repeated or missing source identity")
        seen.add(key)
        if row["candidate_id"] != protocol["candidate_id"] or row["baseline_id"] != protocol["baseline_id"]:
            raise ValueError("Wrong candidate or baseline artifact identity")
        if (not isinstance(row["baseline_information_id"], str) or
                not re.fullmatch("[0-9a-f]{64}", row["baseline_information_id"]) or
                row["candidate_information_id"] != row["baseline_information_id"]):
            raise ValueError("Compared policies did not receive the same information")
        if row["candidate_budget"] != row["baseline_budget"] or row["baseline_budget"] != protocol["budget"]:
            raise ValueError("Compared policies did not receive the frozen equal budget")
        if _time(row["collected_at"]) <= _time(protocol["protocol_frozen_at"]):
            reasons.append("not_collected_after_freeze")
        evidence = row["qualification_evidence"]
        if digest(evidence) != row["qualification_evidence_sha256"]:
            raise ValueError("Qualification evidence changed")
        if evidence["candidate_id"] != protocol["candidate_id"]:
            raise ValueError("Qualification evidence belongs to another candidate")
        checks = evidence["checks"]
        required_checks = ("state_coverage", "belief_calibration", "advantage_calibration",
                           "unknown_rejection", "recovery", "same_training_budget")
        if any(checks.get(name) is not True for name in required_checks):
            reasons.append("qualification_incomplete")
        if len(row["draws"]) != protocol["draws"]:
            raise ValueError("Emission draw census changed")
        paired = []
        for draw in row["draws"]:
            returns = {}
            for arm in ("baseline", "candidate"):
                outcome = draw[arm]
                utility = outcome["utility"]
                if type(utility) not in (int, float) or not math.isfinite(utility):
                    raise ValueError("Nonfinite utility")
                receipt = outcome["cost"]
                if digest(receipt) != outcome["cost_sha256"]:
                    raise ValueError("Cost receipt changed")
                measured = tariff.amount(receipt)
                for name, limit in budget.items():
                    actual = (outcome.get("work") if name == "work" else receipt["service_cost"]
                              if name == "service_cost" else receipt["physical"][budget_metrics[name]])
                    if actual is None:
                        reasons.append("unmeasured_budget_metric")
                    elif nonnegative(actual, name) > limit:
                        reasons.append("resource_budget_exceeded")
                if not set(protocol["required_cost_stages"]) <= {s["name"] for s in receipt["stages"]}:
                    reasons.append("incomplete_cost_scope")
                if receipt["physical"]["wall_seconds"] > protocol["max_wall_seconds"]:
                    reasons.append("deadline_exceeded")
                if receipt["physical"]["peak_owned_bytes"] > protocol["max_owned_bytes"]:
                    reasons.append("owned_memory_budget_exceeded")
                returns[arm] = utility - measured - (amortization if arm == "candidate" else 0.0)
                if not low <= returns[arm] <= high:
                    raise ValueError("Return violates preregistered bounds; never clip")
            if gamma:
                delta = returns["candidate"] - returns["baseline"]
                gap = gamma * (margin - delta)
                paired.append(-math.exp(-gamma * (returns["baseline"] - low)) * math.expm1(gap)
                              if gap <= 0 else math.exp(gamma * (margin - (returns["candidate"] - low)))
                              * math.expm1(-gap))
            else:
                paired.append(returns["candidate"] - returns["baseline"] - margin)
        grouped[row["endpoint"]].append(math.fsum(paired) / len(paired))
    if seen != expected:
        raise ValueError("Incomplete source panel; no partial-panel promotion")
    if gamma:
        span = (1 + math.exp(gamma * margin)) * -math.expm1(-gamma * (high - low))
    else:
        span = 2 * (high - low)
    if not math.isfinite(span):
        raise ValueError("Test variable range is not representable")
    endpoints = {}
    for endpoint, values in grouped.items():
        mean = math.fsum(values) / len(values)
        radius = span * math.sqrt(math.log(len(census) / alpha) / (2 * len(values)))
        endpoints[endpoint] = {"original_sources": len(values), "paired_test_mean": mean,
                               "one_sided_lower_bound": mean - radius}
        if mean - radius <= 0:
            reasons.append("robust_net_benefit_not_established")
    return {"decision": "no-update" if reasons else "eligible", "reasons": sorted(set(reasons)),
            "endpoints": endpoints, "protocol_sha256": digest(protocol),
            "evidence_sha256": digest(rows), "candidate_id": protocol["candidate_id"],
            "baseline_id": protocol["baseline_id"], "scope": "offline local selection only",
            "assumptions": "independent original sources; valid bounded returns and qualification evidence"}


@contextmanager
def _writer(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / "WRITER.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    locked = False
    try:
        if os.name == "nt":
            import msvcrt
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        locked = True
        yield directory
    finally:
        if locked and os.name == "nt":
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        elif locked:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
        # Keep the inode: removing it permits another writer to lock a new file.


def _atomic(path, value):
    _atomic_bytes(path, json.dumps(value, sort_keys=True, allow_nan=False).encode())


def _atomic_bytes(path, raw):
    descriptor, temporary = tempfile.mkstemp(prefix=".selection-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            parent_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _retain_artifact(root, path, expected):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("Artifact bytes differ from evaluated identity")
    directory = root / "artifacts"
    directory.mkdir(exist_ok=True)
    retained = directory / (expected + ".bin")
    if retained.exists():
        if file_digest(retained) != expected:
            raise ValueError("Retained rollback artifact changed")
    else:
        _atomic_bytes(retained, raw)
    return str(retained.resolve())


def select(directory, candidate_file, protocol, rows, *, expected_active_digest):
    """Preserve active bytes on no-update; atomic compare-and-swap otherwise."""
    report = assess(protocol, rows)
    with _writer(directory) as root:
        path = root / "ACTIVE.json"
        prior = json.loads(path.read_text()) if path.exists() else None
        if (digest(prior) if prior else None) != expected_active_digest:
            raise ValueError("Active model changed; refusing stale writer")
        if prior and prior["artifact_sha256"] != protocol["baseline_id"]:
            raise ValueError("Evaluation baseline is not the currently active artifact")
        if prior and file_digest(prior["artifact"]) != prior["artifact_sha256"]:
            raise ValueError("Active baseline bytes changed")
        if protocol["evidence_role"] == "prospective_confirmation":
            consumed_path = root / "CONSUMED.json"
            consumed = json.loads(consumed_path.read_text()) if consumed_path.exists() else {}
            identities = {"source:" + h for hashes in protocol["source_content_sha256"].values() for h in hashes}
            identities.update("information:" + row["baseline_information_id"] for row in rows)
            if identities.intersection(consumed):
                return report | {"decision": "no-update", "reasons": sorted(set(report["reasons"] +
                    ["confirmation_source_already_consumed"]))}
            for identity in identities:
                consumed[identity] = {"protocol_sha256": report["protocol_sha256"],
                                    "evidence_sha256": report["evidence_sha256"]}
            # Consume before activation: interruption errs toward no update.
            _atomic(consumed_path, consumed)
        if report["decision"] == "no-update":
            return report
        candidate_file = Path(candidate_file).resolve(strict=True)
        retained = _retain_artifact(root, candidate_file, protocol["candidate_id"])
        if prior:
            prior = prior | {"artifact": _retain_artifact(root, prior["artifact"], prior["artifact_sha256"])}
        revision = 0 if prior is None else prior["revision"] + 1
        state = {"revision": revision, "artifact": retained,
                 "artifact_sha256": protocol["candidate_id"], "previous": prior,
                 "admission": report}
        _atomic(path, state)
        return report | {"active_digest": digest(state)}


def load_active(directory):
    """Read and verify one byte snapshot; consumers must deserialize these bytes."""
    state = json.loads((Path(directory) / "ACTIVE.json").read_text())
    raw = Path(state["artifact"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != state["artifact_sha256"]:
        raise ValueError("Selected artifact bytes changed")
    return state, raw


def rollback(directory, *, expected_active_digest):
    """Restore verified previous bytes while monotonically increasing revision."""
    with _writer(directory) as root:
        path = root / "ACTIVE.json"
        current = json.loads(path.read_text())
        if digest(current) != expected_active_digest or not current.get("previous"):
            raise ValueError("Stale rollback or no previous selection")
        prior = current["previous"]
        if file_digest(prior["artifact"]) != prior["artifact_sha256"]:
            raise ValueError("Previous artifact is unavailable or changed")
        restored = prior | {"revision": current["revision"] + 1,
                            "rollback_of": digest(current), "previous": current}
        _atomic(path, restored)
        return restored
