"""Read-only codec-d1 TRAIN artifact audit and descriptive ABBA accounting.

Only stdlib metadata/byte readers are imported. No data constructor, model,
observer, optimizer, statistical confirmation or timing-based selection runs.
Audit loose artifacts before replacing them with a verified lossless archive.
"""

import base64
import hashlib
import io
import json
import math
from pathlib import Path
import statistics
import zipfile


SYSTEMS = ("supervised", "anchor", "additive", "ndu")
SEEDS = (11, 23, 47)
ORDER = ("rowwise-png-v1", "local-png-codebook-v1",
         "local-png-codebook-v1", "rowwise-png-v1")


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


def _json(payload):
    return json.loads(payload, parse_constant=lambda value: _require(False, "nonfinite JSON: " + value))


def _number(value, label, *, positive=False):
    _require(type(value) in (int, float) and math.isfinite(value)
             and (value > 0 if positive else value >= 0), label)
    return value


def _artifact(root, row):
    path = (root / row["file"]).resolve()
    _require(path.is_relative_to(root.resolve()) and path.is_file(), "artifact escapes build or missing")
    payload = path.read_bytes()
    _require(_sha(payload) == row["sha256"] and len(payload) == row.get("bytes", len(payload)),
             "artifact hash/bytes mismatch: " + row["file"])
    return payload


def _model(root, row):
    return _artifact(root, {"file": row["model_file"], "sha256": row["model_sha256"]})


def _inputs(root, selection):
    receipt = selection["common"]["training_diagnostic"]
    _require(receipt["schema"] == "hepta.codec-train-inputs.v1"
             and receipt["actual_constructor_calls"] == ["train"]
             and receipt["official_held_out_constructed"] is False, "official data capability violation")
    _require(set(receipt["artifacts"]) == {"pool", "fit", "monitor"}, "TRAIN evidence roles")
    for role, item in receipt["artifacts"].items():
        _require(len(item["files"]) == 2, "NPZ and metadata evidence required")
        payloads = {Path(row["file"]).suffix: _artifact(root, row) for row in item["files"]}
        _require(set(payloads) == {".npz", ".json"}, "NPZ and metadata evidence required")
        metadata = _json(payloads[".json"])
        provenance = metadata["training_diagnostic"]
        _require(metadata["split"] == "train" and provenance["parent_split"] == "train"
                 and provenance["role"] == role and provenance["parent_manifest"] == receipt["parent"],
                 "monitor/fit provenance is not parent TRAIN")
    _require(selection["datasets"]["train"] == receipt["artifacts"]["fit"]["manifest"]
             and selection["datasets"]["validation"] == receipt["artifacts"]["monitor"]["manifest"],
             "engine internal-monitor manifest mismatch")
    return receipt


def _trace(root, evidence):
    payload = _artifact(root, evidence)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = archive.namelist()
        rows = evidence["rows"]
        expected = {f"{index:03d}.{suffix}" for index in range(rows) for suffix in ("png", "json")}
        _require(len(names) == len(set(names)) and set(names) == expected | {"rng.json", "manifest.json"},
                 "output trace member/row mismatch")
        identity = {}
        for name in sorted(expected | {"rng.json"}):
            value = archive.read(name)
            if name.endswith(".json"):
                decoded = _json(value)
                _require(value == _encoded(decoded), "noncanonical output/RNG JSON")
                if name != "rng.json":
                    png = archive.read(name[:-5] + ".png")
                    _require(decoded["png_sha256"] == _sha(png)
                             and base64.b64decode(decoded["png_base64"], validate=True) == png,
                             "PNG does not match actual JSON output")
            identity[name] = _sha(value)
    return identity


