"""Persistent maintenance state and new-process restoration for engineering only.

Jobs have finite deadlines, while recurrent state persists across job changes.
The physical job and its prior action history restart; model memory does not.
These diagnostics add no independent confirmation samples or utility claims.
"""

import argparse
import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from experiments.continuous_boundary_flow import common as flow_common
from experiments.continuous_boundary_flow import math_model
from experiments.continuous_boundary_flow.common import named_seed, write_records
from experiments.continuous_boundary_flow.math_model import (
    TaskSpec,
    build_model,
    sample_step,
    solve_dp,
)
from experiments.continuous_boundary_flow.native.adapter import ACTIONS, Q
from experiments.first_passage_cell import kernels
from . import cells, features
from . import common as policy_common
from .common import OBJECTIVE, CostMeter, canonical, kind_for, save_json, sha
from .features import FeatureMap
from .native import bridge as bridge_module
from .native.bridge import ScoreBridge

ARMS = ("dual_flow", "generic_gru", "elman_mlp")
DIAGNOSTIC_SEED = named_seed(2203, "boundary-policy:engineering-maintenance.v1")


def source_hashes():
    root = Path(__file__).resolve().parents[2]
    paths = [
        Path(__file__),
        Path(__file__).with_name("engineering.py"),
        Path(cells.__file__),
        Path(features.__file__),
        Path(math_model.__file__),
        Path(kernels.__file__),
        Path(bridge_module.__file__),
        Path(flow_common.__file__),
        Path(policy_common.__file__),
    ]
    return {str(path.relative_to(root)): sha(path.read_bytes()) for path in paths}


