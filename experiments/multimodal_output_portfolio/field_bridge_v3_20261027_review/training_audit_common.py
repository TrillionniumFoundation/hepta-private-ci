"""Independent evidence readers and arithmetic for completed V3 training stages."""

import gzip
import hashlib
import json
from pathlib import Path

import numpy as np


HERE = Path(__file__).parent
SCIENCE = HERE.parent / "field_bridge_v3_20261027"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def bound(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def check_close(actual, expected, message, atol=1e-12, rtol=0.):
    require(np.allclose(np.asarray(actual), np.asarray(expected), atol=atol, rtol=rtol, equal_nan=False), message)


def expected_pairs(registry, role, conditions):
    identities = registry["roles"][role]["identities"]
    require(len(identities) % 2 == 0, "Odd source-role image inventory")
    pairs = [[identities[index], identities[index + 1]] for index in range(0, len(identities), 2)]
    return pairs * len(conditions), [condition for condition in conditions for _ in pairs]


def read_registry(source=SCIENCE):
    source = Path(source)
    allocation = read(source / "SOURCE_ALLOCATION.json")
    core = {key: value for key, value in allocation.items() if key != "manifest_sha256"}
    require(bound(core) == allocation["manifest_sha256"], "Source allocation content digest differs")
    packed = (source / "SOURCE_IDENTITIES.json.gz").read_bytes()
    raw = gzip.decompress(packed)
    require(hashlib.sha256(packed).hexdigest() == allocation["registry_gzip_sha256"]
            and hashlib.sha256(raw).hexdigest() == allocation["registry_sha256"], "Source role registry identity differs")
    registry = json.loads(raw)
    all_pixels = []
    for role, entry in registry["roles"].items():
        identities = entry["identities"]
        pixels = [identity.rsplit(":", 1)[-1] for identity in identities]
        summary = allocation["roles"][role]
        require(len(identities) == summary["images"]
                and hashlib.sha256("\n".join(identities).encode()).hexdigest() == summary["identity_sha256"]
                and hashlib.sha256("\n".join(sorted(pixels)).encode()).hexdigest() == summary["pixel_set_sha256"],
                f"Source role identity differs: {role}")
        all_pixels.extend(pixels)
    require(len(all_pixels) == len(set(all_pixels)), "Source roles overlap by pixel identity")
    return registry, allocation


def inventory(directory, freeze_path, phase, seed, source=SCIENCE):
    directory, source = Path(directory), Path(source)
    require((directory / "COMPLETE.json").is_file() and not (directory / "FAILED.json").exists(),
            "Only a successfully completed stage may be audited")
    complete, start, freeze = read(directory / "COMPLETE.json"), read(directory / "START.json"), read(freeze_path)
    require(complete["seed"] == seed and complete["stage"] == phase and start["phase"] == phase
            and start["seed"] == seed, "Stage/seed provenance mismatch")
    require(start["freeze_sha256"] == digest(freeze_path) and start["registered_commit"] == freeze["registered_commit"],
            "Execution did not use the supplied pre-outcome freeze")
    require(start["protocol_sha256"] == digest(source / "PROTOCOL.json") == freeze["protocol_sha256"],
            "Protocol changed after execution")
    require(phase in freeze["allowed_phases"], "Freeze did not authorize the completed phase")
    for name, identity in start["source_files"].items():
        path = (source.parent / name).resolve()
        require(path.is_relative_to(source.parent.resolve()) and freeze["source_files"].get(name) == identity
                and digest(path) == identity, f"Execution source identity differs: {name}")
    actual = {str(path.relative_to(directory)) for path in directory.rglob("*") if path.is_file()}
    require(actual == {*complete["files"], "COMPLETE.json"}, "Completed stage file inventory changed")
    for name, identity in complete["files"].items():
        path = (directory / name).resolve()
        require(path.is_relative_to(directory.resolve()) and digest(path) == identity, f"Stage member changed: {name}")
    return complete, start, freeze


def hard_output(path, registry, role, conditions):
    with np.load(path, allow_pickle=False) as packed:
        arrays = {name: packed[name].copy() for name in packed.files}
    expected_ids, marks = expected_pairs(registry, role, conditions)
    require(arrays["source_ids"].tolist() == expected_ids and arrays["conditions"].tolist() == marks,
            f"Hard output source-pair/condition alignment differs: {path}")
    n = len(expected_ids)
    require(arrays["pixels_u8"].shape == (n, 1, 28, 56) and arrays["pixels_u8"].dtype == np.uint8
            and len(arrays["captions_utf8"]) == n, "Hard decoded output shape/type differs")
    actual_hashes = [hashlib.sha256(pixels.tobytes() + caption.encode("utf-8")).hexdigest()
                     for pixels, caption in zip(arrays["pixels_u8"], arrays["captions_utf8"].tolist(), strict=True)]
    require(actual_hashes == arrays["output_sha256"].tolist(), f"Decoded pixel/UTF8 bytes changed: {path}")
    values = {name.removeprefix("values_"): value for name, value in arrays.items() if name.startswith("values_")}
    require(set(values) == {"reward"} and values["reward"].shape == (n,) and np.isfinite(values["reward"]).all(),
            "Reference/bank output values have an unexpected observer or shape")
    return {"values": values["reward"], "mean": float(values["reward"].mean()), "hashes": actual_hashes,
            "rows": n, "file_sha256": digest(path)}


def checkpoint(path, protocol, seed):
    import torch
    record = torch.load(path, map_location="cpu", weights_only=True)
    require(record["schema"] == "hepta.field-bridge.v3.complete-adapter.1"
            and record["training_configuration"] == protocol["training"]
            and record["metadata"]["seed"] == seed, "Checkpoint schema/configuration/seed differs")
    expected_names = {module + suffix for module in protocol["training"]["adapter_modules"] for suffix in (".down", ".up")}
    require(set(record["parameters"]) == expected_names, "Incomplete adapter parameter inventory")
    parameter_digest = hashlib.sha256()
    for name, value in record["parameters"].items():
        require(value.dtype == torch.float32 and torch.isfinite(value).all(), "Invalid checkpoint parameter")
        require(value.ndim == 2 and value.shape[0 if name.endswith(".down") else 1] == 8, "Adapter rank changed")
        parameter_digest.update(name.encode())
        parameter_digest.update(value.contiguous().numpy().tobytes())
    optimizer = record["optimizer"]
    optimizer_digest = hashlib.sha256(json.dumps(optimizer["param_groups"], sort_keys=True).encode())
    for index, fields in sorted(optimizer["state"].items()):
        optimizer_digest.update(str(index).encode())
        for name, value in sorted(fields.items()):
            optimizer_digest.update(name.encode())
            if torch.is_tensor(value):
                require(torch.isfinite(value).all(), "Nonfinite optimizer state")
                optimizer_digest.update(value.detach().contiguous().numpy().tobytes())
            else:
                optimizer_digest.update(repr(value).encode())
    identity = {"parameters": parameter_digest.hexdigest(), "optimizer": optimizer_digest.hexdigest()}
    require(identity == record["identity"], "Complete checkpoint parameter/optimizer hash differs")
    parameters = [index for group in optimizer["param_groups"] for index in group["params"]]
    require(parameters == list(range(16)) and set(optimizer["state"]) <= set(parameters), "Optimizer parameter inventory differs")
    for group in optimizer["param_groups"]:
        require(group["momentum"] == .9 and group["dampening"] == 0 and group["weight_decay"] == 0
                and not group["nesterov"] and not group["maximize"] and group["lr"] in {.05, .2, .4}, "Optimizer dynamics changed")
    ordered = list(record["parameters"].values())
    for index, state in optimizer["state"].items():
        require(set(state) == {"momentum_buffer"} and state["momentum_buffer"].shape == ordered[index].shape,
                "Optimizer momentum tensor inventory differs")
    momentum_square = sum(float(state["momentum_buffer"].double().square().sum()) for state in optimizer["state"].values())
    count = sum(value.numel() for value in ordered)
    return {"identity": identity, "metadata": record["metadata"], "frozen_base_sha256": record["frozen_base_sha256"],
            "file_sha256": digest(path), "parameter_count": count, "momentum_l2": momentum_square ** .5,
            "momentum_rms": (momentum_square / count) ** .5}


def journal(path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream]
    for index, row in enumerate(rows):
        require(row["record_index"] == index and row["committed_monotonic_ns"] > 0, "Journal sequence differs")
        if index:
            require(row["committed_monotonic_ns"] >= rows[index - 1]["committed_monotonic_ns"], "Journal clock reversed")
    return rows, {bound(row): row for row in rows}


def expected_schedule(seed, schedule_id, start, count, p):
    return [{"step": step, "adapt_seed": seed * 100003 + p["batch_seed_offset"] + schedule_id * 1009 + step,
             "clean_seed": seed * 100003 + p["rehearsal_seed_offset"] + schedule_id * 1009 + step,
             "noise_seed": p["forward_seed_offset"] + step, "condition": p["conditions"][step % 4]}
            for step in range(start, start + count)]


def paired_block(decision, outcome, baseline, seed, p):
    receipt = outcome["receipt"]
    require(decision["record_index"] < outcome["record_index"] and
            decision["committed_monotonic_ns"] < outcome["committed_monotonic_ns"], "Decision did not precede outcome")
    require(decision["seed"] == seed and receipt["start"] == decision["step"] and receipt["end"] == decision["step"] + 48
            and receipt["schedule_id"] == decision["schedule_id"] and receipt["action_index"] == decision["action_index"],
            "Block scope/action/time mismatch")
    expected = bound(expected_schedule(seed, receipt["schedule_id"], receipt["start"], 48, p))
    require(receipt["schedule_sha256"] == decision["schedule_sha256"] == expected and receipt["before"] == decision["before"],
            "Before-state or future minibatch schedule differs")
    require(receipt["clock_advances_on_rejection"] is True and receipt["multiplier"] == p["multipliers"][receipt["action_index"]],
            "Action or rejection clock convention differs")
    guard = np.asarray(receipt["guard_values"], dtype=float)
    require(guard.shape == baseline.shape and np.isfinite(guard).all() and len(receipt["guard_output_sha256"]) == len(guard),
            "Guard output coverage differs")
    delta = float((guard - baseline).mean())
    check_close(receipt["guard_delta"], delta, "Guard eligibility arithmetic differs")
    require(receipt["accepted"] == (delta >= p["guard_min_delta"]), "Guard acceptance differs")
    require(receipt["after"] == receipt["candidate"] if receipt["accepted"] else receipt["after"] == receipt["before"],
            "Rejected/accepted optimizer transaction differs")
    if receipt["action_index"] == 0:
        require(receipt["candidate"] == receipt["before"] == receipt["after"] and receipt["accepted"], "Zero action is not an exact admissible hold")
    for edge in ("first_gradient", "last_gradient"):
        require(np.isfinite([receipt[edge]["loss"], receipt[edge]["unclipped_gradient_norm"]]).all()
                and receipt[edge]["optimizer_advanced"] == (receipt["action_index"] != 0), "Gradient edge record differs")
    resources = receipt["resources"]
    require(resources["scheduled_gradient_microsteps"] == 48 and resources["gradient_backward_calls"] == 48
            and resources["gradient_backward_examples"] == 48 * 96 and resources["transaction_snapshots"] == 1,
            "Block gradient/snapshot counters differ")
    return receipt


def cost_check(actual, phase, seed, block_receipts, registry, p):
    """Independent expected invocation counts, including rejected and zero work."""
    expected = {}
    action = p["fixed_actions"][str(seed)]
    factor = 1 + (action != 0)

    def forward(name, calls, examples):
        expected[name + "_calls"] = calls
        expected[name + "_examples"] = examples
        expected[name + "_refinement_examples"] = examples * factor

    def hard(name, role, conditions, repetitions):
        count = len(registry["roles"][role]["identities"]) // 2
        batches = (count + p["panel_batch_size"] - 1) // p["panel_batch_size"]
        calls, examples = repetitions * len(conditions) * batches, repetitions * len(conditions) * count
        forward(name + "_generator", calls, examples)
        expected[name + "_reward_observer_calls"] = 2 * calls
        expected[name + "_reward_observer_digit_examples"] = 2 * examples

    blocks = len(block_receipts)
    gradients = blocks * 48
    forward("gradient_generator", gradients * 2, gradients * 96)
    forward("gradient_teacher", gradients * 2, gradients * 96)
    expected.update(gradient_backward_calls=gradients, gradient_backward_examples=gradients * 96,
                    scheduled_gradient_microsteps=gradients, transaction_snapshots=blocks)
    expected["optimizer_steps"] = sum(row["action_index"] != 0 for row in block_receipts) * 48
    rejected = sum(not row["accepted"] for row in block_receipts)
    expected.update(rejected_blocks=rejected, accepted_blocks=blocks - rejected, discarded_gradient_microsteps=rejected * 48)
    hard("original_guard", "fit_guard", ["clean"], 1)
    hard("candidate_guard", "fit_guard", ["clean"], blocks)
    if phase == "reference":
        require(blocks == 24, "Reference must execute exactly24 blocks")
        for role, conditions in (("task", p["conditions"]), ("clean", ["clean"])):
            hard("reference_original_" + role, "reference_" + role, conditions, 1)
            hard("reference_endpoint_" + role, "reference_" + role, conditions, 4)
    else:
        require(phase == "bank" and blocks == 360, "Bank must execute336 reference-tail and24 path blocks")
        expected["complete_model_optimizer_clones"] = 96
        forward("directional_generator", 48, 24 * 96)
        forward("directional_teacher", 48, 24 * 96)
        expected.update(directional_backward_calls=24, directional_backward_examples=24 * 96,
                        directional_gradient_measurements=24, feature_probe_reverse_calls=72)
        probe_pairs = len(registry["roles"]["fit_probe"]["identities"]) // 2
        clean_pairs = len(registry["roles"]["fit_guard"]["identities"]) // 2
        probe_batches = ((probe_pairs + p["panel_batch_size"] - 1) // p["panel_batch_size"]) * 4
        clean_batches = (clean_pairs + p["panel_batch_size"] - 1) // p["panel_batch_size"]
        forward("adapt_feature_probe", 24 * probe_batches, 24 * probe_pairs * 4)
        forward("clean_feature_probe", 24 * clean_batches, 24 * clean_pairs)
        expected["feature_probe_reverse_examples"] = 24 * (2 * probe_pairs * 4 + clean_pairs)
        hard("current_hard_value", "fit_probe", p["conditions"], 24)
        hard("terminal_fit_label", "fit_probe", p["conditions"], 96)
        forward("margin_generator", 24 * probe_batches, 24 * probe_pairs * 4)
        expected["margin_reward_observer_calls"] = 48 * probe_batches
        expected["margin_reward_observer_digit_examples"] = 48 * probe_pairs * 4
    require(all(isinstance(value, int) and value >= 0 for value in actual.values()), "Invalid resource-counter type/value")
    unexpected = set(actual) - set(expected)
    require(not unexpected, f"Unclassified actual resource counters: {sorted(unexpected)}")
    for key, value in expected.items():
        require(actual.get(key, 0) == value, f"Resource counter differs: {key}: {actual.get(key, 0)} != {value}")
    return {"all_recorded_invocation_counters_exact": True, "scheduled_gradient_microsteps": gradients,
            "gradient_examples": gradients * 96, "accepted_blocks": blocks - rejected, "rejected_blocks": rejected,
            "count_scope": "actual measured forward/backward/probe/observer invocations and transactional counters, not FLOPs"}
