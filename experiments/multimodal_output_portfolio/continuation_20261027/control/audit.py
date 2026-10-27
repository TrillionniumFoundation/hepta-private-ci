"""Independent media decoding, complete-terminal rescoring and original-owner replay."""
import argparse
import hashlib
import json
import itertools
import math
from pathlib import Path
import subprocess
import wave

import numpy as np
from PIL import Image

from .client import Native, Q, sha, write


def read(path):
    return json.loads(Path(path).read_text())


def relocated(run, path):
    parts = Path(path).parts
    position = parts.index("evaluation")
    result = run.joinpath(*parts[position:])
    if not result.resolve().is_relative_to(run.resolve()):
        raise ValueError("Media path outside frozen run")
    return result


def decode(run, paths):
    mapped = {name: relocated(run, value) for name, value in paths.items()}
    text = mapped["text"].read_text().strip().split()
    if len(text) != 2 or text[0] != "category":
        raise ValueError("Malformed independently decoded text")
    code = int(text[1])
    with Image.open(mapped["image"]) as image:
        pixels = np.array(image.convert("RGB"))
    image_code = round((float(pixels[8:, :, :].mean()) - 32) / 64)
    with wave.open(str(mapped["audio"]), "rb") as stream:
        parameters = stream.getparams()
        signal = np.frombuffer(stream.readframes(parameters.nframes), dtype="<i2")
    if (parameters.nchannels, parameters.sampwidth, parameters.framerate, len(signal)) != (1, 2, 8000, 8000):
        raise ValueError("Unexpected independently read audio")
    clock = np.arange(len(signal)) / parameters.framerate
    energy = [abs(signal @ np.exp(2j * np.pi * frequency * clock)) for frequency in (400, 600, 800, 1000)]
    audio_code = int(np.argmax(energy))
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-threads", "1", "-i", str(mapped["video"]),
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-threads", "1", "-"])
    if len(raw) != 4 * 16 * 16 * 3:
        raise ValueError("Independent video decoder did not return four complete frames")
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(4, 16, 16, 3)
    video_codes = [round((float(frame[8:].mean()) - 32) / 64) for frame in frames]
    markers = [int(frame[0, :, 0].argmax()) for frame in frames]
    if markers != [0, 4, 8, 12] or any(v not in range(4) for v in [code, image_code, audio_code, *video_codes]):
        raise ValueError("Invalid independently decoded semantic media")
    mismatch = (image_code != code) + (audio_code != code) + any(v != code for v in video_codes)
    fault = 0 if mismatch == 0 else 1 if mismatch == 1 else 2
    return {"code": code, "fault": fault, "media_sha256": {key: sha(p) for key, p in mapped.items()}}


IGNORED_MEASUREMENT_FIELDS = {"execution_micros", "transient_allocation_bytes", "model_latency_micros", "model_resident_bytes", "restore_micros"}


def semantic(value):
    if isinstance(value, dict):
        return {key: semantic(item) for key, item in value.items() if key not in IGNORED_MEASUREMENT_FIELDS}
    if isinstance(value, list):
        return [semantic(item) for item in value]
    return value