def _prefixes(root, selection):
    expected = {(system, seed, lr) for system in SYSTEMS for seed in SEEDS
                for lr in selection["plan"]["learning_rates"]}
    rows = selection["all_validation_candidates"]
    found, missing = {}, []
    for row in rows:
        key = (row["system"], row["seed"], row["learning_rate"])
        _require(key not in found and row["updates"] > 0, "duplicate or zero-update candidate")
        artifact = _json(_artifact(root, row["prefix_artifact"]))
        checkpoints = row["prefix_checkpoints"]
        steps = [entry["step"] for entry in checkpoints]
        fields = {"step", "loss", "mean_prefix_loss", "model_digest", "content_digest", "moments_digest",
                  "draws_sha256", "rng_state", "idx", "full_mask"}
        _require(all(set(entry) == fields for entry in checkpoints), "actual prefix witness fields")
        terminal = artifact["incomplete_terminal_state"]
        _require(steps in ([1], [1, 32]) and artifact == {"candidate": row["name"],
                 "checkpoints": checkpoints, "terminal_updates": row["updates"],
                 "complete": row["updates"] >= 32, "incomplete_terminal_state": terminal}
                 and (steps == [1, 32]) == row["prefix_equivalence_complete"]
                 and (row["updates"] >= 32) == (steps == [1, 32]), "invalid actual prefix receipt")
        _require((terminal is None) == (row["updates"] >= 32), "incomplete terminal state required")
        if terminal is not None:
            _require(set(terminal) == {"updates", "model_digest", "moments_digest", "rng_state", "draws_sha256"}
                     and terminal["updates"] == row["updates"] and terminal["model_digest"] == row["model_digest"],
                     "incomplete terminal model/update binding")
            if row["updates"] == 1:
                _require(all(terminal[key] == checkpoints[0][key] for key in terminal if key != "updates"),
                         "incomplete terminal differs from available step1")
        found[key] = {entry["step"]: entry for entry in checkpoints}
        if 32 not in found[key]:
            missing.append({"candidate": list(key), "terminal_state": terminal})
        _model(root, row)
    _require(set(found) == expected and len(rows) == 36, "complete 36-candidate search required")
    return found, missing


def _loads(build_paths):
    _require(1 <= len(build_paths) <= 4, "one to four completed ABBA prefix builds required")
    roots = [Path(value).resolve() for value in build_paths]
    roots = [value.parent if value.name == "selection.json" else value for value in roots]
    _require(len(set(roots)) == len(roots), "fresh distinct build directories required")
    return [(root, _json((root / "selection.json").read_bytes())) for root in roots]


