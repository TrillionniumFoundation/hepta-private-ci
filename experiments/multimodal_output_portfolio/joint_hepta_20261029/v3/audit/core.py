"""Independent artifact, ledger and synthetic-source audit primitives.

No runtime scoring/accounting helper is imported. The registered mechanism
generator is reused solely to reconstruct the source-bound public input/target.
"""

from collections import Counter, defaultdict
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re
import wave

import numpy as np
from PIL import Image
import torch

from ...mechanism_data import batch


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def tensor_digest(value):
    """Independently reproduce the declared tensor-tree identity format."""
    result = hashlib.sha256()
    def visit(node):
        if torch.is_tensor(node):
            item = node.detach().cpu().contiguous()
            result.update(str((str(item.dtype), tuple(item.shape))).encode())
            result.update(item.numpy().tobytes())
        elif isinstance(node, dict):
            for key in sorted(node):
                result.update(str(key).encode()); visit(node[key])
        elif isinstance(node, (tuple, list)):
            for item in node:
                visit(item)
        else:
            result.update(repr(node).encode())
    visit(value)
    return result.hexdigest()


def groups(state):
    return {group: tensor_digest({n: p for n, p in state.items() if (
        "actor" if n.startswith("actor.") else "critic" if n.startswith(("critic.", "delivery_critic."))
        else "generator") == group}) for group in ("generator", "actor", "critic")}


def ce(values, weights=None):
    values = np.asarray(values, dtype=np.float64)
    weights = np.ones_like(values) if weights is None else np.asarray(weights, dtype=np.float64)
    z = -2 * values
    top = z.max()
    return float(-(top + np.log(np.dot(weights, np.exp(z - top)) / weights.sum())) / 2)


class Audit:
    def __init__(self, root, log):
        self.root, self.log = Path(root), log
        self.counts, self.errors, self.notes = Counter(), [], []
        self.identities, self.inputs = defaultdict(set), defaultdict(set)
        self.max_utility_error = 0.0
        self.trace_rows = {}

    def check(self, condition, code, path, details=None):
        self.counts[code] += 1
        if not bool(condition):
            self.errors.append({"check": code, "path": str(path), "details": details})
        return bool(condition)

    def near(self, actual, expected, code, path, tolerance=1e-9):
        return self.check(math.isfinite(float(actual)) and math.isfinite(float(expected)) and
                          abs(float(actual) - float(expected)) <= tolerance,
                          code, path, {"actual": actual, "expected": expected, "tolerance": tolerance})

    def sources(self, source_map, directory):
        for name, expected in source_map.items():
            path = Path(directory) / name
            self.check(path.is_file() and sha(path) == expected, "source_sha256", path)


