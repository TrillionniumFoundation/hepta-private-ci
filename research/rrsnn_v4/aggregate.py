"""Paired seed-by-scenario inference over a complete, frozen v4 evaluation matrix.

Latent paths and terminal query draws remain nested observations. The bootstrap
resamples the two crossed factors (training seed and scenario/value group), not
the number of neural paths or the number of repeated deterministic executions.
"""

from pathlib import Path
import argparse
import gzip
import json

import numpy as np

from .prepare_data import DATA_SPEC, load_data, sha, validate_freeze, write_once
from .task import scenario_digest


ROOT = Path(__file__).resolve().parent
TRAINING_SEEDS = (101, 211, 307, 401, 503)
DATASETS = ("test", "shift", "paired")
BOOTSTRAP_SEEDS = {"test": 65401001, "shift": 65401002, "paired": 65401003}
BOOTSTRAP_DRAWS = 10_000
LATENT_REPLAYS = 4
QUERY_DRAWS = 4
PRIMARY_COMPARATOR = "ctrnn_state_cpu"
SECONDARY_BASELINES = ("lif", "alif", "resource_lif", "ctrnn", "ctrnn_state",
                       "ctrnn_upper_state", "alif_analog", "ctrnn_analog")
SECONDARY_RULE = "Minimum mean best_validation_nll across the five frozen training seeds; lexical variant name breaks exact ties. No heldout metric is read."
CONDITIONS = ("A0", "A2", "B0", "B2")
TOLERANCE = 1e-10
FIELDS = ("expected_utility", "normalized_utility", "high_value_delivery_fraction",
          "budget_spent", "task_output_pulses", "internal_spikes", "renewals")


def group_layout(metadata, paired):
    groups = sorted({int(row["group"]) for row in metadata})
    indices = [[i for i, row in enumerate(metadata) if int(row["group"]) == group]
               for group in groups]
    for subset in indices:
        conditions = [metadata[i]["condition"] for i in subset]
        if paired and sorted(conditions) != list(CONDITIONS):
            raise ValueError("A counterfactual group must keep all four conditions")
        if not paired and len(subset) != 1:
            raise ValueError("Independent synthetic scenarios must have unique groups")
    return groups, indices


def group_average(values, indices):
    """Average conditions within groups after paths/queries have been averaged."""
    values = np.asarray(values, dtype=np.float64)
    if values.ndim != 2 or values.shape[0] != len(TRAINING_SEEDS):
        raise ValueError("Expected one value per training seed and scenario")
    return np.stack([values[:, rows].mean(axis=1) for rows in indices], axis=1)


class PairedBootstrap:
    def __init__(self, groups, seed, draws=BOOTSTRAP_DRAWS):
        if groups < 1 or draws < 1:
            raise ValueError("Positive group and bootstrap counts required")
        random = np.random.default_rng(seed)
        self.groups, self.seed, self.draws = groups, int(seed), draws
        self.seed_weights = random.multinomial(len(TRAINING_SEEDS),
                                              np.full(len(TRAINING_SEEDS), 1/len(TRAINING_SEEDS)), draws)
        self.group_weights = random.multinomial(groups, np.full(groups, 1/groups), draws)

    def samples(self, values):
        values = np.asarray(values, dtype=np.float64)
        if values.shape != (len(TRAINING_SEEDS), self.groups) or not np.isfinite(values).all():
            raise ValueError("Bootstrap input must be a finite seed-by-group matrix")
        seed_means = self.seed_weights @ values
        return np.einsum("bg,bg->b", seed_means, self.group_weights)/(len(TRAINING_SEEDS)*self.groups)

    def summary(self, values):
        samples = self.samples(values)
        interval = np.quantile(samples, [.025, .975], method="linear")
        return {"mean": float(np.mean(values)), "ci95": interval.tolist(),
                "training_seed_means": np.mean(values, axis=1).tolist()}


def expected_signatures(scenarios, metadata, oracle):
    return [(scenario_digest(scenario), int(item["group"]), item["condition"], float(optimum))
            for scenario, item, optimum in zip(scenarios, metadata, oracle)]