def plain(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    return value


def contexts_from_saved(payload):
    if payload["phase"] != "training" or payload["seed"] != 2203:
        raise ValueError(
            "Engineering uses only the declared first seed's training contexts"
        )
    contexts, digest = [], hashlib.sha256()
    for row in payload["contexts"]:
        spec = TaskSpec(**row["spec"])
        if spec.horizon > 16:
            raise ValueError("Job deadline exceeds the declared feature scale")
        model = build_model(spec, n_grid=64, x_max=4.8)
        dp = solve_dp(model)
        digest.update(canonical(row["spec"]))
        for value in (model.x, model.transition, model.reward, dp["q"]):
            digest.update(np.asarray(value, dtype=np.float64).tobytes())
        contexts.append(
            {"id": row["id"], "index": row["index"], "model": model, "dp": dp}
        )
    if not contexts:
        raise ValueError("No saved training contexts")
    return contexts, digest.hexdigest()


class MaintenanceStream:
    def __init__(self, checkpoint, contexts_payload, bindings, *, snapshot=None):
        self.checkpoint, self.contexts_payload, self.bindings = (
            checkpoint,
            contexts_payload,
            bindings,
        )
        if sha(canonical(checkpoint) + b"\n") != bindings["checkpoint_sha256"]:
            raise ValueError("Selected checkpoint binding changed")
        if (
            sha(canonical(contexts_payload) + b"\n")
            != bindings["training_contexts_sha256"]
        ):
            raise ValueError("Training context binding changed")
        if bindings["sources"] != source_hashes():
            raise ValueError("Engineering source changed after checkpoint")
        self.arm = checkpoint["arm"]
        if self.arm not in ARMS or checkpoint["seed"] != 2203:
            raise ValueError("Unexpected engineering model")
        self.params, self.kind = cells.deserialize(checkpoint["model"])
        if self.kind != kind_for(self.arm):
            raise ValueError("Selected model architecture changed")
        self.contexts, self.context_digest = contexts_from_saved(contexts_payload)
        self.maps = [
            FeatureMap(
                context,
                self.arm,
                checkpoint["candidate"],
                checkpoint.get("boundary_weights"),
            )
            for context in self.contexts
        ]
        self.rng = np.random.Generator(np.random.Philox(DIAGNOSTIC_SEED))
        self.state = {
            "tick": 0,
            "context_position": 0,
            "state_idx": -1,
            "elapsed": 0,
            "hidden": [0.0] * 6,
            "previous_failed": 0.0,
            "previous_risk": 0.0,
            "previous_repair": 0.0,
            "jobs_started": 0,
            "jobs_completed": 0,
            "stop_jobs": 0,
            "deadline_jobs": 0,
            "failure_windows": 0,
            "repair_windows": 0,
            "sum_job_discounted_utility": 0.0,
            "max_abs_hidden": 0.0,
            "max_abs_score": 0.0,
        }
        if snapshot is not None:
            if (
                snapshot["schema"] != "hepta.boundary-policy.maintenance-checkpoint.v1"
                or snapshot["bindings"] != bindings
                or snapshot["reconstructed_contexts_sha256"] != self.context_digest
            ):
                raise ValueError("Maintenance checkpoint provenance changed")
            self.state = copy.deepcopy(snapshot["maintenance"])
            self.rng.bit_generator.state = snapshot["rng"]
            hidden = np.asarray(self.state["hidden"])
            context = self.contexts[self.state["context_position"]]
            if (
                hidden.shape != (6,)
                or not np.isfinite(hidden).all()
                or np.any(np.abs(hidden) > 1)
                or not 0 <= self.state["elapsed"] <= context["model"].spec.horizon
                or not -1 <= self.state["state_idx"] < context["model"].n_states
            ):
                raise ValueError("Invalid restored maintenance state")

    def snapshot(self):
        return {
            "schema": "hepta.boundary-policy.maintenance-checkpoint.v1",
            "selected_checkpoint": self.checkpoint,
            "training_contexts": self.contexts_payload,
            "bindings": self.bindings,
            "reconstructed_contexts_sha256": self.context_digest,
            "maintenance": copy.deepcopy(self.state),
            "rng": plain(self.rng.bit_generator.state),
            "job_boundary_semantics": "new physical job clears prior risk/failure/repair; recurrent hidden is preserved",
        }

    def advance(self, bridge):
        s = self.state
        context = self.contexts[s["context_position"]]
        started = None
        if s["state_idx"] < 0 or s["elapsed"] == context["model"].spec.horizon:
            hidden_before_job = s["hidden"].copy()
            s["context_position"] = int(self.rng.integers(len(self.contexts)))
            context = self.contexts[s["context_position"]]
            initial_uniform = float(self.rng.random())
            s["state_idx"] = int(
                np.searchsorted(
                    np.cumsum(context["model"].initial_distribution), initial_uniform
                )
            )
            s.update(
                elapsed=0, previous_failed=0.0, previous_risk=0.0, previous_repair=0.0
            )
            s["jobs_started"] += 1
            if s["hidden"] != hidden_before_job:
                raise ValueError("Model memory was reset at a job boundary")
            started = {
                "context_position": s["context_position"],
                "initial_uniform": initial_uniform,
                "model_state_reset": False,
            }
        model = context["model"]
        before = copy.deepcopy(s)
        x, reset = self.maps[s["context_position"]].step(
            [s["state_idx"]],
            model.spec.horizon - s["elapsed"],
            [s["previous_failed"]],
            [s["previous_risk"]],
            [s["previous_repair"]],
        )
        hidden = np.asarray([s["hidden"]])
        scores, after = cells.step(x, reset, hidden, self.params, self.kind)
        if (
            np.max(np.abs(after)) > 1
            or np.max(np.abs(scores)) > 8
            or not np.isfinite(after).all()
            or not np.isfinite(scores).all()
        ):
            raise ValueError("Long-running recurrent bound failed")
        quantized = np.rint(scores[0] * Q).astype(np.int64).tolist()
        request = {
            "row_id": f"engineering.{self.arm}.t{s['tick']}",
            "model_sha256": self.bindings["checkpoint_sha256"],
            "objective_sha256": OBJECTIVE,
            "observation_sha256": sha(
                canonical(
                    {"features": x[0].tolist(), "reset_fraction": float(reset[0])}
                )
            ),
            "state_sha256": sha(
                canonical({"before": hidden[0].tolist(), "after": after[0].tolist()})
            ),
            "scores_q24": quantized,
        }
        result = bridge.decide_batch([request])
        if result["actual_kernel_calls"] != 0 or result["actual_ndu_calls"] != 1:
            raise ValueError("Unexpected engineering native call contract")
        receipt = result["rows"][0]
        action = ACTIONS.index(receipt["action"])
        expected_action = 2 - int(np.argmax(np.asarray(quantized)[::-1]))
        if action != expected_action:
            raise ValueError("Original NDU did not consume the supplied scores")
        uniforms = self.rng.random((1, 5))
        trace = sample_step(
            model, np.array([s["state_idx"]]), np.array([action]), uniforms=uniforms
        )
        reward = float(trace["reward"][0])
        s["sum_job_discounted_utility"] += model.gamma ** s["elapsed"] * reward
        s["tick"] += 1
        s["elapsed"] += 1
        s["state_idx"] = int(trace["next_state_idx"][0])
        s["hidden"] = after[0].tolist()
        s["previous_failed"] = float(trace["failed"][0])
        s["previous_risk"] = (
            0.0
            if trace["F_after_action"][0] is None
            else float(trace["F_after_action"][0])
        )
        s["previous_repair"] = float(action == 1)
        s["failure_windows"] += int(trace["failed"][0])
        s["repair_windows"] += int(action == 1)
        s["max_abs_hidden"] = max(s["max_abs_hidden"], float(np.max(np.abs(after))))
        s["max_abs_score"] = max(s["max_abs_score"], float(np.max(np.abs(scores))))
        if action == 2 or s["elapsed"] == model.spec.horizon:
            s["jobs_completed"] += 1
            s["stop_jobs"] += int(action == 2)
            s["deadline_jobs"] += int(action != 2)
        return {
            "tick": before["tick"],
            "job_started": started,
            "context_id": context["id"],
            "state_before": before,
            "features": x[0].tolist(),
            "reset_fraction": float(reset[0]),
            "scores_float": scores[0].tolist(),
            "scores_q24": quantized,
            "native_receipt": receipt,
            "action": ("wait", "repair", "stop")[action],
            "uniforms": uniforms[0].tolist(),
            "reward": reward,
            "active_time": float(trace["active_time"][0]),
            "tau_hit": trace["tau_hit"][0],
            "maintenance_after": copy.deepcopy(s),
        }


def replay(checkpoint_path, score_binary, output_dir, ticks=16):
    """A fresh Python process reconstructs everything from the saved checkpoint."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    snapshot = json.loads(Path(checkpoint_path).read_bytes())
    meter = CostMeter()
    stream = MaintenanceStream(
        snapshot["selected_checkpoint"],
        snapshot["training_contexts"],
        snapshot["bindings"],
        snapshot=snapshot,
    )
    bridge = ScoreBridge(
        score_binary,
        output / "native",
        expected_binary_sha256=snapshot["bindings"]["score_binary_sha256"],
    )
    records = []
    try:
        for _ in range(ticks):
            records.append(stream.advance(bridge))
    finally:
        native_cost = bridge.close()
    cost = meter.finish()
    evidence = write_records(output / "records.jsonl.gz", records)
    evidence["path"] = "records.jsonl.gz"
    summary = {
        "schema": "hepta.boundary-policy.cold-maintenance-replay.v1",
        "passed": True,
        "source_checkpoint_sha256": sha(Path(checkpoint_path).read_bytes()),
        "starting_tick": snapshot["maintenance"]["tick"],
        "ending_tick": stream.state["tick"],
        "ticks": ticks,
        "record_sha256": [sha(canonical(row)) for row in records],
        "final_checkpoint_sha256": sha(canonical(stream.snapshot())),
        "records": evidence,
        "cost": cost,
        "native_cost_subset": native_cost,
        "process_scope": "fresh Python process and fresh original-NDU score host; no sparse kernel or durable owner",
    }
    save_json(output / "SUMMARY.json", summary)
    save_json(output / "FINAL_CHECKPOINT.json", stream.snapshot())
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--score-binary", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--ticks", type=int, default=16)
    args = parser.parse_args()
    if not 1 <= args.ticks <= 64:
        raise ValueError("Bounded engineering replay requires 1..64 ticks")
    result = replay(args.checkpoint, args.score_binary, args.output, args.ticks)
    print(json.dumps({"passed": result["passed"], "ticks": result["ticks"]}))


if __name__ == "__main__":
    main()