def decode(directory, *, audio_rate=2048, frame_ms=120):
    """Reopen all four files without calling media.read_bundle/utility."""
    directory = Path(directory)
    with Image.open(directory / "image.png") as image:
        visual = np.asarray(image.convert("RGB"), dtype=np.float32).transpose(2, 0, 1) / np.float32(255)
    with wave.open(str(directory / "audio.wav")) as sound:
        if (sound.getnchannels(), sound.getsampwidth(), sound.getframerate(), sound.getnframes()) != (1, 2, audio_rate, 1024):
            raise ValueError("Audio header differs from the declared profile")
        audio = np.frombuffer(sound.readframes(1024), dtype="<i2").astype(np.float32) / np.float32(32767)
    frames = []
    with Image.open(directory / "video.gif") as video:
        for index in range(video.n_frames):
            video.seek(index)
            duration = video.info.get("duration", 0)
            if duration <= 0 or duration % frame_ms or duration > 4 * frame_ms:
                raise ValueError("GIF duration outside registered expansion law")
            frame = np.asarray(video.convert("RGB"), dtype=np.float32).transpose(2, 0, 1) / np.float32(255)
            frames.extend([frame] * (duration // frame_ms))
    if visual.shape != (3, 16, 16) or len(frames) != 4 or any(f.shape != visual.shape for f in frames):
        raise ValueError("Media dimensions differ from the profile")
    text = (directory / "text.txt").read_text(encoding="utf-8")
    match = re.fullmatch(r"action=(\d+);sound=(\d+)\n", text)
    if not match or not (0 <= int(match[1]) < 63 and 0 <= int(match[2]) < 17):
        raise ValueError("Text outside the exact finite-label format")
    return {"image": visual[None], "audio": audio[None], "video": np.stack(frames)[None],
            "text": np.asarray([[int(match[1]), int(match[2])]], dtype=np.int64)}


@lru_cache(maxsize=1024)
def source(source_id):
    namespace, identity = source_id.removeprefix("synthetic.").rsplit(".", 1)
    if not identity.isdigit():
        raise ValueError("Synthetic identity is not an integer")
    public, target = batch([int(identity)], namespace)
    return namespace, int(identity), tensor_digest(public), {k: v.numpy() for k, v in target.items()}


def utility(sample, target):
    errors = sum(float(np.mean((sample[m].astype(np.float64) - target[m].astype(np.float64)) ** 2))
                 for m in ("image", "audio", "video"))
    return float(0.65 * math.exp(-4 * errors) + 0.35 * np.mean(sample["text"] == target["text"]))


def trajectory(audit, path, role, expected_parameter=None):
    path = Path(path)
    if str(path) in audit.trace_rows:
        return audit.trace_rows[str(path)]
    record, seal = read(path), read(path.with_name("SEAL_COST.json"))
    profile, events = record["profile"], record["events"]
    tariff = profile["tariff"]
    audit.check(digest(profile) == record["profile_sha256"], "trajectory_profile_identity", path)
    namespace, identity, input_hash, target = source(record["source_id"])
    audit.identities[role].add((namespace, identity)); audit.inputs[role].add(input_hash)
    audit.check(record["input_sha256"] == input_hash, "source_bound_input", path)
    if expected_parameter:
        audit.check(record["parameter_snapshot_sha256"] == expected_parameter, "selected_parameter_identity", path)
    all_events = events + [seal]
    audit.check(events[0]["action"] == "encode" and events[-1]["action"] == "audit_draft"
                and seal["action"] == "audit_close", "ledger_boundaries", path)
    for index, event in enumerate(all_events):
        service = event.get("attempted_service", event["action"])
        fee = tariff.get(service, 0.0)
        audit.near(event["service_fee"], fee, "service_fee", path)
        audit.check(event["cpu_seconds"] >= 0 and event["wall_seconds"] >= 0, "nonnegative_meter", path)
        amount = event["cpu_seconds"] * tariff["cpu_second"] + event["wall_seconds"] * tariff["wall_second"] + fee
        audit.near(event["amount"], amount, "meter_amount", path)
        # Restoring a frozen prefix may happen much later in wall/CPU time.
        # Its first suffix action folds the explicitly charged restore setup.
        if index > record["prefix_event_count"]:
            for clock in ("cpu", "wall"):
                audit.near(event[f"{clock}_seconds"], event[f"meter_{clock}_end"] - all_events[index-1][f"meter_{clock}_end"],
                           "continuous_suffix_meter", path, 2e-8)
    raw_cost = math.fsum(e["amount"] for e in events)
    cost = raw_cost + seal["amount"]
    observed = record["outcome"]["delivered_utility"]
    audit.near(record["actual_cost"], raw_cost, "trajectory_ledger_sum", path)
    audit.near(record["net_return"], observed - raw_cost, "preseal_return", path)
    audit.near(record["remaining_budget"], profile["initial_budget"] - raw_cost, "remaining_budget", path)
    audit.near(record["suffix_cost"], raw_cost - record["inherited_prefix_cost"], "preseal_suffix", path)
    audit.near(seal["actual_cost_through_seal"], cost, "sealed_ledger_sum", path)
    audit.near(seal["net_return_through_seal"], observed - cost, "sealed_return", path)
    if record["resumed"]:
        audit.near(record["inherited_prefix_cost"], math.fsum(e["amount"] for e in events[:record["prefix_event_count"]]),
                   "inherited_prefix_once", path)
    else:
        audit.near(record["inherited_prefix_cost"], 0, "fresh_prefix_not_inherited", path)
    chain = events[0]["after_state"]
    for event in events[1:]:
        if "before_state" in event:
            audit.check(event["before_state"] == chain, "state_hash_chain", path)
            chain = event["after_state"]
    audit.check(chain == record["state_sha256"], "terminal_state_hash", path)
    for action in record["actions"]:
        audit.check(0 < action["selected_probability"] <= 1.000001, "selected_action_legal_probability", path)
        if record["policy"] in ("fixed", "stop", "greedy"):
            audit.check(not action["sampled_actor"], "forced_action_no_actor_score", path)
    failure = record["failure"]
    audit.check((failure is None and record["outcome"]["terminal_kind"] == "delivered") or
                (failure is not None and record["outcome"]["terminal_kind"] == "failed" and observed == -1.0),
                "retained_failure_contract", path)
    filenames = {"image": "image.png", "audio": "audio.wav", "video": "video.gif", "text": "text.txt"}
    for modality, expected in record["outcome"]["artifact_sha256"].items():
        artifact = path.parent / "outputs" / filenames[modality]
        audit.check(artifact.is_file() and sha(artifact) == expected, "actual_artifact_sha256", artifact)
    recomputed = None
    if failure is None:
        audit.check(set(record["outcome"]["artifact_sha256"]) == set(filenames), "complete_delivered_bundle", path)
        sample = decode(path.parent / "outputs", audio_rate=profile["audio_rate"], frame_ms=profile["frame_ms"])
        recomputed = utility(sample, target)
        error = abs(recomputed - observed)
        audit.max_utility_error = max(audit.max_utility_error, error)
        audit.near(observed, recomputed, "independent_media_utility", path, 2e-7)
        audit.check(record["actions"][-1]["action"] == "stop", "delivered_stop_terminal", path)
    row = {"path": str(path.relative_to(audit.root)), "source": record["source_id"], "role": role,
           "trajectory_sha256": sha(path), "seal_sha256": sha(path.with_name("SEAL_COST.json")),
           "utility": observed, "independent_utility": recomputed, "sealed_cost": cost,
           "sealed_return": observed - cost, "failure": failure,
           "parameter_sha256": record["parameter_snapshot_sha256"], "profile_sha256": record["profile_sha256"],
           "actions": [a["action"] for a in record["actions"]],
           "service_fee": math.fsum(e["service_fee"] for e in all_events)}
    audit.log.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
    audit.trace_rows[str(path)] = row
    audit.counts["trajectories"] += 1
    audit.counts["failures_retained"] += int(failure is not None)
    return row
