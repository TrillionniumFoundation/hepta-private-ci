"""Frozen A/B execution, with complete path seals before endpoint access."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import time

import numpy as np
import torch

from ..multimodal_output_portfolio.field_bridge_v3_20261027 import learning
from ..multimodal_output_portfolio.field_bridge_v3_20261027.assets import load_assets
from .bank import append_history, build_bank, initialize, load_heads, measure, write_json
from .branching import BASELINES, codec, dynamics_identity, strict, timed
from .heads import choose
from .sources import load_training_roles

ROOT = Path(__file__).resolve().parents[2]


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_freeze(path, phase):
    freeze = json.loads(Path(path).read_text())
    if phase not in freeze["allowed_phases"] or len(freeze["registered_commit"]) != 40:
        raise ValueError("Phase is not source-registered")
    for name, digest in freeze["source_files"].items():
        source = (ROOT / name).resolve()
        if not source.is_relative_to(ROOT) or file_hash(source) != digest:
            raise ValueError("Frozen source differs: " + name)
    for name, digest in freeze.get("artifacts", {}).items():
        if file_hash(name) != digest:
            raise ValueError("Frozen input artifact differs: " + name)
    return freeze


class Budget:
    def __init__(self, root, costs, phase):
        self.root, self.costs, self.phase = Path(root), costs, phase
        self.wall, self.cpu = time.monotonic(), time.process_time()

    def __call__(self):
        stat = os.statvfs(self.root)
        if stat.f_bavail * stat.f_frsize < 2 * 1024 ** 3 or stat.f_favail < 2000:
            raise RuntimeError("Registered disk/inode reserve exhausted")
        raw = sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file())
        if raw > 1024 ** 3:
            raise RuntimeError("Global 1 GiB raw evidence cap exhausted")
        if time.monotonic() - self.wall > 10800 or time.process_time() - self.cpu > 7200:
            raise RuntimeError("Registered per-seed wall/CPU ceiling exhausted")
        cap = 39168 if self.phase == "A" else 23040
        if self.costs.values.get("scheduled_gradient_microsteps", 0) > cap:
            raise RuntimeError("Scheduled gradient ceiling exceeded")


def evaluate_paths(context, binding, heads, out, phase, check_budget):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    schedules = range(6000, 6004) if phase == "A" else range(106000, 106016)
    modes = ["ordinary", "field12", "full_current_state", "history6"]
    if phase == "B":
        modes.append("fixed_taper")
    rows = []
    for schedule_id in schedules:
        baseline_states = None
        for mode in modes:
            check_budget()
            before_cost = context.costs.snapshot()
            adapter = initialize(context, binding, schedule_id, mode)
            trace, states = [], []
            baseline = BASELINES[context.seed]
            for decision in range(6):
                check_budget()
                before, before_hash = adapter.seal()
                if mode in heads:
                    unused, unused_hash, unused_state, features, feature_receipt = measure(adapter)
                    action, choice = timed(context.costs, "head_decision", lambda: choose(heads[mode], features[mode], baseline))
                else:
                    action = baseline if mode == "ordinary" else [baseline, baseline, 2, 1, 1, 0][decision]
                    choice = {"chosen_action": action, "override": action != baseline, "fallback_reason": None}
                    features, feature_receipt = None, None
                receipt = adapter.transition(action)
                if features is not None:
                    append_history(adapter, features["field12"], action, receipt)
                state = adapter.capture()
                identity = dynamics_identity(state)
                states.append(identity)
                trace.append({"decision": decision, "before": before_hash, "choice": choice,
                              "transaction": receipt, "state": identity, "feature_receipt": feature_receipt})
            terminal, digest = adapter.seal()
            name = f"seed-{context.seed}-schedule-{schedule_id}-{mode}"
            checkpoint = out / (name + ".state")
            checkpoint.write_bytes(terminal)
            if mode == "ordinary":
                baseline_states = states
            first = next((i for i, (state, ref) in enumerate(zip(states, baseline_states, strict=True))
                          if state["dynamics"] != ref["dynamics"]), None)
            row = {"id": name, "seed": context.seed, "schedule_id": schedule_id, "method": mode,
                   "path": checkpoint.name, "sha256": digest, "bytes": len(terminal),
                   "first_legal_divergence_decision": first,
                   "first_legal_divergence_clock": None if first is None else (first + 1) * 48,
                   "terminal_reference_tail_state_equal": states[-1]["dynamics"] == baseline_states[-1]["dynamics"],
                   "overrides": sum(x["choice"]["override"] for x in trace),
                   "accepted_overrides": sum(x["choice"]["override"] and x["transaction"]["accepted"] for x in trace),
                   "costs": context.costs.since(before_cost), "trace": trace}
            rows.append(row)
            write_json(out / (name + ".json"), row)
            print(json.dumps({"stage": phase + "_paths", "seed": context.seed, "schedule": schedule_id,
                              "method": mode, "overrides": row["overrides"], "first_divergence": first}), flush=True)
    expected = 16 if phase == "A" else 80
    if len(rows) != expected:
        raise ValueError("Incomplete paired path inventory")
    result = {"complete": True, "phase": phase, "seed": context.seed, "paths": rows,
              "training_complete": True, "new_endpoint_roles_opened": []}
    write_json(out / "PATHS.json", result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--freeze", required=True)
    parser.add_argument("--phase", required=True, choices=["A", "B"])
    parser.add_argument("--seed", required=True, type=int, choices=[17, 29, 43])
    args = parser.parse_args()
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    random.seed(291029 + args.seed)
    np.random.seed(291029 + args.seed)
    torch.manual_seed(291029 + args.seed)
    freeze = verify_freeze(args.freeze, args.phase)
    protocol_path = Path(learning.__file__).with_name("PROTOCOL.json")
    protocol = json.loads(protocol_path.read_text())
    originals, observers, identities = load_assets(args.assets, [args.seed], ["reward"])
    corpus = load_training_roles(args.assets, args.phase, ["development_gradient", "development_rehearsal",
                                                        "development_probe", "development_guard"])
    context = learning.make_context(originals[args.seed], corpus, observers, args.seed, "development", protocol)
    binding = {"study_id": "hepta.parameter-field.fullstudy.20261029.1", "runtime_sha256": codec.digest(strict.runtime_descriptor()),
               "source_freeze_sha256": file_hash(args.freeze), "protocol_sha256": freeze["protocol_sha256"]}
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    out = root / ("stage_" + args.phase) / f"seed-{args.seed}"
    out.mkdir(parents=True, exist_ok=False)
    budget = Budget(root, context.costs, args.phase)
    try:
        if args.phase == "A":
            heads, unused = build_bank(context, binding, out / "bank", budget)
        else:
            heads = load_heads(root / "stage_A" / f"seed-{args.seed}" / "bank")
        paths = evaluate_paths(context, binding, heads, out / "paths", args.phase, budget)
        budget()
        expected = 39168 if args.phase == "A" else 23040
        if context.costs.values.get("scheduled_gradient_microsteps") != expected:
            raise ValueError("Final physical work count differs from registered design")
        write_json(out / "COMPLETE.json", {"complete": True, "phase": args.phase, "seed": args.seed,
                   "registered_commit": freeze["registered_commit"], "source_freeze_sha256": file_hash(args.freeze),
                   "costs": context.costs.snapshot(), "path_count": len(paths["paths"]), "assets": identities,
                   "wall_seconds": time.monotonic() - budget.wall, "cpu_seconds": time.process_time() - budget.cpu})
    except BaseException as error:
        write_json(out / "FAILED.json", {"complete": False, "error_type": type(error).__name__, "message": str(error),
                   "costs": context.costs.snapshot(), "partial_evidence_preserved": True,
                   "wall_seconds": time.monotonic() - budget.wall, "cpu_seconds": time.process_time() - budget.cpu})
        raise


if __name__ == "__main__":
    main()