def audit_builds(build_paths):
    """Raise on identity/cap faults; missing step32 is retained soft evidence."""
    builds = _loads(build_paths)
    first, first_root = builds[0][1], builds[0][0]
    plan = first["plan"]
    _require(plan["model_seeds"] == list(SEEDS) and plan["systems"] == list(SYSTEMS)
             and plan["cpu_seconds_per_system"] == 10 and plan["operator_units_per_system"] == 12_000_000_000
             and plan["data_profile"]["seeds"]["train"] == 304797655, "frozen codec-d1 scope/caps")
    analysis = plan["diagnostic_analysis"]
    _require(analysis["path"] == "training_diagnostics/codec-d1/analyze.py"
             and analysis["sha256"] == _sha(Path(__file__).read_bytes()), "analysis source binding")
    repeats = first["common"]["calibrations"]["11"]["raw_repeats"]["full"]
    reference = statistics.median([value for row in repeats for value in row["per_row_cost"]["cpu_ns"]])
    _number(reference, "positive first TRAIN reference", positive=True)
    identities, traces, prefixes, missing, retained = None, None, None, [], []
    for index, (root, selection) in enumerate(builds):
        slot, common = selection["training_diagnostic"], selection["common"]
        _require(selection["experiment_id"] == "codec-train-d1" and selection["test_opened"] is False
                 and selection["qualification_eligible"] is False and slot["qualification_eligible"] is False
                 and slot["schema"] == "hepta.codec-train-build.v1"
                 and slot["build_index"] == index and slot["codec_variant"] == ORDER[index], "fixed ABBA diagnostic identity")
        for key in ("plan", "plan_sha256", "source_commit", "sources", "freeze_sha256", "execution_commit"):
            _require(selection[key] == first[key] and bool(selection[key]), "frozen binding mismatch: " + key)
        effective = {**plan, "output_codec_profile": ORDER[index], "diagnostic_build_index": index,
                     "diagnostic_reference": slot["reference_binding"]}
        _require(slot["effective_plan"] == effective
                 and slot["effective_plan_sha256"] == _sha(_encoded(effective)), "effective plan binding mismatch")
        _require(common["reference_full_cpu_ns"] == reference, "one fixed first TRAIN reference required")
        own_raw = common["calibrations"]["11"]["raw_repeats"]["full"]
        own_median = statistics.median([v for row in own_raw for v in row["per_row_cost"]["cpu_ns"]])
        _require(common["observed_reference_full_cpu_ns"] == own_median, "observed TRAIN reference mismatch")
        if index == 0:
            _require(slot["reference_binding"] is None, "first reference must be observed locally")
        else:
            receipt = slot["reference_binding"]["receipt"]
            _require(receipt["schema"] == "hepta.codec-train-reference.v1"
                     and receipt["experiment_id"] == "codec-train-d1"
                     and receipt["reference_full_cpu_ns"] == reference
                     and receipt["first_selection_sha256"] == _sha((first_root / "selection.json").read_bytes())
                     and Path(receipt["first_selection_path"]).resolve() == first_root / "selection.json"
                     and all(receipt[key] == first[key] for key in ("plan_sha256", "source_commit", "freeze_sha256")),
                     "first planned reference receipt mismatch")
        inputs = _inputs(root, selection)
        base = common["bases"]
        base_id = {}
        for seed in SEEDS:
            item = base[str(seed)]
            _artifact(root, item)
            base_id[seed] = (item["sha256"], item["digest"])
        library = _artifact(root, {"file": selection["native_library"], "sha256": selection["native_library_sha256"]})
        identity = (inputs, common["calibration_identity"], base_id, _sha(library))
        if identities is None:
            identities = identity
        _require(identity == identities, "TRAIN inputs/base/native bytes identity mismatch")
        actual = {}
        for seed in SEEDS:
            rows = common["calibrations"][str(seed)]["raw_repeats"]["full"]
            _require(len(rows) == 3, "all three calibration repeats required")
            for repeat, row in enumerate(rows):
                _require(row["repeat"] == repeat and row["rows"] == 72 and row["mode"] == "full"
                         and row["observe"] is False and row["budget_violations"] == 0
                         and row["output_evidence"]["rows"] == 72, "fixed TRAIN calibration scope")
                actual[(seed, repeat)] = _trace(root, row["output_evidence"])
        if traces is None:
            traces = actual
        _require(actual == traces, "actual calibration PNG/JSON/RNG identity mismatch")
        current, absent = _prefixes(root, selection)
        missing.append({"build_index": index, "candidates_missing_step32": absent})
        if prefixes is None:
            prefixes = current
        for key, checkpoints in current.items():
            for prior_step, checkpoint in checkpoints.items():
                if prior_step in prefixes[key]:
                    _require(checkpoint == prefixes[key][prior_step], "available prefix checkpoint mismatch")
                else:
                    prefixes[key][prior_step] = checkpoint
        _require(slot["prefix_equivalence_complete"] == (not absent), "prefix completion summary mismatch")
        _require(len(selection["selected"]) == 12 and {(r["system"], r["seed"]) for r in selection["selected"]}
                 == {(s, seed) for s in SYSTEMS for seed in SEEDS}, "twelve selected states required")
        for row in selection["selected"]:
            _require(row["mode"] == "full" and row["reference_full_cpu_ns"] == reference, "static selected policy/reference")
            _model(root, row)
            report = selection["validation_measures"][row["system"]][str(row["seed"])]
            _require(report["mode"] == "full" and report["budget_violations"] == 0, "selected service cap")
            _trace(root, report["output_evidence"])
        for system in SYSTEMS:
            budget, cost = selection["budgets"][system], selection["system_cost"][system]
            _require(budget["total_cap"] == 12_000_000_000
                     and 0 <= budget["consumed_units"] <= budget["total_cap"]
                     and budget["remaining_units"] == budget["total_cap"] - budget["consumed_units"], "operator cap/conservation")
            _number(cost["cpu_seconds"], "complete attributed CPU")
            _require(common["cpu_seconds"] <= cost["cpu_seconds"] <= 10, "complete CPU cap/common attribution")
        size = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
        _require(size <= 32 * 1024**2, "32MiB retained-build bound")
        retained.append(size)
    return {"schema": "hepta.codec-train-artifact-audit.v1", "qualification_eligible": False,
            "prefix_complete": not any(row["candidates_missing_step32"] for row in missing),
            "prefix_missing": missing, "reference_full_cpu_ns": reference,
            "calibration_traces_compared": 9 * len(builds), "candidate_keys_compared": 36,
            "retained_build_bytes": retained, "formal_data_accessed": False}


def _cost(report):
    cost = report["cost"]
    return {"prepare_cpu_ns": cost["prepare_cpu_ns"], "service_cpu_ns": cost["cpu_ns"],
            "complete_cpu_ns": cost["prepare_cpu_ns"] + cost["cpu_ns"],
            "prepare_units": cost["prepare"]["consumed_units"],
            "service_units": sum(report["per_row_cost"]["work_units"]),
            "operator_totals": cost["operator_totals"], "prepare_totals": cost["prepare"].get("totals", {}),
            "codec_storage": cost.get("output_codec_storage"), "output_evidence": report["output_evidence"]}


def _spread(values):
    return {"values": values, "mean": statistics.mean(values), "min": min(values), "max": max(values),
            "sample_sd": statistics.stdev(values), "positive_fraction": sum(v > 0 for v in values) / len(values),
            "zero_fraction": sum(v == 0 for v in values) / len(values), "negative_fraction": sum(v < 0 for v in values) / len(values)}


