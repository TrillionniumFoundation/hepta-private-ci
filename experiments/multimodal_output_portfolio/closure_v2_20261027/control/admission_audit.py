"""Independent public-feature, full-cohort metric and original-owner replay."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil

import numpy as np
from scipy.stats import beta
import torch

from ...continuation_20261027.joint.run import reference_observer
from .verify_forecasts import replay
from .verify_media import byte_hash, independent_score, read_outputs, verify_sources


def read(path):
    return json.loads(path.read_text())


def save(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def public_prediction(initial, candidate, scalar, pixels_mask, tokens, observer, fitted):
    expression = r"left ([0-9]) right ([0-9]) relation (less|equal|greater)"
    match = re.fullmatch(expression, initial["caption"].strip())
    order = None if scalar == 0 else [int(match[1]), int(match[2])][::scalar]
    pixels, caption = read_outputs(candidate)
    text = re.fullmatch(expression, caption.strip())
    correct_relation = None if order is None else "less" if order[0] < order[1] else "greater" if order[0] > order[1] else "equal"
    text_matches = order is not None and text is not None and [int(text[1]), int(text[2])] == order and text[3] == correct_relation
    with torch.inference_mode():
        image = torch.cat([torch.from_numpy(pixels[:, :, :, start:start + 28]) for start in (0, 28)])
        separately_observed = torch.cat([observer(image[i:i + 1]).softmax(-1) for i in (0, 1)]).numpy()
        hidden = observer.net[:-1](image)
        probabilities = observer.net[-1](hidden).softmax(-1)
    probabilities, hidden = probabilities.numpy(), hidden.numpy()
    agrees = order is not None and separately_observed.argmax(1).tolist() == order
    minimum = 0. if order is None else min(float(separately_observed[i, y]) for i, y in enumerate(order))
    one_hot = np.zeros((2, 10))
    if order is not None:
        one_hot[0, order[0]] = one_hot[1, order[1]] = 1.
    vector = np.r_[order is not None, text_matches, agrees, minimum, one_hot.ravel(), probabilities.ravel(), hidden.ravel()]
    head = fitted["head_model"]
    value = float(np.clip(((vector - head["mean"]) / head["scale"]) @ head["weights"] + head["intercept"], .001, .999))
    missing = bool(torch.all(pixels_mask == 0) and int(tokens[3]) == 11 and int(tokens[5]) == 11)
    if missing:
        category = "declared_ood"
    elif order is None:
        category = "unknown_preference"
    elif not text_matches:
        category = "caption_inconsistent"
    elif agrees and value >= fitted["selector"]["head_threshold"] and minimum >= fitted["selector"]["minimum_public_digit_probability"]:
        category = "selected_by_public_head"
    else:
        category = "other_known_candidate"
    probability = fitted["categories"][category]["probability"]
    q = 1 << 24
    confidence = 1_000_000 - (q - int(math.floor(probability * q + .5))) * 1_000_000 // q
    moment = probability * math.exp(-2 * .998) + (1 - probability) * math.exp(-2 * -2.002)
    return {"category": category, "probability": probability, "confidence_ppm": confidence,
        "commit": bool(category == "selected_by_public_head" and moment < 1),
        "predicted_commit_moment": moment, "raw_head_probability": value}, vector


def reconstruct_metrics(rows):
    labels = np.asarray([r["strict_success"] for r in rows])
    confidence = np.asarray([r["confidence_ppm"] for r in rows])
    ood = np.asarray([r["declared_ood"] for r in rows])
    accepted = np.asarray([r["commit"] for r in rows])
    legacy = (confidence >= 750000) & ((1_000_000 - confidence) <= 500000)
    def error(selected):
        cp, y = confidence[selected], labels[selected]
        cells = np.minimum(cp // 100000, 9)
        return float(sum(abs(y[cells == k].sum() - cp[cells == k].sum() / 1e6) for k in range(10)) / len(y))
    wrong = int(np.sum(accepted & ~ood & (labels == 0)))
    metrics = {"ece_full": error(np.ones(len(rows), dtype=bool)), "ece_id": error(~ood),
        "legacy_id_coverage": float(legacy[~ood].mean()), "legacy_ood_far": float(legacy[ood].mean()),
        "legacy_ood_false_acceptances": int(legacy[ood].sum()),
        "legacy_ood_one_sided_95_upper": 1 - .05 ** (1 / int(ood.sum())) if legacy[ood].sum() == 0 else None,
        "selective_id_coverage": float(accepted[~ood].mean()), "incorrect_semantic_commits_id": wrong,
        "incorrect_semantic_commit_per_id_case": wrong / int((~ood).sum()),
        "incorrect_semantic_commit_per_id_one_sided_95_upper": float(beta.ppf(.95, wrong + 1, int((~ood).sum()) - wrong))}
    gates = {"ece": max(metrics["ece_full"], metrics["ece_id"]) <= .03,
        "ood_far": metrics["legacy_ood_far"] <= .004999,
        "ood_upper": metrics["legacy_ood_one_sided_95_upper"] is not None and metrics["legacy_ood_one_sided_95_upper"] <= .004999,
        "id_nonvacuity": metrics["legacy_id_coverage"] >= .25}
    extra = {"id_coverage": metrics["selective_id_coverage"] >= .25,
        "incorrect_commit_rate": metrics["incorrect_semantic_commit_per_id_case"] <= .004999}
    return metrics, gates, extra


def run(assets, binary, development, calibration, qualification, output):
    output.mkdir(parents=True, exist_ok=False)
    (output / "native-replay").mkdir()
    (output / "executed-source").mkdir()
    for name in ("admission_audit.py", "verify_forecasts.py", "verify_media.py"):
        shutil.copyfile(Path(__file__).with_name(name), output / "executed-source" / name)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    seal, result = read(qualification / "QUALIFICATION_SEAL.json"), read(qualification / "RESULT.json")
    if byte_hash(qualification / "ROWS.json") != result["rows_sha256"] or byte_hash(qualification / "QUALIFICATION_SEAL.json") != result["seal_sha256"]:
        raise ValueError("Qualification output seal differs")
    if byte_hash(qualification / "SOURCE_ALLOCATION.json") != seal["allocation_sha256"] or byte_hash(qualification / "PROTOCOL.json") != seal["protocol_sha256"]:
        raise ValueError("Allocated sources or frozen gate definitions changed")
    pinned_sources = read(qualification / "SOURCE_ALLOCATION.json")
    for path, expected in pinned_sources["exclusion_source_pins"].items():
        if byte_hash(path) != expected:
            raise ValueError("Historical exclusion evidence changed")
    for name, expected in seal["source_sha256"].items():
        if byte_hash(qualification / "executed-source" / name) != expected:
            raise ValueError("Qualification executed-source snapshot changed")
    fitted = read(calibration / "CALIBRATOR.json")
    if byte_hash(qualification / "CALIBRATOR.json") != byte_hash(calibration / "CALIBRATOR.json") or byte_hash(binary) != fitted["native_binary_sha256"]:
        raise ValueError("Calibration or native binary differs")
    public_observer, audit_observer = reference_observer(assets, "reward"), reference_observer(assets, "audit")
    source_roles, seen = {}, set()
    for base, role in ((calibration, "calibration_id"), (calibration, "calibration_ood"),
                       (qualification, "qualification_id"), (qualification, "qualification_ood")):
        metadata, public, private = verify_sources(base / (role + "-inputs"), assets)
        identities = {identity.rsplit(":", 1)[1] for row in metadata for identity in row["source_ids"]}
        if seen & identities:
            raise ValueError("Calibration/qualification pixel sources overlap")
        seen |= identities
        source_roles[role] = (metadata, public, private)
        if base == qualification:
            for name, expected in seal["public_private_inputs"][role].items():
                if byte_hash(base / (role + "-inputs") / name) != expected:
                    raise ValueError("Sealed qualification input changed")
    calibration_rows = read(calibration / "ROWS.json")
    for category, stats in fitted["categories"].items():
        chosen = [r for r in calibration_rows if r["category"] == category]
        outcomes = []
        for row in chosen:
            _, _, private = source_roles[row["role"]]
            i = row["index"]
            outcome = independent_score(audit_observer, row["candidate"], private["pixels"][i:i + 1].numpy(), private["labels"][i].tolist())
            if outcome["strict_success"] != row["strict_success"]:
                raise ValueError("Calibration label differs from actual candidate")
            outcomes.append(outcome["strict_success"])
        probability = 0. if category == "caption_inconsistent" else (sum(outcomes) + .5) / (len(outcomes) + 1)
        if stats != {"n": len(chosen), "successes": sum(outcomes), "probability": probability}:
            raise ValueError("Calibration frequencies differ from independent historical scoring")
    rows = read(qualification / "ROWS.json")
    maximum, count, reopened, numeric_digest = 0., 0, 0, hashlib.sha256()
    for row in rows:
        role, i = row["role"], row["index"]
        _, public, private = source_roles[role]
        initial = independent_score(audit_observer, row["initial"], private["pixels"][i:i + 1].numpy(), private["labels"][i].tolist())
        actual = independent_score(audit_observer, row["candidate"], private["pixels"][i:i + 1].numpy(), private["labels"][i].tolist())
        reopened += 4
        if initial["feedback"] != row["feedback"] or actual["strict_success"] != row["strict_success"]:
            raise ValueError("External scalar or actual final semantics differs")
        prediction, vector = public_prediction(row["initial"], row["candidate"], row["feedback"], public["mask"][i], public["tokens"][i], public_observer, fitted)
        maximum = max(maximum, float(np.max(np.abs(vector - row["public_vector"]))))
        for key, value in prediction.items():
            if isinstance(value, (str, bool, int)):
                if value != row[key]:
                    raise ValueError("Independent public predictor differs: " + key)
            else:
                maximum = max(maximum, abs(value - row[key]))
        if row["confirmed"]:
            read_outputs(row["confirmed"])
            reopened += 2
            if row["confirmed"]["sha256"] != row["candidate"]["sha256"] or not row["commit"]:
                raise ValueError("Final host confirmation changed actual candidate bytes")
        elif row["commit"]:
            raise ValueError("Accepted candidate has no actual terminal delivery")
        expected_correction = row["native_proposed"] and row["expires"] >= 7 and row["budget"] >= 2
        if row["actual_correction"] != expected_correction or row["candidate"]["command"] != int(expected_correction):
            raise ValueError("Expired/budget-refused neural action reached the decoder")
        sunk = .005 + (1 + expected_correction) * .01 + .002 + .005 * (row["native_proposed"] and not expected_correction)
        payoff = (1 if actual["strict_success"] else -2) - .002 if row["commit"] else 0.
        maximum = max(maximum, abs(sunk - row["sunk_resource_fee"]), abs(payoff - sunk - row["total_net_utility"]),
            abs(math.exp(-2 * (payoff - sunk)) - row["actual_total_policy_moment"]))
        chronology = row["chronology"]
        if not (chronology["initial_delivery"] < chronology["scalar_arrived"] < chronology["process_restart"]
                < chronology["late_native_decision"] < chronology["public_prediction"] < chronology["terminal_host_decision"] < chronology["private_grade"]):
            raise ValueError("Private final label or future feedback entered an earlier decision")
        if expected_correction and not chronology["late_native_decision"] < chronology["candidate_readback"] < chronology["public_prediction"]:
            raise ValueError("Late correction was not actually delivered after delayed control")
        name = f"{role}-{i:04}"
        transcript = read(qualification / "episodes" / name / "TRANSCRIPT.json")
        steps, fingerprint = replay(transcript, binary, development, output / "native-replay" / name)
        if steps != 16 or row["actual_original_kernel_executions"] != 50:
            raise ValueError("Native branch/recovery cost accounting differs")
        count += steps
        numeric_digest.update(fingerprint.encode())
        with (output / "PROGRESS.jsonl").open("a") as stream:
            stream.write(json.dumps({"episode": name, "native_api_ticks": steps, "native_fingerprint": fingerprint}) + "\n")
        if count % (80 * 16) == 0:
            print(f"independent semantic-admission audits {count // 16}/{len(rows)}", flush=True)
    metrics, gates, extra = reconstruct_metrics(rows)
    for key, value in metrics.items():
        if value is None:
            if result[key] is not None:
                raise ValueError("Unsupported finite upper bound")
        else:
            maximum = max(maximum, abs(value - result[key]))
    if gates != result["legacy_shaped_gates"] or extra != result["additional_selective_gates"]:
        raise ValueError("Semantic qualification gates differ")
    if maximum > 1e-7:
        raise ValueError("Independent reconstruction exceeded tolerance")
    save(output / "RESULT.json", {"passed": True, "candidate_episodes_reconstructed": len(rows),
        "original_native_api_ticks_replayed": count, "original_native_kernel_work_replayed": 50 * len(rows),
        "cold_recoveries_replayed": len(rows), "native_semantic_replay_sha256": numeric_digest.hexdigest(),
        "actual_media_files_reopened": reopened, "calibration_candidates_regraded": len(calibration_rows),
        "maximum_feature_probability_cost_statistic_discrepancy": maximum, "metrics": metrics,
        "legacy_shaped_gates": gates, "additional_selective_gates": extra,
        "qualification_all_bounded_gates_passed": all(gates.values()) and all(extra.values()),
        "full_and_id_ece_include_every_rejected_candidate": True, "private_final_labels_are_not_policy_inputs": True,
        "read_only_to_original_evidence": True, "source_pixel_identities_verified": len(seen),
        "run_rows_sha256": byte_hash(qualification / "ROWS.json"), "run_seal_sha256": byte_hash(qualification / "QUALIFICATION_SEAL.json"),
        "audit_source_sha256": {p.name: byte_hash(p) for p in (output / "executed-source").glob("*.py")}})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("assets", "binary", "development", "calibration", "qualification", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.assets, args.binary, args.development, args.calibration, args.qualification, args.output)