def load_block(variant, checkpoints, dataset, context, selection_hash, freeze_hash, sources):
    scenarios, metadata, oracle, manifest, freeze_path = context
    count = len(scenarios)
    signatures = expected_signatures(scenarios, metadata, oracle)
    block = {field: np.empty((len(TRAINING_SEEDS), count, LATENT_REPLAYS)) for field in FIELDS}
    block["realized"] = np.empty((len(TRAINING_SEEDS), count, LATENT_REPLAYS, QUERY_DRAWS))
    block["pre_shock_outputs"] = np.empty((len(TRAINING_SEEDS), count, LATENT_REPLAYS))
    block["state_numeric_bytes_per_episode"] = []
    block["query_witness"] = None
    block["initial_state_pairing_verified"] = dataset == "paired"
    block["training"] = []
    data_files = next(item["files"] for item in manifest["splits"] if item["name"] == dataset)
    for seed_index, training_seed in enumerate(TRAINING_SEEDS):
        checkpoint = checkpoints[training_seed]
        receipt_path = checkpoint.parent / "training.json"
        receipt = json.loads(receipt_path.read_text())
        if (receipt.get("status") != "completed" or receipt.get("variant") != variant
                or receipt.get("seed") != training_seed or receipt.get("checkpoint_sha256") != sha(checkpoint)
                or receipt.get("holdout_opened_by_training") is not False):
            raise ValueError(f"Invalid training receipt: {receipt_path}")
        training_protocol = ROOT / "experiment_protocol.json"
        if receipt.get("protocol_sha256") != sha(training_protocol):
            raise ValueError("Training receipt does not match the training protocol")
        sources[str(receipt_path.relative_to(ROOT))] = sha(receipt_path)
        block["training"].append({key: receipt.get(key) for key in
            ("seed", "updates", "best_validation_nll", "train_cpu_seconds", "train_seconds",
             "process_peak_rss_mib", "cpu_budget_target_seconds", "cpu_budget_overshoot_seconds",
             "resource_quality", "metadata")})
        for replay in range(LATENT_REPLAYS):
            filename = checkpoint.parent / f"evaluation_{dataset}_rep{replay}.json.gz"
            with gzip.open(filename, "rt", encoding="utf-8") as handle:
                payload = json.load(handle)
            identity, evaluation = payload["identity"], payload["evaluation"]
            required = {"variant": variant, "training_seed": training_seed,
                        "checkpoint_sha256": sha(checkpoint), "protocol_sha256": freeze_hash,
                        "training_protocol_sha256": sha(ROOT / "experiment_protocol.json"),
                        "selection_sha256": selection_hash, "evaluator_sha256": sha(ROOT / "evaluate.py"),
                        "task_sha256": sha(ROOT / "task.py"),
                        "data_manifest_sha256": sha(ROOT / "data" / "manifest.json"),
                        "source_files": data_files, "dataset": dataset, "latent_replay": replay,
                        "primary_comparator": PRIMARY_COMPARATOR, "real_future_window": False}
            if any(identity.get(key) != value for key, value in required.items()):
                raise ValueError(f"Evaluation identity differs: {filename}")
            if (evaluation.get("all_resource_invariants_passed") is not True
                    or evaluation.get("episodes") != count
                    or evaluation.get("query_draws_per_scenario") != QUERY_DRAWS):
                raise ValueError("Incomplete evaluation or resource validation")
            rows = evaluation["rows"]
            if len(rows) != count:
                raise ValueError("Evaluation row count differs from the source data")
            witness = []
            for i, row in enumerate(rows):
                signature = (row["scenario_digest"], int(row["group"]), row["condition"],
                             float(row["oracle_expected_utility"]))
                if signature != signatures[i] or row["scenario_index"] != i:
                    raise ValueError("Rows are not matched to the original scenario and expected oracle")
                if row["training_seed"] != training_seed or row["latent_replay"] != replay:
                    raise ValueError("Raw row seed/replay identity differs")
                expected = float(row["expected_utility"])
                optimum = float(oracle[i])
                ratio = expected/optimum if optimum > 1e-12 else 1.
                if expected < -TOLERANCE or expected > optimum+1e-8 or abs(ratio-row["normalized_utility"]) > TOLERANCE:
                    raise ValueError("Expected utility violates its expected DP oracle")
                if (len(row["query_seeds"]) != QUERY_DRAWS or len(row["query_bits"]) != QUERY_DRAWS
                        or len(row["realized_query_utility"]) != QUERY_DRAWS):
                    raise ValueError("Four nested terminal query draws are required")
                witness.append((row["query_seeds"], row["query_bits"]))
                for field in FIELDS:
                    block[field][seed_index, i, replay] = float(row[field])
                block["realized"][seed_index, i, replay] = row["realized_query_utility"]
                block["pre_shock_outputs"][seed_index, i, replay] = sum(
                    output["emitted_at"] < scenarios[i].shock_time-1e-9 for output in row["delivered"])
            if block["query_witness"] is None:
                block["query_witness"] = witness
            elif block["query_witness"] != witness:
                raise ValueError("Observer queries changed across training seeds or latent paths")
            if dataset == "paired":
                if evaluation.get("paired_initial_state_equal") is not True:
                    raise ValueError("Strict counterfactual pre-cue state equality was not verified")
                receipts = evaluation.get("paired_initial_state_receipts", [])
                groups, subsets = group_layout(metadata, True)
                if len(receipts) != len(groups):
                    raise ValueError("Missing counterfactual initial-state witnesses")
                for subset in subsets:
                    if len({rows[i]["initial_state_sha256"] for i in subset}) != 1:
                        raise ValueError("Counterfactual conditions have unequal pre-cue neural state")
                    if len({json.dumps(witness[i]) for i in subset}) != 1:
                        raise ValueError("Counterfactual conditions have different future query draws")
            block["state_numeric_bytes_per_episode"].append(evaluation["state_storage"]["bytes_per_episode"])
            sources[str(filename.relative_to(ROOT))] = sha(filename)
    for field in (*FIELDS, "realized", "pre_shock_outputs"):
        if not np.isfinite(block[field]).all():
            raise ValueError("Nonfinite recorded utility or cost")
    return block


