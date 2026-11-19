"""Source-only prospective CellSplit evidence *format*; never an authorization.

Consumes a prediction-only prelabel packet and a separately supplied outcomes
packet. The caller MUST provide the prelabel SHA-256 captured before labels
became accessible. A matching caller-provided hash is not authentication or
proof of timing, source independence, actual physical work, or label custody.

Even a numerically perfect panel is deliberately SHADOW_ONLY / DENY_ALL. This
is an executable research protocol for future independently witnessed runs,
not a device/Model/CNS/NDU selector or a claim about current historical trials.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import random
import stat


class Rejected(ValueError):
    """Research evidence is incomplete, inconsistent, or ineligible."""


PRED_SCHEMA = "hepta.cell-fabric.prospective-prelabel.v1"
GOLD_SCHEMA = "hepta.cell-fabric.prospective-gold.v1"
ARMS = ("no_change", "equal_budget_single", "split", "type_prior", "zero_feature")
MAX_BYTES = 4_000_000
MAX_CASES = 4096
MAX_ROOTS = 4096
MAX_FAMILIES = 16
HEX = set("0123456789abcdef")


def _strict_pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise Rejected("duplicate JSON object key")
        out[key] = value
    return out


def _reject_constant(token):
    raise Rejected(f"nonfinite JSON constant {token}")


def _load(raw):
    try:
        return json.loads(raw, object_pairs_hook=_strict_pairs,
                          parse_constant=_reject_constant)
    except (ValueError, UnicodeDecodeError, TypeError) as exc:
        raise Rejected("invalid strict JSON evidence") from exc


def _keys(obj, keys):
    if type(obj) is not dict or set(obj) != set(keys):
        raise Rejected("unexpected or missing evidence fields")


def _identity(value):
    if (type(value) is not str or not 1 <= len(value) <= 128
            or not value.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in value)):
        raise Rejected("invalid bounded source identity")
    return value


def _identities(values, limit):
    if type(values) is not list or len(values) > limit:
        raise Rejected("unbounded identity census")
    items = [_identity(v) for v in values]
    if len(items) != len(set(items)):
        raise Rejected("duplicate identity")
    return items


def _sha(value):
    if type(value) is not str or len(value) != 64 or any(c not in HEX for c in value):
        raise Rejected("noncanonical source SHA-256")
    return value


def _count(value):
    if type(value) is not int or value < 0 or value > 10**12:
        raise Rejected("unbounded, missing or noninteger work")
    return value


def _probability(value):
    if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 1:
        raise Rejected("invalid model probability")
    return float(value)


def _read_file(path):
    if path.is_symlink():
        raise Rejected("evidence symlink denied")
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise Rejected("evidence must be regular file")
            data = stream.read(MAX_BYTES + 1)
    except OSError as exc:
        raise Rejected("evidence cannot be opened") from exc
    if not data or len(data) > MAX_BYTES:
        raise Rejected("empty or oversized evidence")
    return data


def validate_prelabel(packet):
    _keys(packet, ("schema", "study_id", "source_families", "fit_roots",
                   "calibration_roots", "arms", "work", "predictions", "authority"))
    if packet["schema"] != PRED_SCHEMA or packet["authority"] != "DENY_ALL":
        raise Rejected("unexpected evidence class or authority")
    _identity(packet["study_id"])
    families = _identities(packet["source_families"], MAX_FAMILIES)
    if len(families) < 2:
        raise Rejected("no independent cross-family design")
    fit = _identities(packet["fit_roots"], MAX_ROOTS)
    cal = _identities(packet["calibration_roots"], MAX_ROOTS)
    if set(fit) & set(cal):
        raise Rejected("fit/calibration overlap")
    if packet["arms"] != list(ARMS):
        raise Rejected("not an exactly registered five-arm design")
    work = packet["work"]
    if type(work) is not dict or set(work) != set(ARMS):
        raise Rejected("missing all-arm resource census")
    for costs in work.values():
        _keys(costs, ("encoder_calls", "head_calls", "cpu_us", "resident_bytes"))
        for scalar in costs.values():
            _count(scalar)
    rows = packet["predictions"]
    if type(rows) is not list or not rows or len(rows) > MAX_CASES * len(ARMS):
        raise Rejected("empty or unbounded prelabel prediction set")
    expected = {}
    root_families = {}
    seen = set()
    forbidden_roots = set(fit) | set(cal)
    for row in rows:
        _keys(row, ("case_id", "root", "family", "arm", "p1"))
        case, root, family = (_identity(row[k]) for k in ("case_id", "root", "family"))
        arm = row["arm"]
        if family not in families or arm not in ARMS:
            raise Rejected("unsupported family or arm")
        if root in forbidden_roots:
            raise Rejected("held source root present in fit/calibration")
        if root in root_families and root_families[root] != family:
            raise Rejected("source root reused across families")
        root_families[root] = family
        key = (case, arm)
        if key in seen:
            raise Rejected("duplicate physical arm/case record")
        seen.add(key)
        value = _probability(row["p1"])
        old = expected.setdefault(case, {"root": root, "family": family, "arms": {}})
        if old["root"] != root or old["family"] != family:
            raise Rejected("case identity changes source across arms")
        old["arms"][arm] = value
    if len(expected) > MAX_CASES or len(root_families) > MAX_ROOTS:
        raise Rejected("source census exceeded")
    if any(set(x["arms"]) != set(ARMS) for x in expected.values()):
        raise Rejected("incomplete paired arm census")
    if {x["family"] for x in expected.values()} != set(families):
        raise Rejected("source family has no evaluated cases")
    return expected, families, root_families


def _check_gold(packet, prediction_cases, families, roots):
    _keys(packet, ("schema", "study_id", "outcomes", "source_families", "authority"))
    if packet["schema"] != GOLD_SCHEMA or packet["authority"] != "DENY_ALL":
        raise Rejected("gold source is not bounded/deny-all")
    _identity(packet["study_id"])
    if _identities(packet["source_families"], MAX_FAMILIES) != families:
        raise Rejected("gold family census differs from prelabel")
    outcomes = packet["outcomes"]
    if type(outcomes) is not list or len(outcomes) != len(prediction_cases):
        raise Rejected("unmatched independent-label census")
    labels = {}
    for row in outcomes:
        _keys(row, ("case_id", "root", "family", "label"))
        case, root, family = (_identity(row[k]) for k in ("case_id", "root", "family"))
        if (case in labels or case not in prediction_cases
                or prediction_cases[case]["root"] != root
                or prediction_cases[case]["family"] != family
                or roots.get(root) != family):
            raise Rejected("duplicate, changed or missing gold source identity")
        y = row["label"]
        if type(y) is not int or y not in (0, 1):
            raise Rejected("invalid gold binary label")
        labels[case] = y
    if set(labels) != set(prediction_cases):
        raise Rejected("incomplete gold labels")
    return labels


def review(prelabel_bytes, gold_bytes, expected_prelabel_sha256):
    """Compute paired numeric diagnostics; no caller can issue release authority."""
    digest = hashlib.sha256(prelabel_bytes).hexdigest()
    if digest != _sha(expected_prelabel_sha256):
        raise Rejected("prelabel bytes disagree with frozen SHA-256")
    prelabel, gold = _load(prelabel_bytes), _load(gold_bytes)
    cases, families, roots = validate_prelabel(prelabel)
    labels = _check_gold(gold, cases, families, roots)
    if gold["study_id"] != prelabel["study_id"]:
        raise Rejected("independent-outcome study identity drift")
    report = {}
    for family in families:
        selected = [(v, labels[k]) for k, v in sorted(cases.items()) if v["family"] == family]
        grouped = {a: {"correct": 0, "brier_sum": 0.0} for a in ARMS}
        paired = {}
        for arm in ARMS:
            probs = [item["arms"][arm] for item, _ in selected]
            truth = [y for _, y in selected]
            grouped[arm] = {"correct": sum(int(p >= .5) == y for p, y in zip(probs, truth)),
                            "brier": math.fsum((p - y)**2 for p, y in zip(probs, truth)) / len(selected)}
        for baseline in ("no_change", "equal_budget_single", "type_prior", "zero_feature"):
            wins = losses = 0
            brier_differences = {}
            for item, y in selected:
                split, alt = item["arms"]["split"], item["arms"][baseline]
                s, b = int(split >= .5) == y, int(alt >= .5) == y
                wins += int(s and not b)
                losses += int(b and not s)
            for item, y in selected:
                root = item["root"]
                split = (item["arms"]["split"] - y)**2
                control = (item["arms"][baseline] - y)**2
                brier_differences.setdefault(root, []).append(control - split)
            # Every root is the resampling unit, not every correlated Cell call.
            root_deltas = [math.fsum(v) / len(v) for _, v in sorted(brier_differences.items())]
            mean = math.fsum(root_deltas) / len(root_deltas)
            bounds = None
            if len(root_deltas) >= 2:
                rng = random.Random(17017)
                boot = sorted(math.fsum(root_deltas[rng.randrange(len(root_deltas))]
                                        for _ in root_deltas) / len(root_deltas)
                              for _ in range(512))
                bounds = [boot[12], boot[499]]  # root-block descriptive percentiles
            paired[baseline] = {"split_only_correct": wins, "baseline_only_correct": losses,
                                "root_mean_brier_gain": mean, "root_bootstrap_95pct_descriptive": bounds}
        report[family] = {"cases": len(selected),
                          "independent_roots_declared": len({v["root"] for v, _ in selected}),
                          "arm_metrics": grouped, "paired_vs_split": paired}
    return {"schema": "hepta.cell-fabric.prospective-panel-review.v1",
            "study_id": prelabel["study_id"], "prelabel_sha256": digest,
            "gold_sha256": hashlib.sha256(gold_bytes).hexdigest(),
            "source_families": report, "reported_work_unverified": prelabel["work"],
            "limitations": ["prelabel_sha_not_independently_timestamped_or_signed",
                            "gold_custody_not_independently_authenticated",
                            "model_source_and_frozen_baseline_not_physically_reexecuted",
                            "head_costs_and_equal_budget_not_externally_measured",
                            "source_root_independence_is_asserted_not_verified",
                            "cluster_bootstrap_is_descriptive_not_prospective_inference",
                            "NDU_future_utility_and_negative_transfer_not_observed"],
            "status": "HOLD_NO_GO", "authority": "DENY_ALL",
            "cell_split_authorized": False, "model_selection_authorized": False,
            "ndu_utility_verified": False, "production_accepted": False}


def _write_exclusive(path, data):
    if path.exists() or path.is_symlink():
        raise Rejected("output must be a new path")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise Rejected("cannot create exclusive review") from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prelabel", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--expected-prelabel-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = review(_read_file(args.prelabel), _read_file(args.gold), args.expected_prelabel_sha256)
    payload = (json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    _write_exclusive(args.output, payload)
    print("P06_RESEARCH_ONLY: HOLD_NO_GO / DENY_ALL")


if __name__ == "__main__":
    main()