def check_row(row, protocol, initial, final):
    if initial["media_sha256"] != row["initial_observed"]["media_sha256"] or final["media_sha256"] != row["final_observed"]["media_sha256"]:
        raise ValueError("Actual media identity changed")
    ticks = row["actual_continuation_ticks"]
    if any(t["owner_authority"] != "DENY_ALL" for t in row["actual_root_ticks"] + ticks):
        raise ValueError("Native signal was relabelled as action authority")
    allowed = not any(t["native_abstain"] for t in ticks)
    proposal = initial["fault"] != 0 if row["arm"] == "risk_history" else ticks[-1]["proposed_repair"]
    executed = bool(proposal and allowed and row["media_budget"] >= 2)
    if executed != row["executed_repair"] or bool(proposal and not executed) != row["denied_attempt"]:
        raise ValueError("Actual dispatch did not follow the registered owner and host resource rules")
    if ticks[1]["feedback_q24"] != 0 or ticks[2]["feedback_q24"] != 0:
        raise ValueError("Fresh scalar reached later native readout")
    expected_feedback = 0 if row["arm"] == "risk_zero" else round(protocol["numeric_feedback_by_fault"][initial["fault"]] * Q)
    if ticks[0]["feedback_q24"] != expected_feedback:
        raise ValueError("Phase1 scalar does not match actual media readback and intervention")
    ordered = [row["chronology"][key] for key in ("delivered", "feedback", "continuation", "private_scoring")]
    if not all(a < b for a, b in zip(ordered, ordered[1:])):
        raise ValueError("Feedback/scoring chronology violated")
    charge = protocol["initial_action_cost"][initial["code"]]
    charge += protocol["channel_cost_by_fault"][initial["fault"]]
    charge += row["actual_native_ticks_including_planning"] * protocol["native_tick_charge"]
    if "verification_replay_steps" in protocol:
        replays = sum(2 * branch["start"]["sequence"] for branch in row["forecast_branches"])
        if replays != row["additional_ledger_validation_kernel_steps"] + row["original_journal_replayed_prefix_steps"]:
            raise ValueError("Actual restore verification steps are not fully charged")
        charge += replays * protocol["verification_replay_step_charge"]
    charge += protocol["repair_cost"] if executed else protocol["denied_repair_attempt_cost"] if proposal else 0
    harm = protocol["irreversible_first_delivery_damage"][initial["fault"]]
    penalty = protocol["terminal_mismatch_penalty"][final["fault"]]
    utility = [value - harm - penalty - charge for value in protocol["semantic_utility_action_by_target"][final["code"]]]
    strict = [int(final["fault"] == 0 and final["code"] == target) for target in range(3)]
    error = max(abs(a - b) for a, b in zip(utility, row["return_by_private_target"]))
    if error > 1e-12 or strict != row["strict_by_private_target"]:
        raise ValueError("Independent terminal rescoring differs")
    return utility, strict, charge, error