def block_summary(block, indices, bootstrap):
    result = {"normalized_expected_utility": bootstrap.summary(group_average(
                block["normalized_utility"].mean(axis=2), indices)),
              "expected_utility": bootstrap.summary(group_average(
                block["expected_utility"].mean(axis=2), indices)),
              "realized_query_utility": bootstrap.summary(group_average(
                block["realized"].mean(axis=(2, 3)), indices)),
              "state_numeric_bytes_per_episode": sorted(set(block["state_numeric_bytes_per_episode"])),
              "state_storage_scope": "Resident numeric encoder state only; excludes weights, RNG objects, containers, task queues, temporaries and process/framework overhead.",
              "initial_state_pairing_verified": block["initial_state_pairing_verified"],
              "training": block["training"]}
    for field in ("high_value_delivery_fraction", "budget_spent", "task_output_pulses",
                  "internal_spikes", "renewals", "pre_shock_outputs"):
        result[field+"_mean"] = float(block[field].mean())
    return result


def compare(candidate, baseline, indices, bootstrap):
    if candidate["query_witness"] != baseline["query_witness"]:
        raise ValueError("Model comparison does not share terminal queries")
    raw_delta = candidate["expected_utility"]-baseline["expected_utility"]
    realized_delta = candidate["realized"]-baseline["realized"]
    def summarize(values):
        return bootstrap.summary(group_average(values, indices))
    return {
        "normalized_expected_gain_percentage_points": summarize(100*(
            candidate["normalized_utility"]-baseline["normalized_utility"]).mean(axis=2)),
        "expected_utility_gain": summarize(raw_delta.mean(axis=2)),
        "realized_query_utility_gain": summarize(realized_delta.mean(axis=(2, 3))),
        "high_value_delivery_gain_percentage_points": summarize(100*(
            candidate["high_value_delivery_fraction"]-baseline["high_value_delivery_fraction"]).mean(axis=2)),
        "expected_pathwise_negative_transfer_fraction": summarize((raw_delta < -TOLERANCE).mean(axis=2)),
        "expected_pathwise_positive_transfer_fraction": float((raw_delta > TOLERANCE).mean()),
        "expected_pathwise_tie_fraction": float((np.abs(raw_delta) <= TOLERANCE).mean()),
        "realized_path_query_negative_transfer_fraction": summarize((realized_delta < -TOLERANCE).mean(axis=(2, 3))),
        "negative_transfer_definition": "Compare each matched training-seed/scenario/latent-replay pair before averaging. Realized negatives additionally match the query draw. These are finite-path outcomes, not a claim that latent or query repeats are independent test scenarios.",
    }


