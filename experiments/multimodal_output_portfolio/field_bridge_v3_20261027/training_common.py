"""Small explicit V3 training contracts; importing this module opens no data."""

import gzip
import hashlib
import json
from pathlib import Path
import re
import time


REQUIRED = (
    "steps", "macro_steps", "adapter_modules", "adapter_rank", "learning_rate", "momentum",
    "gradient_clip", "adapt_batch_size", "rehearsal_batch_size", "clean_loss_weight", "teacher_anchor",
    "guard_min_delta", "multipliers", "conditions", "refinement_charge", "fixed_actions", "ridges",
    "generic_projection_seed", "exploration_paths", "fit_schedule_ids", "reference_schedule_id", "development_schedule_ids",
    "audit_schedule_ids", "final_schedule_id", "panel_batch_size", "reference_clean_min_delta",
    "ordinary_clean_min_delta", "init_seed_offset", "batch_seed_offset", "rehearsal_seed_offset",
    "forward_seed_offset", "panel_seed_offset", "probe_forward_seed_offset", "hard_forward_seed_offset",
    "value_target", "candidate_mode", "feature_modes", "feature_dimension")
MODES = ("field", "generic", "richer", "h7")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def object_hash(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def configuration(protocol):
    config = protocol["training"]
    require(not (set(REQUIRED) - set(config)), f"Missing training choices: {sorted(set(REQUIRED)-set(config))}")
    require(config["steps"] == 288 and config["macro_steps"] == 48, "V3 requires six 48-step decisions")
    require(config["adapt_batch_size"] == 64 and config["rehearsal_batch_size"] == 32,
            "V3 requires the common 64+32 example objective")
    require(config["clean_loss_weight"] == .5 and config["teacher_anchor"] == .1,
            "Weighted training objective differs from the registered treatment")
    require(config["multipliers"] == [0., .25, 1., 2.] and config["guard_min_delta"] == 0.,
            "Action family or empirical retention guard differs")
    paths = [[(trajectory + decision) % 4 for decision in range(6)] for trajectory in range(4)]
    require(config["exploration_paths"] == paths, "Balanced exploratory action paths differ")
    require(config["ridges"] == [1e-4, .01, 1.], "The three ridge candidates must be predeclared")
    require(config["candidate_mode"] == "field" and config["feature_modes"] == list(MODES)
            and config["feature_dimension"] == {"field": 12, "generic": 12, "richer": 30, "h7": 7},
            "The field treatment and comparison representations must remain prospectively fixed")
    require(len(config["fit_schedule_ids"]) == 4 and len(set(config["fit_schedule_ids"])) == 4,
            "Four distinct fit schedules are required")
    require(len(config["adapter_modules"]) == 8 and config["adapter_rank"] == 8,
            "The prospective actuator must keep the eight upstream rank-eight adapters")
    require(config["panel_batch_size"] > 0 and len(config["conditions"]) == 4, "Invalid panel definition")
    return config


class Costs:
    """Count actual invocations/examples; these counters are not FLOPs or latency."""

    def __init__(self):
        self.values = {}

    def add(self, name, amount=1):
        self.values[name] = self.values.get(name, 0) + int(amount)

    def forward(self, name, examples, action):
        self.add(name + "_calls")
        self.add(name + "_examples", examples)
        self.add(name + "_refinement_examples", examples * (1 + (action != 0)))

    def snapshot(self):
        return dict(self.values)

    def since(self, previous):
        return {key: value - previous.get(key, 0) for key, value in sorted(self.values.items())
                if value != previous.get(key, 0)}


class Journal:
    """Append-only compressed decisions/outcomes, with an immediately flushed commit."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = gzip.open(self.path, "xt", encoding="utf-8")
        self.count = 0

    def append(self, value):
        record = {**value, "record_index": self.count, "committed_monotonic_ns": time.monotonic_ns()}
        self.stream.write(canonical(record).decode() + "\n")
        self.stream.flush()
        self.count += 1
        return object_hash(record)

    def close(self):
        self.stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.close()


def verify_freeze(path, protocol_path, phase, run_root):
    """Freeze is external to scientific files, avoiding a circular source hash."""
    record = json.loads(Path(path).read_text())
    require(re.fullmatch(r"[0-9a-f]{40}", record["registered_commit"]), "A committed source identity is required")
    require(phase in record["allowed_phases"], f"The freeze does not authorize phase {phase}")
    require(file_hash(protocol_path) == record["protocol_sha256"], "Protocol differs from source freeze")
    portfolio = Path(__file__).parent.parent
    for name, identity in record["source_files"].items():
        location = (portfolio / name).resolve()
        require(location.is_relative_to(portfolio.resolve()), "Unsafe frozen source path")
        require(file_hash(location) == identity, f"Frozen source changed: {name}")
    for name, identity in record.get("artifacts", {}).items():
        location = (Path(run_root) / name).resolve()
        require(location.is_relative_to(Path(run_root).resolve()), "Unsafe frozen artifact path")
        require(file_hash(location) == identity, f"Frozen prior-stage artifact changed: {name}")
    return record
