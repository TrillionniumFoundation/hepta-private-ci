"""Independent evidence recomputation; never imports the policy solver.

The input audit uses graph traversal instead of the preparation union-find.
It reads source labels solely to verify declared component exclusions and
balanced preparation. It does not open the final-scoring label file.
"""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import itertools
import json
from pathlib import Path
import unicodedata

import numpy as np

from prepare_news_cohorts import _read_archive, select_rows, COUNTS


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def normalize(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def audit_inputs(data_dir, archive):
    root = Path(data_dir)
    receipt = json.loads((root / "data_receipt.json").read_bytes())
    for name, expected in receipt["files"].items():
        path = root / name
        if path.name != name or path.is_symlink():
            raise ValueError("unbounded or aliased input artifact")
        payload = path.read_bytes()
        if len(payload) != expected["bytes"] or sha(payload) != expected["sha256"]:
            raise ValueError(f"data artifact changed: {name}")
    sources = json.loads((root / "sources.json").read_bytes())["rows"]
    predictors = json.loads((root / "predictors.json").read_bytes())["rows"]
    training = json.loads((root / "train_labels.json").read_bytes())["roles"]
    if (len(sources) != len(predictors) or len({s["raw_source_id"] for s in sources}) != len(sources)
            or [s["index"] for s in sources] != list(range(len(sources)))):
        raise ValueError("duplicate or misaligned selected source")
    if any(set(p) != {"source_id", "source_version", "text"} for p in predictors):
        raise ValueError("unexpected predictor metadata")
    if set(training) != {"old_train", "old_probe", "current_train", "current_probe"}:
        raise ValueError("training label file contains unexpected roles")
    raw = _read_archive(archive)
    old = {r["source_id"] for cohort in select_rows(raw, COUNTS).values() for r in cohort}
    by_story, by_title = defaultdict(list), defaultdict(list)
    for i, row in enumerate(raw):
        by_story[row["source_group_id"]].append(i)
        by_title[normalize(row["text"])].append(i)
    selected = {r["raw_source_id"]: r for r in sources}
    seen = bytearray(len(raw))
    component_count, verified = 0, 0
    reasons, support = Counter(), Counter()
    candidates = defaultdict(list)
    actual_labels = {}
    wanted_months = {spec["month"] for spec in receipt["roles"].values()}
    for start in range(len(raw)):
        if seen[start]:
            continue
        pending, members = [start], []
        seen[start] = 1
        while pending:
            index = pending.pop()
            members.append(index)
            row = raw[index]
            # Each adjacency list is consumed once, independent of union-find.
            adjacent = by_story.pop(row["source_group_id"], [])
            adjacent += by_title.pop(normalize(row["text"]), [])
            for neighbour in adjacent:
                if not seen[neighbour]:
                    seen[neighbour] = 1
                    pending.append(neighbour)
        component_count += 1
        ids = sorted(raw[i]["source_id"] for i in members)
        component_id = "news-group:" + sha(ids)
        months = {datetime.fromtimestamp(raw[i]["timestamp_ms"] / 1000, timezone.utc).strftime("%Y-%m")
                  for i in members}
        labels = {raw[i]["label"] for i in members}
        causes = []
        if len(months) != 1:
            causes.append("cross_month")
        if len(labels) != 1:
            causes.append("label_conflict")
        if old.intersection(ids):
            causes.append("previous_cohort_component")
        for cause in causes:
            reasons[cause] += 1
        picked = [selected[source] for source in ids if source in selected]
        if picked and (causes or len(picked) != 1):
            raise ValueError("selected source component leaks, conflicts or spans months")
        if causes:
            continue
        month, label = next(iter(months)), next(iter(labels))
        if month not in wanted_months:
            reasons["outside_selected_months"] += 1
            continue
        ordinary = [i for i in members
                    if int(sha(normalize(raw[i]["publisher"]).encode())[:8], 16) % 5 != 0]
        if not ordinary:
            reasons["no_non_ood_publisher"] += 1
            continue
        rep_index = min(ordinary, key=lambda i: (raw[i]["timestamp_ms"], raw[i]["source_id"]))
        representative = raw[rep_index]
        support[f"{month}/{label}"] += 1
        candidates[(month, label)].append((sha([receipt["salt"], component_id]), representative["source_id"]))
        if not picked:
            continue
        source = picked[0]
        index = source["index"]
        predictor = predictors[index]
        expected = {
            "source_id": "uci-news:" + representative["source_id"],
            "source_version": "sha256:" + representative["source_row_sha256"],
            "text": representative["text"],
        }
        if (source["raw_source_id"] != representative["source_id"] or predictor != expected
                or source["component_id"] != component_id or source["month"] != month
                or source["component_member_count"] != len(ids)
                or source["component_members_sha256"] != sha(ids)
                or source["normalized_title_sha256"] != sha(normalize(representative["text"]).encode())
                or source["source_row_sha256"] != representative["source_row_sha256"]
                or receipt["roles"][source["role"]]["month"] != month):
            raise ValueError("selected representative, component or predictor binding differs")
        actual_labels[index] = label
        verified += 1
    if (verified != len(sources) or component_count != receipt["audit"]["raw_components"]
            or dict(reasons) != receipt["audit"]["excluded_components_by_reason"]
            or dict(support) != receipt["audit"]["eligible_components_by_month_class"]):
        raise ValueError("independent graph counts differ")
    offsets = Counter()
    for role in ("old_train", "old_probe", "old_test", "current_train", "current_probe", "future_may", "future_june"):
        spec = receipt["roles"][role]
        month, count = spec["month"], spec["rows"]
        role_sources = [s for s in sources if s["role"] == role]
        if (len(role_sources) != count
                or Counter(actual_labels[s["index"]] for s in role_sources) != {j: count // 4 for j in range(4)}):
            raise ValueError("selected count or class balance differs")
        selected_ids = {s["raw_source_id"] for s in role_sources}
        expected_ids = set()
        for label in range(4):
            key = (month, label)
            values = sorted(candidates[key])
            begin, end = offsets[key], offsets[key] + count // 4
            expected_ids.update(source for _, source in values[begin:end])
            offsets[key] = end
        if expected_ids != selected_ids:
            raise ValueError("deterministic hash-ranked component sampling differs")
        if role in training:
            saved = training[role]
            indices = [s["index"] for s in role_sources]
            if (saved["indices"] != indices or saved["labels"] != [actual_labels[i] for i in indices]
                    or saved["source_ids"] != [sources[i]["source_id"] for i in indices]):
                raise ValueError("training labels or role indices differ from source")
    return {
        "schema": "hepta.cell-field-independent-input-audit.v1",
        "algorithm": "independent adjacency-list component traversal; no preparation union-find",
        "raw_rows": len(raw), "components": component_count, "verified_selected_components": verified,
        "component_exclusion_counts": dict(reasons), "eligible_counts": dict(support),
        "deterministic_sampling_reproduced": True, "predictor_allowlist_verified": True,
        "training_labels_reproduced": True, "final_labels_opened": False,
        "data_receipt_sha256": sha((root / "data_receipt.json").read_bytes()),
        "auditor_sha256": sha(Path(__file__).read_bytes()),
    }


def verify_seal(run_dir):
    """Verify every sealed byte before opening predictions or final labels."""
    root = Path(run_dir)
    seal = json.loads((root / "pre_evaluation_seal.json").read_bytes())
    files = seal["files"]
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if actual != set(files) | {"pre_evaluation_seal.json"}:
        raise ValueError("run artifact set differs from the pre-evaluation inventory")
    for name, expected in files.items():
        path = root / name
        if (Path(name).is_absolute() or ".." in Path(name).parts
                or path.is_symlink() or not path.is_file()):
            raise ValueError("unsafe sealed artifact path")
        data = path.read_bytes()
        if len(data) != expected["bytes"] or sha(data) != expected["sha256"]:
            raise ValueError(f"sealed artifact changed: {name}")
    return seal


def _load_arrays(path):
    with np.load(path, allow_pickle=False) as archive:
        return {name: archive[name] for name in archive.files}


def _checkpoint_vector(directory):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_bytes())
    state = _load_arrays(directory / "state.npz")
    vector = np.concatenate([state[f"{group}__{name}"].ravel()
                             for group in ("theta", "m", "v")
                             for name in manifest["parameter_names"]])
    if sha((directory / "state.npz").read_bytes()) != manifest["payload_sha256"]:
        raise ValueError("checkpoint payload differs from manifest")
    return vector, manifest


def _probability_and_gradient(theta, mode, features, labels=None):
    """Independent fixed-head forward/gradient algebra for the two registered heads."""
    x = np.asarray(features, dtype=np.float64)
    width, classes = x.shape[1], 4
    x = x / np.maximum(np.sqrt(np.square(x).sum(axis=1, keepdims=True)), 1e-12) * np.sqrt(width)
    w = theta[:width * classes].reshape(width, classes)
    offset = width * classes
    if mode == "linear":
        bias, u, gate = theta[offset:offset + classes], x, None
    elif mode == "gated":
        a = theta[offset:offset + width]
        bias = theta[offset + width:offset + width + classes]
        g = theta[offset + width + classes:]
        gate_argument = x * a + g
        gate = 1 / (1 + np.exp(-np.clip(gate_argument, -40, 40)))
        u = x * gate
    else:
        raise ValueError("unregistered Head in independent forward evaluator")
    logits = u @ w + bias
    exponential = np.exp(logits - np.max(logits, axis=1, keepdims=True))
    probability = exponential / exponential.sum(axis=1, keepdims=True)
    if labels is None:
        return probability, None, None
    y = np.asarray(labels, dtype=np.int64)
    weights = 1 / np.bincount(y, minlength=classes)[y]
    weights /= weights.sum()
    loss = float(np.sum(-weights * np.log(np.maximum(probability[np.arange(len(y)), y], 1e-15))))
    delta = probability.copy()
    delta[np.arange(len(y)), y] -= 1
    delta *= weights[:, None]
    gw, gb = u.T @ delta, delta.sum(axis=0)
    if gate is None:
        gradient = np.concatenate([gw.ravel(), gb])
    else:
        dg = (delta @ w.T) * x * gate * (1 - gate) * (np.abs(gate_argument) < 40)
        gradient = np.concatenate([gw.ravel(), (dg * x).sum(axis=0), gb, dg.sum(axis=0)])
    return probability, loss, gradient


def _cost(fields, actions, target, dt, effort):
    error = fields - target
    track = float(0.5 * (np.dot(error[-1], error[-1]) + dt * np.sum(error[:-1] ** 2)))
    charge = float(0.5 * dt * effort * np.sum(actions ** 2))
    return {"total": track + charge, "tracking": track, "effort": charge}


def audit_runs(run_dir, protocol_path, data_dir):
    """Check predictions, trajectories and LQ identities without importing a controller."""
    root, data = Path(run_dir), Path(data_dir)
    seal = verify_seal(root)
    protocol_bytes = Path(protocol_path).read_bytes()
    protocol = json.loads(protocol_bytes)
    runs = json.loads((root / "runs.json").read_bytes())
    for key, value in (("protocol_sha256", sha(protocol_bytes)),
                       ("data_receipt_sha256", sha((data / "data_receipt.json").read_bytes()))):
        if runs[key] != value or seal[key] != value:
            raise ValueError(f"frozen identity mismatch: {key}")
    records = runs["records"]
    actual = [(r["seed"], r["head"], r["mask"], r["policy"]) for r in records]
    expected = list(itertools.product(protocol["seeds"], protocol["head_modes"],
                                      protocol["action_masks"], protocol["policies"]))
    if len(actual) != len(expected) or set(actual) != set(expected):
        raise ValueError("registered condition census incomplete or duplicated")
    prediction = _load_arrays(root / "predictions.npz")
    feature = _load_arrays(root / "projected_features.npz")["features"]
    labels = json.loads((data / "train_labels.json").read_bytes())["roles"]
    sources = json.loads((data / "sources.json").read_bytes())["rows"]
    if runs["source_ids"] != [s["source_id"] for s in sources]:
        raise ValueError("prediction source order differs from frozen inputs")
    probabilities = prediction["probabilities"]
    if probabilities.shape != (len(records), len(sources), 4):
        raise ValueError("prediction shape differs from registered census")
    maxima = Counter()
    scalar_checks, successful, failures = 0, 0, []

    def close(name, got, wanted, tolerance=2e-8):
        nonlocal scalar_checks
        got, wanted = np.asarray(got), np.asarray(wanted)
        if got.shape != wanted.shape or not np.isfinite(got).all() or not np.isfinite(wanted).all():
            raise ValueError(f"nonfinite or mismatched independent check: {name}")
        error = float(np.max(np.abs(got - wanted))) if got.size else 0.0
        maxima[name] = max(maxima[name], error)
        scalar_checks += got.size
        if error > tolerance * (1 + float(np.max(np.abs(wanted)))):
            raise ValueError(f"independent {name} mismatch: {error}")

    dt, effort = protocol["h"], protocol["effort_price"]
    oracle_values = {}
    for number, info in enumerate(runs["initial_order"]):
        if info["status"] != "completed":
            continue
        vector, meta = _checkpoint_vector(root / info["path"])
        p = len(vector) // 3
        predicted, _, _ = _probability_and_gradient(vector[:p], info["head"], feature)
        close("initial_checkpoint_probability", prediction["initial_probabilities"][number], predicted, 2e-12)
        if meta["step_count"] != protocol["warmup_steps"] or meta["state_sha256"] != info["state_sha256"]:
            raise ValueError("initial full-state identity or training step differs")
    for index, record in enumerate(records):
        if record["status"] not in ("completed", "ok", "success"):
            failures.append({"run_id": record["run_id"], "status": record["status"], "error": record.get("error")})
            if not np.isnan(probabilities[index]).all():
                raise ValueError("failed condition silently retains scored predictions")
            continue
        successful += 1
        name = record["run_id"]
        initial = f"seed{record['seed']}-{record['head']}"
        ref = _load_arrays(root / "references" / f"{initial}.npz")
        policy = _load_arrays(root / "controllers" / f"{name}.npz")
        live = _load_arrays(root / "trajectories" / f"{name}.npz")
        tangent = _load_arrays(root / "tangent" / f"{name}.npz")
        oracle_name = f"{initial}-{record['mask']}-full"
        oracle = _load_arrays(root / "controllers" / f"{oracle_name}.npz")
        horizon, dim = ref["A"].shape[:2]
        parameter_count = dim // 3
        checkpoint, checkpoint_meta = _checkpoint_vector(root / record["paths"]["checkpoint"])
        close("complete_final_checkpoint", live["states"][-1], checkpoint, 0)
        if (checkpoint_meta["step_count"] != protocol["warmup_steps"] + horizon
                or checkpoint_meta["state_sha256"] != record["final_state_sha256"]):
            raise ValueError("final full-state identity or training step differs")
        close("initial_state", live["states"][0], ref["reference_states"][0])
        direct, _, _ = _probability_and_gradient(live["states"][-1, :parameter_count], record["head"], feature)
        close("final_probability", probabilities[index], direct, 2e-12)
        for k, state in enumerate(live["states"]):
            observed = []
            momentum = state[parameter_count:2 * parameter_count]
            for role in ("current_probe", "old_probe"):
                rows = labels[role]
                _, loss, gradient = _probability_and_gradient(state[:parameter_count], record["head"],
                                                             feature[rows["indices"]], rows["labels"])
                observed.append((loss, float(gradient @ momentum)))
            close("nonlinear_observation", live["observations"][k],
                  [observed[0][0], observed[1][0], observed[0][1], observed[1][1]], 2e-11)
        close("nonlinear_fields", live["fields"], live["observations"][:, :2] - ref["reference_observations"][:, :2])
        nonlinear_cost = _cost(live["fields"], live["actions"], policy["target"], dt, effort)
        for key, value in nonlinear_cost.items():
            close("nonlinear_cost_" + key, record["cost"][key], value)
        close("orthonormal_actions", policy["B"].T @ policy["B"], np.eye(policy["B"].shape[1]))
        expected_e = np.vstack([dt * policy["B"], np.zeros((2 * parameter_count, policy["B"].shape[1]))])
        close("physical_action_map", policy["E"], np.tile(expected_e / ref["state_scales"][:, None], (horizon, 1, 1)))
        z, u = tangent["states"], tangent["actions"]
        zp, up = tangent["projected_states"], tangent["projected_actions"]
        close("tangent_initial", z[0], np.zeros(dim))
        advantage = 0.0
        q_values, bound, discrepancies = [], [0.0], [0.0]
        for k in range(horizon):
            y = policy["Cobs"][k] @ z[k]
            close("full_path_feedback", u[k], -policy["K"][k] @ y + policy["offset"][k])
            close("projected_feedback", up[k], -policy["K"][k] @ zp[k] + policy["offset"][k])
            close("tangent_transition", z[k + 1], ref["A"][k] @ z[k] + policy["E"][k] @ u[k])
            close("projected_transition", zp[k + 1], policy["F"][k] @ zp[k] + policy["D"][k] @ up[k])
            residual = policy["Cobs"][k + 1] @ ref["A"][k] - policy["F"][k] @ policy["Cobs"][k]
            q = float(np.linalg.norm(residual @ z[k]))
            q_values.append(q)
            bound.append(float(np.linalg.norm(policy["F"][k] - policy["D"][k] @ policy["K"][k], 2) * bound[-1] + q))
            discrepancies.append(float(np.linalg.norm(policy["Cobs"][k + 1] @ z[k + 1] - zp[k + 1])))
            difference = u[k] + oracle["K"][k] @ z[k] - oracle["offset"][k]
            advantage += float(0.5 * difference @ oracle["riccati_W"][k] @ difference)
        fields = np.array([ref["C_extended"][k, :2] @ z[k] for k in range(horizon + 1)])
        tangent_cost = _cost(fields, u, policy["target"], dt, effort)
        value = float(oracle["riccati_constant"][0])
        oracle_values[(record["seed"], record["head"], record["mask"])] = value
        close("bellman_advantage_identity", tangent_cost["total"] - value, advantage)
        close("reachable_forcing", tangent["forcing"], q_values)
        close("transfer_recursion", tangent["field_transfer_bound"], bound)
        close("field_discrepancy", tangent["field_discrepancy"], discrepancies)
        if np.max(np.asarray(discrepancies) - np.asarray(bound)) > 2e-8 * (1 + np.max(bound)):
            raise ValueError("same-policy deterministic transfer bound violated")
        if "tangent" in record:
            close("stored_tangent_cost", record["tangent"]["cost"]["total"], tangent_cost["total"])
            close("stored_advantage", record["tangent"]["bellman_advantage_sum"], advantage)
    nested = []
    for seed, head in itertools.product(protocol["seeds"], protocol["head_modes"]):
        narrow, broad = oracle_values.get((seed, head, "bias")), oracle_values.get((seed, head, "all"))
        if narrow is None or broad is None:
            nested.append({"seed": seed, "head": head, "status": "unavailable_condition_failure"})
        else:
            if broad > narrow + 2e-8 * (1 + abs(narrow)):
                raise ValueError("nested full-state oracle ordering violated")
            nested.append({"seed": seed, "head": head, "bias_value": narrow, "all_value": broad,
                           "actuation_penalty": narrow - broad})
    return {"schema": "hepta.cell-field-independent-run-audit.v1", "records": len(records),
            "successful_records": successful, "failed_records": failures,
            "sealed_files_verified": len(seal["files"]), "scalar_equalities_checked": scalar_checks,
            "max_absolute_errors": dict(maxima), "nested_oracle_comparisons": nested,
            "final_labels_opened": False, "policy_solver_imported": False,
            "pre_evaluation_seal_sha256": sha((root / "pre_evaluation_seal.json").read_bytes()),
            "auditor_sha256": sha(Path(__file__).read_bytes())}


def audit_evaluation(run_dir, data_dir, protocol_path, evaluation_file):
    """Recompute heldout metrics and paired intervals without importing evaluation."""
    root, data = Path(run_dir), Path(data_dir)
    seal = verify_seal(root)
    runs = json.loads((root / "runs.json").read_bytes())
    plan = json.loads(Path(protocol_path).read_bytes())
    result = json.loads(Path(evaluation_file).read_bytes())
    receipt = json.loads((data / "data_receipt.json").read_bytes())
    if (sha(Path(protocol_path).read_bytes()) != seal["protocol_sha256"]
            or result["pre_evaluation_seal_sha256"] != sha((root / "pre_evaluation_seal.json").read_bytes())
            or sha((data / "data_receipt.json").read_bytes()) != runs["data_receipt_sha256"]):
        raise ValueError("evaluation or protocol identity differs from frozen run")
    label_bytes = (data / "final_labels.json").read_bytes()
    if sha(label_bytes) != receipt["files"]["final_labels.json"]["sha256"] or sha(label_bytes) != result["final_labels_sha256"]:
        raise ValueError("final scoring labels changed")
    final = json.loads(label_bytes)["roles"]
    prediction = _load_arrays(root / "predictions.npz")
    saved = {(r["run_id"], r["role"]): r for r in result["records"]}
    saved_initial = {(r["initial_index"], r["role"]): r for r in result["initial"]}
    if len(saved) != 3 * len(runs["records"]) or len(saved_initial) != 3 * len(runs["initial_order"]):
        raise ValueError("final evaluation census is incomplete or duplicate")
    fields = ("rows", "accuracy", "balanced_accuracy", "nll", "brier")
    scores, bootstrap_indices, checked, largest = {}, {}, 0, 0.0
    minimum_probability, floor_count = 1.0, 0

    def compare(value, expected):
        nonlocal checked, largest
        value, expected = np.asarray(value), np.asarray(expected)
        if value.shape != expected.shape or not np.isfinite(value).all() or not np.isfinite(expected).all():
            raise ValueError("nonfinite or mismatched final summary")
        difference = float(np.max(np.abs(value - expected)))
        checked += value.size
        largest = max(largest, difference)
        if difference > 2e-12 * (1 + float(np.max(np.abs(expected)))):
            raise ValueError(f"independent final metric differs: {difference}")

    def summarize(probability, labels):
        nonlocal minimum_probability, floor_count
        y = np.asarray(labels, dtype=np.int64)
        if (probability.shape != (len(y), 4) or not np.isfinite(probability).all()
                or np.any(probability < 0) or not np.allclose(probability.sum(axis=1), 1, atol=1e-12, rtol=0)):
            raise ValueError("invalid final probability rows")
        correct = np.equal(np.argmax(probability, axis=1), y).astype(float)
        gold = probability[np.arange(len(y)), y]
        minimum_probability = min(minimum_probability, float(gold.min()))
        floor_count += int(np.sum(gold < np.finfo(float).tiny))
        loss = -np.log(np.maximum(gold, np.finfo(float).tiny))
        brier = np.mean(np.square(probability - np.eye(4)[y]).sum(axis=1))
        summary = (len(y), correct.mean(), np.mean([correct[y == c].mean() for c in range(4)]), loss.mean(), brier)
        return summary, loss, correct

    rng = np.random.default_rng(plan["bootstrap_seed"])
    for role in ("old_test", "future_may", "future_june"):
        labels = np.asarray(final[role]["labels"])
        indices = np.asarray(final[role]["indices"])
        if len(set(indices.tolist())) != len(indices) or len(np.unique(labels)) != 4:
            raise ValueError("final source duplication or missing declared class")
        bootstrap_indices[role] = np.concatenate([
            rng.choice(np.where(labels == label)[0], size=(plan["bootstrap_replicates"], int(np.sum(labels == label))))
            for label in range(4)], axis=1)
        initial_summaries = {}
        for number, initial in enumerate(runs["initial_order"]):
            if initial["status"] != "completed":
                if saved_initial[(number, role)].get("metrics", "missing") is not None:
                    raise ValueError("failed initial state was scored")
                continue
            summary, _, _ = summarize(prediction["initial_probabilities"][number, indices], labels)
            compare([saved_initial[(number, role)][key] for key in fields], summary)
            initial_summaries[number] = summary
        for number, record in enumerate(runs["records"]):
            expected = saved[(record["run_id"], role)]
            if record["status"] != "completed":
                if expected.get("metrics", "missing") is not None:
                    raise ValueError("failed control condition was scored")
                continue
            summary, losses, correct = summarize(prediction["probabilities"][number, indices], labels)
            compare([expected[key] for key in fields], summary)
            baseline = initial_summaries[record["initial_index"]]
            compare(expected["nll_change_from_warmup"], summary[3] - baseline[3])
            compare(expected["accuracy_change_from_warmup"], summary[1] - baseline[1])
            scores[(record["seed"], record["head"], record["mask"], record["policy"], role)] = (losses, correct)
    contrasts_checked, contrast_keys = 0, set()
    for comparison in result["contrasts"]:
        head, mask, role = comparison["head"], comparison["mask"], comparison["role"]
        left, right = comparison["left"], comparison["right"]
        keys = [(seed, head, mask, method, role) for seed in plan["seeds"] for method in (left, right)]
        contrast_key = (head, mask, role, left, right, comparison.get("metric"))
        if contrast_key in contrast_keys:
            raise ValueError("duplicate comparison in final evaluation")
        contrast_keys.add(contrast_key)
        if any(key not in scores for key in keys):
            if comparison["status"] != "incomplete_registered_conditions":
                raise ValueError("incomplete comparison silently excludes failed seed")
            continue
        column = {"nll": 0, "accuracy": 1}[comparison["metric"]]
        difference = np.mean(np.array([scores[(seed, head, mask, left, role)][column]
                                      - scores[(seed, head, mask, right, role)][column]
                                      for seed in plan["seeds"]]), axis=0)
        resampled = difference[bootstrap_indices[role]].sum(axis=1) / len(difference)
        compare(comparison["difference_left_minus_right"], difference.mean())
        compare(comparison["pointwise_percentile_95"], np.percentile(resampled, [2.5, 97.5]))
        contrasts_checked += 1
    wanted_comparisons = set()
    for head, mask, role, pair in itertools.product(plan["head_modes"], plan["action_masks"],
            ("old_test", "future_may", "future_june"),
            (("loss2", "myopic"), ("extended", "loss2"), ("full", "loss2"), ("loss2", "zero"))):
        available = all((seed, head, mask, policy, role) in scores
                        for seed in plan["seeds"] for policy in pair)
        for metric in (("nll", "accuracy") if available else (None,)):
            wanted_comparisons.add((head, mask, role, *pair, metric))
    if wanted_comparisons != contrast_keys:
        raise ValueError("comparison census changed or omitted a registered pair")
    return {"schema": "hepta.cell-field-independent-evaluation-audit.v1",
            "scored_condition_roles": len(saved), "scored_initial_roles": len(saved_initial),
            "contrasts_recomputed": contrasts_checked, "scalar_equalities_checked": checked,
            "max_absolute_difference": largest, "minimum_gold_probability": minimum_probability,
            "nll_underflow_floor_count": floor_count,
            "interval_scope": "pointwise stratified source bootstrap, conditional on the same fitted seeds",
            "evaluator_imported": False, "evaluation_sha256": sha(Path(evaluation_file).read_bytes()),
            "auditor_sha256": sha(Path(__file__).read_bytes())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True)
    parser.add_argument("--archive")
    parser.add_argument("--runs")
    parser.add_argument("--protocol")
    parser.add_argument("--evaluation")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.runs:
        if not args.protocol:
            parser.error("--runs requires --protocol")
        result = (audit_evaluation(args.runs, args.data, args.protocol, args.evaluation)
                  if args.evaluation else audit_runs(args.runs, args.protocol, args.data))
    else:
        if not args.archive:
            parser.error("input audit requires --archive")
        result = audit_inputs(args.data, args.archive)
    Path(args.output).write_bytes(canonical(result) + b"\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