def paired_counterfactual(block, metadata, bootstrap):
    groups, subsets = group_layout(metadata, True)
    cells = np.empty((len(TRAINING_SEEDS), len(groups), len(CONDITIONS)))
    before = np.empty_like(cells)
    for group_index, subset in enumerate(subsets):
        for row in subset:
            condition = CONDITIONS.index(metadata[row]["condition"])
            cells[:, group_index, condition] = block["expected_utility"][:, row, :].mean(axis=1)
            before[:, group_index, condition] = block["pre_shock_outputs"][:, row, :].mean(axis=1)
    interaction = (cells[:, :, 3]-cells[:, :, 2])-(cells[:, :, 1]-cells[:, :, 0])
    return {"expected_utility_by_condition": {condition: bootstrap.summary(cells[:, :, i])
                                              for i, condition in enumerate(CONDITIONS)},
            "pre_shock_output_count_by_condition": {condition: float(before[:, :, i].mean())
                                                    for i, condition in enumerate(CONDITIONS)},
            "shock_interaction_B_minus_A": bootstrap.summary(interaction),
            "interaction_definition": "(B2-B0)-(A2-A0), computed in raw expected utility; all four conditions remain in the same resampled value group."}, interaction


def selected_checkpoints(selection):
    result = {}
    for relative, expected_sha in selection.get("checkpoints", {}).items():
        path = (ROOT / relative).resolve()
        path.relative_to(ROOT)
        if path.name != "model.pt" or not path.parent.name.startswith("seed_") or sha(path) != expected_sha:
            raise ValueError("Invalid or changed checkpoint in frozen selection")
        variant, seed = path.parent.parent.name, int(path.parent.name[5:])
        if seed in result.setdefault(variant, {}):
            raise ValueError("Repeated selected training seed")
        result[variant][seed] = path
    if PRIMARY_COMPARATOR not in result or "rr_full" not in result:
        raise ValueError("Primary RR candidate and locked CPU/state comparator are required")
    for variant, paths in result.items():
        if set(paths) != set(TRAINING_SEEDS):
            raise ValueError(f"Incomplete five-seed checkpoint set: {variant}")
    return result


def freeze_selection(freeze_path, selection_path):
    """Freeze checkpoints and the secondary comparator using validation only."""
    validate_freeze(freeze_path)
    training_path = ROOT / "experiment_protocol.json"
    protocol = json.loads(training_path.read_text())
    if protocol["seeds"] != list(TRAINING_SEEDS):
        raise ValueError("Training seed allocation differs from the frozen inference rule")
    for name, expected in protocol["frozen_files"].items():
        if sha(ROOT / name) != expected:
            raise ValueError(f"Frozen training identity changed: {name}")
    variants = protocol["variants"]+list(protocol.get("cpu_matched_variants", {}))
    if len(variants) != len(set(variants)) or not set(SECONDARY_BASELINES).issubset(variants):
        raise ValueError("The predeclared secondary comparator set is incomplete")
    destination = Path(selection_path)
    if not destination.exists() and any((ROOT / "results").glob("*/seed_*/evaluation_*.json.gz")):
        raise ValueError("A first selection cannot be frozen after heldout evaluation")
    training_hash = sha(training_path)
    checkpoints, validation, receipts = {}, {}, {}
    for variant in variants:
        values = []
        for seed in TRAINING_SEEDS:
            directory = ROOT / "results" / variant / f"seed_{seed}"
            receipt_path, checkpoint = directory / "training.json", directory / "model.pt"
            receipt = json.loads(receipt_path.read_text())
            if (receipt.get("status") != "completed" or receipt.get("variant") != variant
                    or receipt.get("seed") != seed or receipt.get("protocol_sha256") != training_hash
                    or receipt.get("checkpoint_sha256") != sha(checkpoint)
                    or receipt.get("holdout_opened_by_training") is not False):
                raise ValueError(f"Incomplete or incompatible training receipt: {receipt_path}")
            values.append(float(receipt["best_validation_nll"]))
            checkpoints[str(checkpoint.relative_to(ROOT))] = sha(checkpoint)
            receipts[str(receipt_path.relative_to(ROOT))] = sha(receipt_path)
        if not np.isfinite(values).all():
            raise ValueError("Nonfinite validation score")
        validation[variant] = {"per_seed_best_validation_nll": values, "mean": float(np.mean(values))}
    secondary = min(SECONDARY_BASELINES, key=lambda name: (validation[name]["mean"], name))
    result = {"schema": "rrsnn-v4-validation-selection-1", "protocol_sha256": sha(freeze_path),
              "training_protocol_sha256": training_hash, "holdout_metrics_used_for_selection": False,
              "primary_comparator": PRIMARY_COMPARATOR, "secondary_comparator": secondary,
              "secondary_rule": SECONDARY_RULE, "secondary_eligible": list(SECONDARY_BASELINES),
              "validation": validation, "checkpoints": checkpoints,
              "training_receipts_sha256": receipts, "selector_sha256": sha(__file__)}
    destination.parent.mkdir(parents=True, exist_ok=True)
    write_once(destination, (json.dumps(result, indent=2, sort_keys=True, allow_nan=False)+"\n").encode())
    return result