def audit(run, binary, output):
    output.mkdir(parents=True, exist_ok=False)
    frozen = read(run / "FROZEN.json")
    for file, field in (("PROTOCOL.json", "protocol_sha256"), ("ENCODER_DOMAIN_PROOF.json", "calibration_sha256"),
                        ("COMMON_ROOT_TABLE.json", "common_root_table_sha256")):
        if sha(run / file) != frozen[field]:
            raise ValueError("Frozen protocol/calibration/root identity changed")
    for name, expected in frozen["sources"].items():
        if sha(run / "executed-sources" / name) != expected:
            raise ValueError("Frozen executed source identity changed")
    if sha(binary) != frozen["binary_sha256"] or sha(run / "MODEL.json") != frozen["model_sha256"]:
        raise ValueError("Frozen execution identity changed")
    protocol, result = read(run / "PROTOCOL.json"), read(run / "RESULT.json")
    paths = sorted((run / "evaluation").glob("*/EPISODE.json"))
    if len(paths) != 240:
        raise ValueError("Incomplete actual episode census")
    expected_keys = set(itertools.product(range(4), protocol["expiry_contexts"], protocol["media_budget_contexts"], protocol["arms"], range(3)))
    row_key = lambda row: (row["cue"], row["expires"], row["media_budget"], row["arm"], row["realized_transport_fault"])
    if {row_key(read(path)) for path in paths} != expected_keys:
        raise ValueError("Actual census is not the unique registered Cartesian grid")
    expected_groups = {key[:4] for key in expected_keys}
    if len(result["groups"]) != len(expected_groups) or {
        (r["cue"], r["expires"], r["media_budget"], r["arm"]) for r in result["groups"]} != expected_groups:
        raise ValueError("Reported groups are not the registered Cartesian grid")
    native = Native(binary)
    errors, groups, media, replayed, rows, head_error = [], {}, set(), 0, [], 0.0
    weights = read(run / "MODEL.json")["weights"]
    try:
        for path in paths:
            row = read(path)
            initial, final = decode(run, row["initial_paths"]), decode(run, row["final_paths"])
            utility, strict, charge, error = check_row(row, protocol, initial, final)
            errors.append(error)
            for value in [*row["initial_paths"].values(), *row["final_paths"].values()]:
                media.add(str(relocated(run, value)))
            transcript = read(path.with_name("TRANSCRIPT.json"))
            actual_count = 0
            for line in transcript:
                request = dict(line["request"])
                if request["command"] == "Open":
                    request.update(directory=str(output / row["name"]), model=str(run / "MODEL.json"),
                                   calibration=str(run / "ENCODER_DOMAIN_PROOF.json"))
                actual = native.call(request)
                expected = line["response"]["result"]
                if semantic(actual) != semantic(expected):
                    raise ValueError("Independent original-owner replay differs: " + row["name"])
                if request["command"] == "Tick":
                    actual_count += int(actual.get("native_transition_executed", True))
                    if actual["phase"] == 3:
                        value = weights[0] + sum(w * x / Q for w, x in zip(weights[1:], actual["eligibility_before_q24"]))
                        head_error = max(head_error, abs(value - actual["readout_logit"]))
                elif request["command"] == "Forecast":
                    actual_count += len(actual["ticks"])
            if actual_count != row["actual_native_ticks_including_planning"]:
                raise ValueError("Uncharged native planning or continuation invocation")
            replayed += actual_count
            key = (row["cue"], row["expires"], row["media_budget"], row["arm"])
            mass = protocol["fault_law_by_action"][initial["code"]][initial["fault"]]
            target = protocol["target_law_by_cue"][row["cue"]]
            state = groups.setdefault(key, [0.0, 0.0, 0.0, 0.0])
            state[0] += sum(mass * p * math.exp(-protocol["gamma"] * u) for p, u in zip(target, utility))
            state[1] += sum(mass * p * u for p, u in zip(target, utility))
            state[2] += sum(mass * p * s for p, s in zip(target, strict))
            state[3] += mass * charge
            rows.append(row)
    finally:
        native.finish()
    metric_error = 0.0
    for row in result["groups"]:
        key = (row["cue"], row["expires"], row["media_budget"], row["arm"])
        for value, name in zip(groups[key], ("actual_moment", "actual_mean", "actual_strict_success", "actual_cost")):
            metric_error = max(metric_error, abs(value - row[name]))
            if not math.isclose(value, row[name], rel_tol=1e-12, abs_tol=1e-10):
                raise ValueError("Independent aggregate metric differs")
    if head_error > 1e-12:
        raise ValueError("Native head does not match its recorded state-only features")
    # Consequential receipt mutations must be detected by the independent checker.
    negative_controls = []
    selected = next(row for row in rows if row["denied_attempt"])
    initial, final = decode(run, selected["initial_paths"]), decode(run, selected["final_paths"])
    for field in ("executed_repair", "denied_attempt"):
        changed = dict(selected)
        changed[field] = not changed[field]
        try:
            check_row(changed, protocol, initial, final)
        except ValueError:
            negative_controls.append(field)
        else:
            raise ValueError("Mutated dispatch receipt was accepted")
    receipt = {"schema": "hepta.continuation.owner-independent-audit.v1", "passed": True,
        "actual_episodes_rescored": len(rows), "actual_evaluation_media_files_read": len(media),
        "native_ticks_independently_replayed": replayed, "all_full_semantic_native_receipts_match": True,
        "native_measurements_not_assumed_repeatable": sorted(IGNORED_MEASUREMENT_FIELDS),
        "maximum_terminal_utility_error": max(errors), "maximum_aggregate_metric_absolute_error": metric_error,
        "maximum_independent_state_head_logit_error": head_error,
        "dispatch_receipt_mutations_rejected": negative_controls,
        "result_sha256": sha(run / "RESULT.json"), "auditor_source_sha256": sha(__file__),
        "production_authority": False, "semantic_success_qualification": False}
    write(output / "AUDIT.json", receipt)
    print(json.dumps(receipt))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "binary", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    args = p.parse_args()
    audit(args.run.resolve(), args.binary.resolve(), args.output.resolve())
