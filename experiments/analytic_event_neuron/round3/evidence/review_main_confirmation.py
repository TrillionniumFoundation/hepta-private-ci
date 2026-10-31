"""Read-only independent review of completed frozen main-confirmation evidence.

No model selection, fitting or sample generation. Staged reviews are limited to
artifact integrity; aggregate inference requires the complete registered study.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import struct
import tarfile

import numpy as np
from PIL import Image
from scipy.special import log_ndtr


SOURCE = Path(__file__).resolve()
PROJECT = SOURCE.parent.parent


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def arrays(content):
    with np.load(io.BytesIO(content) if isinstance(content, bytes) else content, allow_pickle=False) as data:
        return {k: data[k].item() if data[k].ndim == 0 else data[k].copy() for k in data.files}


def write(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, sort_keys=True, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


class Review:
    def __init__(self):
        self.counts, self.maximum = Counter(), 0.0

    def require(self, value, kind, message):
        self.counts[kind] += 1
        if not value:
            raise AssertionError(kind + ": " + message)

    def close(self, actual, expected, kind, message, tolerance=2e-11):
        a, b = np.asarray(actual), np.asarray(expected)
        self.require(a.shape == b.shape, kind, message + " shape")
        if a.dtype.kind in "USO" or b.dtype.kind in "USO":
            self.require(np.array_equal(a, b), kind, message)
        else:
            gap = float(np.max(abs(a.astype(float) - b.astype(float)))) if a.size else 0.0
            self.maximum = max(self.maximum, gap)
            self.require(np.isfinite(a).all() and np.isfinite(b).all() and gap <= tolerance, kind, message)


def png_value(content, review):
    with Image.open(io.BytesIO(content)) as image:
        review.require(image.format == "PNG" and image.mode == "L" and image.size == (256, 32), "png", "format")
        p = np.asarray(image)
    values = p[0, ::4]
    upper = np.repeat(values, 4)[None, :]
    review.require(np.all((values == 0) | (values == 255)) and np.all(p[:16] == upper)
                   and np.all(p[16:] == 255 - upper), "png", "all payload/complement pixels")
    packed = np.packbits((values == 255).astype(np.uint8)).tobytes()
    value = struct.unpack(">d", packed)[0]
    review.require(math.isfinite(value), "png", "finite decoded float")
    return value


def independent_probabilities(mean, variance):
    mean, variance = np.asarray(mean), np.asarray(variance)
    lower, upper = (-.6 - mean) / np.sqrt(variance), (.6 - mean) / np.sqrt(variance)
    left, right = log_ndtr(lower), log_ndtr(-upper)
    middle = np.empty_like(left)
    for i, (a, b) in enumerate(zip(lower, upper)):
        if b <= 0:
            high, low = float(log_ndtr(b)), float(log_ndtr(a))
            middle[i] = high + math.log(-math.expm1(low - high))
        elif a >= 0:
            high, low = float(log_ndtr(-a)), float(log_ndtr(-b))
            middle[i] = high + math.log(-math.expm1(low - high))
        else:
            middle[i] = math.log1p(-math.exp(left[i]) - math.exp(right[i]))
    logs = np.column_stack((left, middle, right))
    return np.exp(logs), logs


def conditional_action_scores(variance, horizon, model, multiplier):
    """Independent dense-conditioning reference for every legal action."""
    q, scale = model["planning_q"], model["planning_noise_scale"]
    repair_noise, wait_noise = .04 * scale, .64 * scale
    terminal = variance + horizon * q
    result = {"stop": terminal,
              "repair": terminal - variance**2 / (variance + repair_noise) + .12 * multiplier}
    if horizon == 2.0:
        p = variance + q
        covariance = np.array([[p + wait_noise, p], [p, p + repair_noise]])
        cross = np.full(2, p)
        result["wait"] = .07 * multiplier + min(terminal - p**2 / (p + wait_noise),
            terminal - cross @ np.linalg.solve(covariance, cross) + .12 * multiplier)
    return result


def inspect_packets(row, model, packet_bytes, review):
    config = model["event_config"]
    packets = [json.loads(line) for line in packet_bytes.splitlines()]
    review.require(packets == row["event_packets"], "packet", "physical stream equals retained row")
    bits, levels, last, units, snapshots = [config["mean_bits"], config["initial_logvar_bits"]], [0, 0], None, {}, []
    rebases = nonzero = refinements = 0
    for sequence, packet in enumerate(packets, 1):
        review.require(set(packet) == {"schema", "config_sha256", "sequence", "time", "kind", "bits", "counts"}
            and packet["schema"] == "hepta.decision-event.packet.v1" and packet["config_sha256"] == digest(config), "packet", "schema/config")
        next_bits, count, timestamp = packet["bits"], packet["counts"], packet["time"]
        review.require(packet["sequence"] == sequence and math.isfinite(timestamp) and timestamp >= 0
            and (last is None or timestamp >= last), "packet", "logical/physical clock")
        review.require(next_bits[0] == config["mean_bits"] and config["initial_logvar_bits"] <= next_bits[1] <= config["maximum_logvar_bits"]
            and all(type(x) is int and abs(x) <= 2**48 for x in count), "packet", "precision/count domain")
        if packet["kind"] == "refinement":
            review.require(last is not None and timestamp == last and next_bits[1] > bits[1] and count[0] == 0, "packet", "refinement semantics")
            refinements += 1
        else:
            review.require(packet["kind"] in ("observed", "missing") and next_bits[1] == config["initial_logvar_bits"], "packet", "observation precision reset")
        rebases += next_bits != bits
        levels = [math.floor(math.ldexp(levels[j], next_bits[j] - bits[j]) + .5) + count[j] for j in range(2)]
        bits, last = list(next_bits), timestamp
        nonzero += sum(x != 0 for x in count)
        for j, name in enumerate(("mean", "logvar")):
            key = f"{name}:{bits[j]}"
            units[key] = units.get(key, 0) + abs(count[j])
        snapshots.append({"bits": list(bits), "levels": list(levels)})
    expected = {"packets": len(packets), "packet_bytes": len(packet_bytes), "logical_unit_events": sum(units.values()),
        "logical_unit_events_by_resolution": units, "nonzero_channels": nonzero, "precision_rebases": int(rebases),
        "refinement_packets": refinements, "decoder": {"schema": "hepta.decision-event.decoder.v1", "config": config,
            "bits": bits, "levels": levels, "sequence": len(packets), "time": last}}
    review.require(row["event_accounting"] == expected, "packet", "independent complete accounting/state")
    receipt, offset = row["packet_transport"], 0
    review.require(receipt["sha256"] == hashlib.sha256(packet_bytes).hexdigest() and receipt["bytes"] == len(packet_bytes), "packet", "stream digest")
    for operation in receipt["operations"]:
        chunk = packet_bytes[offset:offset + operation["bytes"]]
        review.require(operation["offset"] == offset and operation["sha256"] == hashlib.sha256(chunk).hexdigest()
            and operation["began_ns"] <= operation["written_ns"] <= operation["readback_ns"], "packet", "actual segment readback")
        offset += operation["bytes"]
    review.require(offset == len(packet_bytes) and len(receipt["operations"]) == len(packets), "packet", "complete packet coverage")
    for stage in row["stages"]:
        consumed = sum(op["readback_ns"] <= stage["decision_ns"] for op in receipt["operations"])
        review.require(consumed > 0, "certificate", "receiver state precedes choice")
        snapshot = snapshots[consumed - 1]
        cert = stage["event_certificate"]
        center = math.ldexp(snapshot["levels"][1], -snapshot["bits"][1])
        half = math.ldexp(.5, -snapshot["bits"][1]); padding = 32 * math.ulp(max(1., abs(center)))
        interval = [math.exp(center - half - padding), math.exp(center + half + padding)]
        review.close(cert["variance_interval"], interval, "certificate", "independent decoded cell")
        review.require(cert["precision_bits"] == snapshot["bits"] and cert["selected"] == stage["selected"], "certificate", "actual state/action")
        multiplier, horizon = row["public_terms"]["cost_multiplier"], stage["horizon"]
        center_scores = conditional_action_scores(math.exp(center), horizon, model, multiplier)
        endpoint_scores = [conditional_action_scores(v, horizon, model, multiplier) for v in interval]
        for action in center_scores:
            review.close(cert["scores"][action], center_scores[action], "certificate", "dense center action score")
            review.close(cert["score_intervals"][action], [x[action] for x in endpoint_scores], "certificate", "dense action interval")
        mean = math.ldexp(snapshot["levels"][0], -snapshot["bits"][0]) + model["parameters"][0] * horizon
        review.close(stage["predicted_mean"], mean, "certificate", "prediction from consumed integer packets")
        if config["mode"] != "increment_only":
            h = stage["public_history"]; seen = np.asarray(h["mask"], bool) & np.asarray(h["occupied"], bool)
            times = np.asarray(h["times"])[seen]; q, scale = model["parameters"][1:]
            covariance = 1 + q * np.minimum(times[:, None], times[None, :]) + np.diag(scale * np.asarray(h["obs_var"])[seen])
            cross = 1 + q * times; last_time = max(t for t, active in zip(h["times"], h["occupied"]) if active)
            actual_variance = 1 + q * last_time - cross @ np.linalg.solve(covariance, cross)
            review.require(interval[0] <= actual_variance <= interval[1], "certificate", "independent driver is in cell")
        selected_upper = cert["score_intervals"][cert["selected"]][1]
        separated = all(bound[0] > selected_upper + cert["numeric_allowance"] for name, bound in cert["score_intervals"].items() if name != cert["selected"])
        review.require(cert["certified"] == (config["mode"] != "increment_only" and separated), "certificate", "strict certificate gate")


def rebuild_analysis(predictions, controls):
    result = {}
    for kind, rows in (("prediction", predictions), ("control", controls)):
        groups = defaultdict(list)
        for row in rows:
            groups[row["arm"]].append(row)
        for arm, group in groups.items():
            group.sort(key=lambda row: row["case"])
            result[f"{kind}_ids__{arm}"] = np.asarray([r["case"] for r in group])
            if kind == "prediction":
                for field in ("nll", "brier"):
                    result[field + "__" + arm] = np.asarray([np.mean(r[field]) for r in group])
                for field in ("probabilities", "labels"):
                    result[field + "__" + arm] = np.asarray([r[field] for r in group])
                result["mse__" + arm] = np.asarray([np.mean((np.asarray(r["mean"]) - r["targets"])**2) for r in group])
                result["standardized_error__" + arm] = np.asarray([(np.asarray(r["targets"]) - r["mean"]) / np.sqrt(r["variance"]) for r in group])
            else:
                for field in ("utility", "paid_cost", "elapsed_ns", "cpu_ns", "severe_loss", "squared_error"):
                    result[field + "__" + arm] = np.asarray([r[field] for r in group], dtype=float)
                result["actions__" + arm] = np.asarray(["/".join(r["actions"]) for r in group])
                if "event_accounting" in group[0]:
                    for field in ("packet_bytes", "packets", "logical_unit_events", "refinement_packets", "precision_rebases"):
                        result[field + "__" + arm] = np.asarray([r["event_accounting"][field] for r in group])
                    result["uncertified_decisions__" + arm] = np.asarray([sum(not s["event_certificate"]["certified"] for s in r["stages"]) for r in group])
    return result


def review_scope(run, entry, frozen):
    review = Review(); body, artifacts, member_hashes = {}, {}, {}
    archive_path = run / entry["archive"]
    review.require(file_hash(archive_path) == entry["archive_receipt"]["sha256"], "archive", "archive digest")
    with tarfile.open(archive_path, "r|gz") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            review.require(member.isfile() and not path.is_absolute() and ".." not in path.parts and member.name not in member_hashes, "archive", "safe unique regular member")
            content = archive.extractfile(member).read()
            member_hashes[member.name] = hashlib.sha256(content).hexdigest()
            if not member.name.startswith("transport/") or member.name.endswith("TRANSPORT_RECEIPTS.jsonl"):
                body[member.name] = content
            elif member.name.endswith(".png"):
                artifacts[member.name] = png_value(content, review)
            elif member.name.endswith(".txt"):
                artifacts[member.name] = float(content)
            elif member.name.endswith(".json"):
                artifacts[member.name] = json.loads(content)
            else:
                artifacts[member.name] = content
    manifest = json.loads(body["ARCHIVE_MANIFEST.json"])
    review.require({k: v for k, v in member_hashes.items() if k != "ARCHIVE_MANIFEST.json"} == manifest, "archive", "every member hash and complete inventory")
    review.require(len(member_hashes) == entry["archive_receipt"]["file_count"], "archive", "archive member count")
    data, models = arrays(body["DATA.npz"]), json.loads(body["MODELS.json"])
    review.require(member_hashes["MODELS.json"] == frozen["artifacts_sha256"][f"training/seed_{entry['seed']}/MODELS.json"], "freeze", "published frozen model")
    review.require(data["split"] == "confirmation" and data["seed"] == entry["data_seed"] and data["law"] == entry["law"], "data", "registered identity")
    locations = {str(value): i for i, value in enumerate(data["ids"])}
    review.require(len(locations) == entry["unique_trajectories"], "data", "unique trajectory count")
    prediction = [json.loads(line) for line in body["PREDICTION.jsonl"].splitlines()]
    control = [json.loads(line) for line in body["CONTROL.jsonl"].splitlines()]
    receipts, used = {}, set()
    for row in map(json.loads, body["transport/TRANSPORT_RECEIPTS.jsonl"].splitlines()):
        key = row["case"], row["arm"], row["kind"], row["stage"]
        review.require(key not in receipts and not row["private_target_supplied"] and row["began_ns"] <= row["written_ns"] <= row["readback_ns"], "transport", "receipt identity/chronology")
        if row["kind"] == "observation":
            path = "transport/" + row["path"]; used.add(path)
            review.require(member_hashes[path] == row["sha256"], "transport", "observation hash")
            value = artifacts[path]["value"]
        else:
            paths = ["transport/" + row[k] for k in ("text_path", "image_path")]; used.update(paths)
            review.require(all(member_hashes[path] == row[field] for path, field in zip(paths, ("text_sha256", "image_sha256"))), "transport", "delivery hashes")
            value = artifacts[paths[1]]
            review.require(struct.pack(">d", value) == struct.pack(">d", artifacts[paths[0]]) == struct.pack(">d", row["prediction"]), "transport", "text/PNG/receipt exact bits")
        receipts[key] = row, value
    seen = set()
    for row in prediction:
        key = row["arm"], row["case"]
        review.require(key not in seen and key[0] in models and key[1] in locations, "prediction", "registered paired row"); seen.add(key)
        target = data["future"][locations[key[1]], [1, 2, 4]]
        labels = (target > -.6).astype(int) + (target > .6).astype(int)
        p, logs = independent_probabilities(row["mean"], row["variance"])
        for field, expected in (("targets", target), ("labels", labels), ("probabilities", p),
                ("nll", -logs[np.arange(3), labels]), ("brier", np.sum((p - np.eye(3)[labels])**2, axis=1))):
            review.close(row[field], expected, "prediction", field)
    review.require(len(seen) == len(models) * len(locations), "coverage", "all prediction pairs")
    seen, consumed_receipts = set(), set()
    for row in control:
        arm, case = row["arm"], row["case"]; i = locations[case]
        allowed_arms = set(models) | {"always_stop", "always_repair", "always_wait", "always_wait_repair"}
        review.require((arm, case) not in seen and arm in allowed_arms and row["actual_transport"], "control", "unique actual episode"); seen.add((arm, case))
        actions = row["actions"]
        review.require(actions in (["stop"], ["repair"], ["wait", "stop"], ["wait", "repair"]), "control", "legal complete action path")
        multiplier = float(data["cost_multiplier"][i]); cost = sum((.07 if a == "wait" else .12) * multiplier for a in actions if a != "stop")
        key = case, arm, "delivery", "final"; final, delivered = receipts[key]
        review.require(final["action"] == "/".join(actions) and final["readback_ns"] <= row["final_readback_ns"] < row["score_started_ns"], "control", "final delivery before score")
        expected = {"paid_cost": cost, "terminal_target": float(data["future"][i, 4]), "delivered_prediction": delivered}
        expected["squared_error"] = (delivered - expected["terminal_target"])**2
        expected["utility"] = 1 - expected["squared_error"] - cost
        for field, value in expected.items(): review.close(row[field], value, "control", field)
        review.require(row["severe_loss"] == (expected["utility"] < -2), "control", "severe loss")
        for stage, field in (("terms", "cost_multiplier"), ("wait", "wait_observation"), ("repair", "repair_observation"), ("wait_repair", "wait_repair_observation")):
            key = case, arm, "observation", stage
            if key in receipts: review.close(receipts[key][1], data[field][i], "control", "actual acquired observation")
        keys = {(case, arm, "observation", "initial"), (case, arm, "observation", "terms"), (case, arm, "delivery", "initial"), (case, arm, "delivery", "final")}
        keys.update((case, arm, "observation", ob["stage"]) for ob in row["observations"])
        review.require(keys.issubset(receipts), "coverage", "episode readbacks exist"); consumed_receipts.update(keys)
        if "event_packets" in row:
            path = "transport/" + row["packet_transport"]["path"]; used.add(path)
            inspect_packets(row, models[arm], artifacts[path], review)
    review.require(consumed_receipts == set(receipts) and used == set(artifacts), "coverage", "all transport artifacts consumed")
    review.require(len(seen) == (len(models) + 4) * len(locations), "coverage", "all model/fixed-policy pairs")
    rebuilt = rebuild_analysis(prediction, control); stored = arrays(run / entry["analysis"])
    review.require(file_hash(run / entry["analysis"]) == entry["analysis_sha256"] and set(rebuilt) == set(stored), "analysis", "NPZ hash/complete keys")
    for name in rebuilt: review.close(stored[name], rebuilt[name], "analysis", name, tolerance=0.)
    frozen_audit = json.loads(body["AUDIT.json"])
    review.require(frozen_audit["passed"] and frozen_audit["full_frozen_inference_replay"], "audit", "completed frozen/native replay")
    return {"passed": True, "scope": entry["scope"], "seed": entry["seed"], "law": entry["law"],
        "archive_sha256": entry["archive_receipt"]["sha256"], "analysis_sha256": entry["analysis_sha256"],
        "source_commit": frozen["source_commit"], "review_script_sha256": file_hash(SOURCE), "checks": dict(review.counts),
        "maximum_absolute_difference": review.maximum, "archive_members": len(member_hashes),
        "unique_trajectories": len(locations), "prediction_rows": len(prediction), "control_rows": len(control),
        "pngs_independently_decoded": sum(name.endswith(".png") for name in artifacts),
        "model_or_native_inference_rerun_by_this_review": False,
        "inference_evidence": "Frozen scope AUDIT already replays every model and original native inference; this review independently checks archival bytes, predictions/losses, costs, deliveries, packets and analysis."}


def bootstrap(delta, replicates, seed, alpha):
    """Same registered random draws, independent per-replicate/seed reduction."""
    rng = np.random.default_rng(seed); s, n = delta.shape; values = []
    for start in range(0, replicates, 200):
        count = min(200, replicates - start)
        seeds = rng.integers(s, size=(count, s, 1)); cases = rng.integers(n, size=(count, s, n))
        for b in range(count):
            values.append(sum(float(np.mean(delta[seeds[b, j, 0], cases[b, j]])) for j in range(s)) / s)
    return {"mean_difference": float(delta.mean()), "per_seed_mean_difference": delta.mean(1).tolist(),
            "interval": np.quantile(values, [alpha / 2, 1 - alpha / 2]).tolist()}


def aggregate(run, protocol, entries, reports, frozen):
    review = Review(); result = json.loads((run / "MAIN_RESULTS.json").read_text())
    seeds = protocol["training_seeds"]; laws = [protocol["laws"]["primary"], *protocol["laws"]["mismatch"]]
    expected = {(seed, law) for seed in seeds for law in laws}
    review.require({(e["seed"], e["law"]) for e in entries} == expected and len(entries) == 15, "coverage", "complete registered 15 scopes")
    loaded = {(e["seed"], e["law"]): arrays(run / e["analysis"]) for e in entries}
    identifiers = [str(i) for e in entries for i in loaded[(e["seed"], e["law"])]["control_ids__analytic"]]
    review.require(len(identifiers) == len(set(identifiers)) == result["independent_trajectories"], "sampling", "unique trajectories across scopes")
    review.require(result["training_seed_count"] == 5 and result["source_commit"] == frozen["source_commit"] and result["production_promotion"] is False, "freeze", "scope/source/authority")
    stat = protocol["statistics"]; contrasts = []
    names = ("analytic_vs_history", "analytic_vs_native", "event_vs_continuous")
    for number, (name, pair) in enumerate(zip(names, stat["primary_contrasts"])):
        contrasts.append(("primary_contrasts", name, *pair, "gaussian", number, True))
        for offset, law in enumerate(laws[1:], 1): contrasts.append(("mismatch_contrasts", law + ":" + name, *pair, law, 100 * offset + number, False))
    for number, pair in enumerate(protocol["secondary_contrasts"]): contrasts.append(("secondary_contrasts", pair[0] + "_vs_" + pair[1], *pair, "gaussian", 1000 + number, False))
    computed = {}
    for group, name, candidate, baseline, law, number, primary in contrasts:
        delta = []
        for seed in seeds:
            a = loaded[(seed, law)]
            review.close(a["control_ids__" + candidate], a["control_ids__" + baseline], "sampling", "paired complete trajectories")
            delta.append(a["utility__" + candidate] - a["utility__" + baseline])
        alpha = stat["family_alpha"] / stat["primary_family_size"] if primary else .05
        value = bootstrap(np.asarray(delta), stat["bootstrap_replicates"], stat["bootstrap_seed"] + number, alpha)
        for field in value: review.close(result[group][name][field], value[field], "bootstrap", name + "/" + field)
        if primary:
            passed = value["interval"][0] > stat["minimum_useful_net_utility_gain"] and min(value["per_seed_mean_difference"]) > 0
            review.require(result[group][name]["passes_registered_superiority"] == passed, "gate", name)
        if group == "mismatch_contrasts":
            review.require(result[group][name]["empirical_lower_above_negative_margin"] == (value["interval"][0] > -stat["mismatch_descriptive_margin"])
                and result[group][name]["population_noninferiority_established"] is False, "gate", name)
        computed[name] = value
    event = computed["event_vs_continuous"]; margin = stat["event_utility_noninferiority_margin"]
    review.require(result["event_noninferiority"]["passes_empirical_noninferiority"] == (event["interval"][0] > -margin and min(event["per_seed_mean_difference"]) > -margin), "gate", "separate unchanged noninferiority")
    for law in laws:
        for arm, metrics in result["laws"][law].items():
            for field in ("utility", "paid_cost", "squared_error", "packet_bytes", "uncertified_decisions"):
                if field not in metrics: continue
                values = np.concatenate([loaded[(seed, law)][field + "__" + arm] for seed in seeds])
                review.close(metrics[field]["mean"], values.mean(), "aggregate", law + "/" + arm + "/" + field)
        for candidate, baseline, label in (("event_adaptive", "event_direct", "direct_control"), ("analytic", "equivalent_gaussian", "gaussian_control")):
            maximum = 0.; disagreements = 0
            for seed in seeds:
                a = loaded[(seed, law)]
                for field in ("probabilities", "utility", "paid_cost", "squared_error"):
                    maximum = max(maximum, float(np.max(abs(a[field + "__" + candidate] - a[field + "__" + baseline]))))
                disagreements += int(np.count_nonzero(a["actions__" + candidate] != a["actions__" + baseline]))
            expected = {"maximum_numeric_difference": maximum, "action_disagreements": disagreements, "exact": maximum == 0. and disagreements == 0}
            review.require(result["mechanism_controls"][law][label] == expected, "mechanism", law + label)
        squared_reduction = float(np.mean(np.concatenate([loaded[(seed, law)]["squared_error__analytic"]
            - loaded[(seed, law)]["squared_error__event_adaptive"] for seed in seeds])))
        extra_cost = float(np.mean(np.concatenate([loaded[(seed, law)]["paid_cost__event_adaptive"]
            - loaded[(seed, law)]["paid_cost__analytic"] for seed in seeds])))
        disagreements = sum(int(np.count_nonzero(loaded[(seed, law)]["actions__event_adaptive"]
            != loaded[(seed, law)]["actions__analytic"])) for seed in seeds)
        for field, expected in (("squared_error_reduction", squared_reduction), ("paid_cost_increase", extra_cost),
                ("net_utility_difference", squared_reduction - extra_cost), ("event_vs_analytic_action_disagreements", disagreements)):
            review.close(result["mechanism_controls"][law][field], expected, "mechanism", law + field)
    counts = Counter(review.counts)
    for report in reports: counts.update(report["checks"])
    return {"schema": "hepta.analytic-event.round3.main-independent-review.v1", "passed": True,
        "source_commit": frozen["source_commit"], "review_script_sha256": file_hash(SOURCE), "checks": dict(counts),
        "total_checks": sum(counts.values()), "scopes": len(entries), "unique_trajectories": len(identifiers),
        "prediction_rows": sum(r["prediction_rows"] for r in reports), "control_rows": sum(r["control_rows"] for r in reports),
        "archive_members": sum(r["archive_members"] for r in reports), "pngs_independently_decoded": sum(r["pngs_independently_decoded"] for r in reports),
        "maximum_statistics_difference": review.maximum, "recomputed_contrasts": computed,
        "main_results_sha256": file_hash(run / "MAIN_RESULTS.json"), "negative_and_equivalent_results_retained": True,
        "model_or_native_inference_rerun_by_this_review": False,
        "scope_limits": ["Frozen full inference/native replay is separately recorded in each AUDIT.",
            "Five fitted seeds; dependent horizons and model outputs do not enlarge independent trajectory counts.",
            "Student-t4 squared-loss intervals remain descriptive; no population noninferiority or hardware/energy claim."]}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--scope"); parser.add_argument("--final", action="store_true"); args = parser.parse_args()
    run = args.run_dir; frozen = json.loads((run / "FREEZE.json").read_text()); protocol = json.loads((PROJECT / "PROTOCOL.json").read_text())
    if file_hash(PROJECT / "PROTOCOL.json") != frozen["protocol_sha256"]: raise ValueError("Frozen protocol changed")
    found = {}
    for path in sorted((run / "main").glob("RUN_INDEX*.json")):
        index = json.loads(path.read_text())
        if index["source_commit"] != frozen["source_commit"]: raise ValueError("Index source differs")
        for entry in index["scopes"]:
            if entry["scope"] in found and found[entry["scope"]] != entry: raise ValueError("Contradictory scope indices")
            found[entry["scope"]] = entry
    if args.scope and args.scope not in found: raise ValueError("Requested scope has not completed")
    reports = []
    for name, entry in sorted(found.items()):
        if args.scope and name != args.scope: continue
        path = run / "independent_main_review" / (name + ".json")
        old = json.loads(path.read_text()) if path.exists() else None
        if old and old["review_script_sha256"] == file_hash(SOURCE) and old["archive_sha256"] == entry["archive_receipt"]["sha256"] and old["analysis_sha256"] == entry["analysis_sha256"]:
            if file_hash(run / entry["analysis"]) != old["analysis_sha256"] or file_hash(run / entry["archive"]) != old["archive_sha256"]: raise ValueError("Reviewed bytes changed")
            report = old
        else:
            report = review_scope(run, entry, frozen); write(path, report)
        reports.append(report); print(json.dumps({"scope": name, "artifact_review_passed": report["passed"], "aggregate_inference_performed": False}), flush=True)
    if args.final:
        final_index = json.loads((run / "main/RUN_INDEX.json").read_text())
        if args.scope or not final_index["complete"]: raise ValueError("Final review requires the complete unsliced study")
        result = aggregate(run, protocol, list(found.values()), reports, frozen)
        write(PROJECT / "evidence/MAIN_CONFIRMATION_REVIEW.json", result)
        print(json.dumps({"passed": result["passed"], "total_checks": result["total_checks"], "scopes": result["scopes"]}))


if __name__ == "__main__": main()