def aggregate(freeze_path, selection_path, destination=None):
    protocol = validate_freeze(freeze_path)
    selection = json.loads(Path(selection_path).read_text())
    freeze_hash, selection_hash = sha(freeze_path), sha(selection_path)
    if selection.get("protocol_sha256") != freeze_hash or selection.get("holdout_metrics_used_for_selection") is not False:
        raise ValueError("Selection was not frozen independently of heldout outcomes")
    if selection.get("training_protocol_sha256") != sha(ROOT / "experiment_protocol.json"):
        raise ValueError("Selection training protocol identity changed")
    # Idempotently reconstruct using training/validation receipts only. This
    # verifies the declared rule without selecting a winner from heldout data.
    if freeze_selection(freeze_path, selection_path) != selection:
        raise ValueError("Selected secondary comparator or checkpoint set changed")
    for name, expected in protocol.get("frozen_files", {}).items():
        if sha(ROOT / name) != expected:
            raise ValueError(f"Pre-data frozen source changed: {name}")
    checkpoints = selected_checkpoints(selection)
    secondary = selection["secondary_comparator"]
    if secondary not in checkpoints:
        raise ValueError("The validation-selected secondary comparator is absent")
    sources = {str(Path(freeze_path).resolve().relative_to(ROOT)): freeze_hash,
               str(Path(selection_path).resolve().relative_to(ROOT)): selection_hash,
               "aggregate.py": sha(__file__), "data/manifest.json": sha(ROOT / "data" / "manifest.json"),
               "experiment_protocol.json": sha(ROOT / "experiment_protocol.json")}
    result = {"schema": "rrsnn-v4-paired-aggregate-1", "primary_comparator": PRIMARY_COMPARATOR,
              "secondary_comparator": secondary,
              "secondary_selection_scope": "Read from frozen validation selection; never selected from heldout scores.",
              "training_seeds": list(TRAINING_SEEDS), "latent_replays_per_scenario": LATENT_REPLAYS,
              "query_draws_per_scenario": QUERY_DRAWS,
              "bootstrap": {"draws": BOOTSTRAP_DRAWS, "seeds": BOOTSTRAP_SEEDS,
                "interval": "pointwise 95% percentile interval, linear quantile",
                "unit": "Crossed training seed and scenario/value group; all conditions stay within their group. Shared resampling weights across every model comparison in a dataset.",
                "nesting": "Average four latent paths per training seed/scenario before expected-utility inference. For realized utility also average four queries. Negative indicators are formed before those averages.",
                "qualification": "Conditional on the four recorded paths and query draws; five training seeds provide limited information about training variability. Pointwise intervals make no family-wise significance claim."},
              "primary_metric": "Mean per-scenario expected utility divided by that scenario's expected DP optimum; differences in percentage points. Raw expected and realized utility are reported separately.",
              "real_future_window": False, "native_cell_scale_claim": False,
              "performance_scope": "Closed-loop synthetic task. Internal neural events and common communication outputs are separate quantities. Paired RR execution uses one-row streams, so evaluation wall times are not a fair architecture benchmark.",
              "datasets": {}, "sources_sha256": sources}
    for dataset in DATASETS:
        scenarios, arrays, metadata, manifest = load_data(dataset, freeze_path)
        if len(scenarios) != DATA_SPEC[dataset]["episodes"]:
            raise ValueError("Production sample count differs from the frozen specification")
        groups, indices = group_layout(metadata, dataset == "paired")
        bootstrap = PairedBootstrap(len(groups), BOOTSTRAP_SEEDS[dataset])
        context = (scenarios, metadata, arrays["oracle_utility"], manifest, freeze_path)
        blocks = {name: load_block(name, paths, dataset, context, selection_hash, freeze_hash, sources)
                  for name, paths in sorted(checkpoints.items())}
        entry = {"scenarios": len(scenarios), "resampled_value_groups": len(groups),
                 "expected_oracle_mean": float(arrays["oracle_utility"].mean()),
                 "models": {name: block_summary(block, indices, bootstrap) for name, block in blocks.items()},
                 "against_primary": {name: compare(block, blocks[PRIMARY_COMPARATOR], indices, bootstrap)
                                     for name, block in blocks.items() if name != PRIMARY_COMPARATOR}}
        if secondary is not None:
            entry["against_secondary"] = {name: compare(block, blocks[secondary], indices, bootstrap)
                                           for name, block in blocks.items() if name != secondary}
        if dataset == "paired":
            interactions = {}
            entry["counterfactual"] = {}
            for name, block in blocks.items():
                summary, interaction = paired_counterfactual(block, metadata, bootstrap)
                entry["counterfactual"][name] = summary
                interactions[name] = interaction
            entry["rr_full_shock_interaction_gain_vs_primary"] = bootstrap.summary(
                interactions["rr_full"]-interactions[PRIMARY_COMPARATOR])
        result["datasets"][dataset] = entry
    for path_map in checkpoints.values():
        for path in path_map.values():
            sources[str(path.relative_to(ROOT))] = sha(path)
    destination = Path(destination or ROOT / "results" / "aggregate.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    write_once(destination, (json.dumps(result, indent=2, sort_keys=True, allow_nan=False)+"\n").encode())
    return result


def validate_selection_development():
    """Exercise selection on labelled temporary receipts, never trained models."""
    import tempfile
    saved_root = ROOT
    passed = []
    with tempfile.TemporaryDirectory(prefix="rrv4-selection-development-") as temporary:
        try:
            globals()["ROOT"] = Path(temporary)
            (ROOT/"task.py").write_bytes((saved_root/"task.py").read_bytes())
            pre = ROOT/"pre_data_freeze.json"
            pre.write_text(json.dumps({"scope": "DEVELOPMENT_ONLY_RECEIPT_FIXTURES",
                "frozen_before_data": True, "task_sha256": sha(ROOT/"task.py"), "data_spec": DATA_SPEC}))
            variants = ["rr_full", *SECONDARY_BASELINES]
            full = ROOT/"experiment_protocol.json"
            full.write_text(json.dumps({"scope": "DEVELOPMENT_ONLY_RECEIPT_FIXTURES",
                "seeds": list(TRAINING_SEEDS), "variants": variants,
                "cpu_matched_variants": {PRIMARY_COMPARATOR: "ctrnn_state"},
                "frozen_files": {"task.py": sha(ROOT/"task.py")}}))
            for variant in variants+[PRIMARY_COMPARATOR]:
                for seed in TRAINING_SEEDS:
                    directory = ROOT/"results"/variant/f"seed_{seed}"
                    directory.mkdir(parents=True)
                    checkpoint = directory/"model.pt"
                    checkpoint.write_bytes(b"DEVELOPMENT RECEIPT FIXTURE, NOT A TRAINED CHECKPOINT")
                    score = 1. if variant in ("lif", "alif") else 2.
                    if variant in ("rr_full", PRIMARY_COMPARATOR):
                        score = .5  # Better scores outside the eligible set do not win.
                    (directory/"training.json").write_text(json.dumps({
                        "scope": "DEVELOPMENT_ONLY_RECEIPT_FIXTURES", "status": "completed",
                        "variant": variant, "seed": seed, "protocol_sha256": sha(full),
                        "checkpoint_sha256": sha(checkpoint), "holdout_opened_by_training": False,
                        "best_validation_nll": score}))
            selection_path = ROOT/"selection.json"
            selected = freeze_selection(pre, selection_path)
            assert selected["secondary_comparator"] == "alif"
            assert selected["primary_comparator"] == PRIMARY_COMPARATOR
            passed.append("eligible validation minimum with lexical tie and locked primary")
            assert freeze_selection(pre, selection_path) == selected
            passed.append("write-once selection is idempotent")
            marker = ROOT/"results"/"rr_full"/f"seed_{TRAINING_SEEDS[0]}"/"evaluation_test_rep0.json.gz"
            marker.write_bytes(b"DEVELOPMENT MARKER ONLY; NO TEST OUTCOMES")
            selection_path.unlink()
            try:
                freeze_selection(pre, selection_path)
            except ValueError:
                passed.append("first selection after a heldout evaluation is rejected")
            else:
                raise AssertionError("Post-holdout first selection was accepted")
        finally:
            globals()["ROOT"] = saved_root
    return passed


def validate_development():
    """Analytical fixtures only: no training or heldout task data are opened."""
    bootstrap = PairedBootstrap(3, 901801)
    one = np.ones((5, 3))
    assert bootstrap.summary(one)["ci95"] == [1., 1.]
    assert bootstrap.summary(one*0)["ci95"] == [0., 0.]
    varied = np.arange(15, dtype=float).reshape(5, 3)
    manual = np.asarray([sum(varied[s, g]*bootstrap.seed_weights[b, s]*bootstrap.group_weights[b, g]
                             for s in range(5) for g in range(3))/15 for b in range(12)])
    assert np.allclose(bootstrap.samples(varied)[:12], manual, rtol=0, atol=1e-12)
    metadata = [{"group": group, "condition": condition} for group in range(3) for condition in CONDITIONS]
    groups, indices = group_layout(metadata, True)
    assert groups == [0, 1, 2] and len(indices) == 3 and all(len(row) == 4 for row in indices)
    base = {field: np.full((5, 12, 4), 3.) for field in FIELDS}
    base.update(realized=np.full((5, 12, 4, 4), 3.), query_witness="same-observer",
                pre_shock_outputs=np.zeros((5, 12, 4)))
    candidate = {key: value.copy() if isinstance(value, np.ndarray) else value for key, value in base.items()}
    delta = np.asarray([-2., 1., 1., 1.])
    candidate["expected_utility"] += delta
    candidate["normalized_utility"] += delta/10
    candidate["realized"] += delta[None, None, :, None]
    comparison = compare(candidate, base, indices, bootstrap)
    assert comparison["expected_utility_gain"]["mean"] == .25
    assert comparison["expected_pathwise_negative_transfer_fraction"]["mean"] == .25
    assert comparison["realized_path_query_negative_transfer_fraction"]["mean"] == .25
    assert np.allclose(comparison["normalized_expected_gain_percentage_points"]["ci95"], [2.5, 2.5])
    for index, item in enumerate(metadata):
        candidate["expected_utility"][:, index, :] = {"A0": 4., "A2": 2., "B0": 4., "B2": 3.}[item["condition"]]
    summary, interaction = paired_counterfactual(candidate, metadata, bootstrap)
    assert np.array_equal(interaction, one) and summary["shock_interaction_B_minus_A"]["ci95"] == [1., 1.]
    try:
        group_layout(metadata[:-1], True)
    except ValueError:
        pass
    else:
        raise AssertionError("Incomplete counterfactual group was accepted")
    candidate["query_witness"] = "different-observer"
    try:
        compare(candidate, base, indices, bootstrap)
    except ValueError:
        pass
    else:
        raise AssertionError("Unpaired query streams were accepted")
    selection_checks = validate_selection_development()
    result = {"schema": "rrsnn-v4-aggregation-development-1", "all_passed": True,
              "bootstrap_draws": BOOTSTRAP_DRAWS,
              "checks": ["constant-effect exact intervals", "zero-effect exact intervals",
                         "crossed-resampling independently enumerated", "four conditions kept in each group",
                         "raw negative transfer before averaging", "queries nested within latent paths",
                         "expected and realized utility separate", "counterfactual interaction identity",
                         "incomplete group rejected", "different observer queries rejected", *selection_checks],
              "production_data_opened": False, "source_sha256": sha(__file__)}
    (ROOT / "aggregation_validation.json").write_text(json.dumps(result, indent=2)+"\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", type=Path)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--validate-development", action="store_true")
    parser.add_argument("--freeze-selection", action="store_true")
    args = parser.parse_args()
    if args.validate_development:
        print(json.dumps(validate_development()))
    elif args.freeze and args.selection and args.freeze_selection:
        result = freeze_selection(args.freeze, args.selection)
        print(json.dumps({"checkpoints": len(result["checkpoints"]), "secondary_comparator": result["secondary_comparator"]}))
    elif args.freeze and args.selection:
        result = aggregate(args.freeze, args.selection, args.output)
        print(json.dumps({"datasets": list(result["datasets"]), "primary_comparator": PRIMARY_COMPARATOR}))
    else:
        parser.error("Provide --freeze and --selection, or --validate-development")