def describe_builds(build_paths):
    """Keep every repeat/seed; B−A signs describe engineering, never efficacy."""
    _require(len(build_paths) == 4, "description requires all four planned ABBA builds")
    audit, descriptions = audit_builds(build_paths), []
    for index, (root, selection) in enumerate(_loads(build_paths)):
        calibration, methods = {}, {}
        for seed in SEEDS:
            rows = selection["common"]["calibrations"][str(seed)]["raw_repeats"]["full"]
            costs = [_cost(row) for row in rows]
            calibration[str(seed)] = {"repeats": costs, "complete_cpu_ns_per_request":
                sum(row["complete_cpu_ns"] for row in costs) / sum(row["rows"] for row in rows)}
        for system in SYSTEMS:
            chosen = [row for row in selection["selected"] if row["system"] == system]
            search = sum(row["updates"] for row in selection["all_validation_candidates"] if row["system"] == system)
            residual = sum(row.get("refinement_updates", 0) for row in chosen)
            cpu = selection["system_cost"][system]["cpu_seconds"]
            selected = {}
            for row in chosen:
                report = selection["validation_measures"][system][str(row["seed"])]
                selected[str(row["seed"])] = {"learning_rate": row["learning_rate"], "updates": row["updates"],
                    "examples": row["updates"] * selection["plan"]["batch_size"],
                    "attributed_build_cpu_ns": row.get("build_cpu_ns"),
                    "refinement_updates": row.get("refinement_updates", 0), "means": report["means"],
                    "decoder_corruption_score_drop": report["decoder_corruption_score_drop"],
                    "service": _cost(report), "missing_riskfield": "entropic_risk" not in report["means"]}
            methods[system] = {"cpu_seconds": cpu, "units": selection["budgets"][system]["consumed_units"],
                "search_updates": search, "residual_updates": residual,
                "cpu_seconds_per_adaptation_update": cpu / (search + residual), "selected": selected}
        descriptions.append({"build_index": index, "codec_variant": ORDER[index],
            "selection_ready": selection["selection_ready"], "common_cpu_seconds": selection["common"]["cpu_seconds"],
            "observed_reference_full_cpu_ns": selection["common"]["observed_reference_full_cpu_ns"],
            "retained_bytes": audit["retained_build_bytes"][index], "calibration": calibration, "methods": methods})
    pairs = []
    for a, b in ((0, 1), (3, 2)):
        left, right = descriptions[a], descriptions[b]
        calibration = [right["calibration"][str(seed)]["complete_cpu_ns_per_request"]
                       - left["calibration"][str(seed)]["complete_cpu_ns_per_request"] for seed in SEEDS]
        methods = {}
        for system in SYSTEMS:
            l, r = left["methods"][system], right["methods"][system]
            deltas = {"cpu_seconds": r["cpu_seconds"] - l["cpu_seconds"], "units": r["units"] - l["units"],
                "cpu_seconds_per_adaptation_update": r["cpu_seconds_per_adaptation_update"] - l["cpu_seconds_per_adaptation_update"],
                "actual_adaptation_updates": r["search_updates"] + r["residual_updates"] - l["search_updates"] - l["residual_updates"]}
            metrics = {"selected_updates": [r["selected"][str(seed)]["updates"] - l["selected"][str(seed)]["updates"] for seed in SEEDS]}
            for metric in l["selected"]["11"]["means"]:
                metrics[metric] = [r["selected"][str(seed)]["means"][metric] - l["selected"][str(seed)]["means"][metric] for seed in SEEDS]
            methods[system] = {**deltas, "across_seeds": {key: _spread(value) for key, value in metrics.items()}}
        pairs.append({"rowwise_index": a, "cached_index": b, "direction": "cached-minus-rowwise",
                      "calibration_cpu_ns_per_request": _spread(calibration), "methods": methods})
    return {"schema": "hepta.codec-train-description.v1", "qualification_eligible": False, "audit": audit,
        "builds": descriptions, "pairs": pairs, "missing_riskfield": True,
        "engineering_directions": {
            "both_pairs_all_methods_lower_cpu_per_update": all(row["cpu_seconds_per_adaptation_update"] < 0 for pair in pairs for row in pair["methods"].values()),
            "both_pairs_all_methods_mean_selected_updates_increase": all(row["across_seeds"]["selected_updates"]["mean"] > 0 for pair in pairs for row in pair["methods"].values()),
            "all_six_matched_seed_calibration_costs_lower": all(pair["calibration_cpu_ns_per_request"]["max"] < 0 for pair in pairs)},
        "scope": "TRAIN-only descriptive execution evidence; no CI, formal qualification or content-benefit inference",
        "risk_status": "not present in saved measures; master may add separately billed post-build TRAIN-monitor observer R&D; this analyzer executes no model/observer"}
