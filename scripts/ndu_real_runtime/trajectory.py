"""Bounded, explicit episode chains; digests bind bytes, not observer authority."""

from collections import Counter, defaultdict
import math

from .controllers import ACTIONS
from .objective import MEMORY_MODES, canonical_sha

V2_SCHEMA = "ndu.real.training-transition.v2"
V2_FIELDS = {"episode_step", "previous_record_sha256", "record_sha256", "legal_actions",
             "remaining_seconds", "memory_mode", "utility_profile_sha256", "rubric_sha256", "behavior_control_profile_sha256"}


def is_digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def validate_link(row):
    step = row["episode_step"]
    if type(step) is not int or not 0 <= step < 8:
        raise ValueError("Episode step outside the recorded horizon")
    prior = row["previous_record_sha256"]
    if (step == 0 and prior is not None) or (step > 0 and not is_digest(prior)):
        raise ValueError("Invalid episode predecessor")
    if (row["memory_mode"] not in MEMORY_MODES
            or not all(is_digest(row[k]) for k in ("record_sha256", "utility_profile_sha256", "rubric_sha256", "behavior_control_profile_sha256"))):
        raise ValueError("Missing immutable training profile binding")
    remaining = row["remaining_seconds"]
    if type(remaining) not in (int, float) or not math.isfinite(remaining) or not 0 < remaining <= 3600:
        raise ValueError("Invalid observed remaining wall budget")
    legal = row["legal_actions"]
    if (not isinstance(legal, list) or not legal or len(set(legal)) != len(legal)
            or set(legal) - set(ACTIONS) or "STOP" not in legal or row["action"] not in legal):
        raise ValueError("Observed legal action support is invalid")
    if canonical_sha({k: v for k, v in row.items() if k != "record_sha256"}) != row["record_sha256"]:
        raise ValueError("Training record digest differs")


def validate_chains(records):
    groups = defaultdict(list)
    for row in records:
        if row["schema"] == V2_SCHEMA:
            validate_link(row)
            groups[(row["origin_run_id"], row["episode_id"])].append(row)
    for sequence in groups.values():
        sequence.sort(key=lambda r: r["episode_step"])
        first = sequence[0]
        for index, row in enumerate(sequence):
            if row["episode_step"] != index or any(row[k] != first[k] for k in
                ("source_group", "utility_profile_sha256", "rubric_sha256", "source_size", "memory_mode", "behavior_control_profile_sha256")):
                raise ValueError("Incomplete or mixed-profile episode chain")
            if index:
                previous = sequence[index - 1]
                if (previous["record_sha256"] != row["previous_record_sha256"]
                        or previous["next_candidate_features"] != row["candidate_features"]
                        or previous["next_public_metadata"] != row["public_metadata"]
                        or previous["after_score"] != row["before_score"]
                        or row["remaining_seconds"] > previous["remaining_seconds"]
                        or previous.get("terminal_reason") is not None):
                    raise ValueError("Episode predecessor or observed successor differs")
        last = sequence[-1]
        if (last["next_candidate_features"] is not None
                or (last.get("terminal_reason") not in {"actor_stop", "budget_stop"}
                    and last["execution_status"] != "failed")):
            raise ValueError("Episode chain has no observed terminal boundary")
    return len(groups)


def episode_groups(rows, memory_mode):
    if memory_mode == "reset":
        return [[row] for row in rows]
    if memory_mode != "persistent" or any(row["schema"] != V2_SCHEMA for row in rows):
        raise ValueError("Persistent unroll requires complete v2 episode chains")
    groups = defaultdict(list)
    for row in rows:
        groups[(row["origin_run_id"], row["episode_id"])].append(row)
    return [sorted(sequence, key=lambda r: r["episode_step"]) for sequence in groups.values()]


def memory_replay_metadata(rows, training_memory_mode):
    """Identify replayed encodings without reattributing the behavior outcomes."""
    if training_memory_mode not in MEMORY_MODES:
        raise ValueError("Unknown training memory mode")
    counts = Counter(row["memory_mode"] if row["schema"] == V2_SCHEMA else "legacy_v1_unspecified" for row in rows)
    known = sorted(mode for mode in counts if mode in MEMORY_MODES)
    changed = any(mode != training_memory_mode for mode in known)
    equal = False if changed else None if counts.get("legacy_v1_unspecified") or not rows else True
    return {"replayed_from_memory_modes": known, "collection_memory_mode_rows": dict(counts),
            "training_memory_mode": training_memory_mode, "memory_mode_changed_during_replay": changed,
            "collection_training_memory_equal": equal,
            "memory_replay_semantics": "candidate_latents_recomputed; recorded_behavior_actions_and_scores_unchanged",
            "on_policy_or_counterfactual_return_claimed": False}


def grouped_batches(groups, order, maximum_rows):
    batch, count = [], 0
    for index in order:
        group = groups[index]
        if batch and count + len(group) > maximum_rows:
            yield batch
            batch, count = [], 0
        batch.append(group)
        count += len(group)
    if batch:
        yield batch
