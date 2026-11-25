"""Create immutable pilot/formal protocols before any test labels exist."""
import argparse
import hashlib
import itertools
import json
from pathlib import Path

from common import dump, runtime, sha, utc, validate_sources
from runner import case_name, source_hashes


def build(args):
    target = Path(args.out)
    if target.exists():
        raise FileExistsError("Protocol identity is immutable")
    diagnosis = Path(args.diagnosis)
    if sha(diagnosis) != "11c3ad04e214c5f8655a473804c935a2e68d015995dcd12343b0f20cc422455d":
        raise ValueError("Unexpected diagnostic evidence")
    rows = [r for r in json.loads(diagnosis.read_text())["rows"] if r["kind"] == "fresh"]
    candidates = (1e-8, 1e-6, 1e-4, .02)
    scores = {v: sum(next(c["dev"]["cross_entropy"] for c in r["ridge_controls"]
                          if c["scaled"] and c["ridge"] == v) for r in rows) / len(rows) for v in candidates}
    chosen = min(scores, key=scores.get)
    pilot = args.mode == "pilot"
    pilot_record = None
    if not pilot:
        if not args.pilot_result or not args.cache_check:
            raise ValueError("Formal registration requires complete pilot and cache-equivalence evidence")
        pilot_record = json.loads(Path(args.pilot_result).read_text())
        if args.physical_lr != pilot_record["chosen_physical_lr"]:
            raise ValueError("Formal learning rate must use the global pilot rule")
        if not json.loads(Path(args.cache_check).read_text())["passed"]:
            raise ValueError("Operator cache equivalence did not pass")
    seeds = (1701,) if pilot else (2101, 2102, 2103)
    lrs = (1e-5, 1e-4) if pilot else (args.physical_lr,)
    messages = ("full",) if pilot else ("boundary", "flow", "full")
    connections = ("learned",) if pilot else ("learned", "fixed")
    cases = [{"width": n, "seed": seed, "bank": bank, "message": message, "connection": connection,
              "train_n": 64, "physical_lr": lr, "group": "pilot" if pilot else "main_factorial"}
             for lr, n, seed, bank, message, connection in itertools.product(
                 lrs, (8, 16, 32, 64), seeds, ("value_risk", "tanh"), messages, connections)]
    if not pilot:
        cases += [{"width": n, "seed": seed, "bank": bank, "message": "full", "connection": "learned",
                   "train_n": samples, "physical_lr": args.physical_lr, "group": "sample_efficiency"}
                  for n, seed, bank, samples in itertools.product((16, 32), seeds, ("value_risk", "tanh"), (16, 32))]
    hashes = source_hashes()
    protocol = {"experiment": "actual-hcsn-v2-" + args.mode + "-20261125", "registered_utc": utc(),
                "phase": "diagnosis" if pilot else "formal", "source_hashes": hashes,
                "physical_source": validate_sources(), "runtime": runtime(), "cases": cases,
                "initialization_rule": "torch.manual_seed(seed + 101 * width); identical initial tensor mechanism for all arms",
                "fresh_parents_only": True, "backend": "dense", "precision": "float64",
                "operator_reuse": "same differentiable dense matrix exponential within a frozen control epoch; train-only equivalence checked",
                "fixed_mask_is_not_learned_topology": True, "data": {
                    "seed": 271 if pilot else 31415, "per_source_train": 16, "per_source_dev": 16,
                    "per_source_test": 32, "pre_late_Bayes_accuracy": .75,
                    "test_source_ids": [] if pilot else [540200, 540201, 540202, 540203]},
                "ridge": chosen, "scale_floor": 1e-6, "head_lr": .001, "gradient_clip": 1.,
                "max_updates": args.max_updates, "optimization_cpu_budget_s": args.cpu_budget,
                "optimization_wall_budget_s": args.wall_budget, "batch_size": 8,
                "development_steps": [s for s in (4, 8, 16, 32, 64, 96, 128, 192, 256) if s <= args.max_updates],
                "dev_selection": "minimum final-step cross entropy; initial scaled ridge head is eligible; no test selection",
                "loss": "final-step cross entropy only; no supervision with unrevealed future targets at early steps",
                "hyperparameter_rule": {"ridge": "one penalty minimizing mean diagnostic fresh-parent dev CE across all 8 width/bank arms",
                                       "diagnosis_sha256": sha(diagnosis),
                                       "diagnostic_penalty_mean_dev_CE": scores,
                                       "physical_lr": "pilot train/dev learning curves only; same global value for every formal arm"},
                "budget_scope": "same maximum updates and optimization-only CPU/wall envelopes; setup/validation/IO also separately timed",
                "censored_budget_is_not_completed_updates": True, "test_quality_threshold_accuracy": .85,
                "test_generation_before_seal_forbidden": True, "old_test_read": False,
                "parameter_capacity_note": "allocated dimensions vary by width; freezing recurrent parameters intentionally changes trainable count",
                "sample_efficiency_note": "nested same-source 16/32/64 training sets; 64-label rows reused from main factorial; ridge labels counted"}
    if args.pilot_result:
        protocol["pilot_results_sha256"] = sha(args.pilot_result)
        protocol["pilot_budget_rationale"] = pilot_record["formal_budget_decision"]
    if args.cache_check:
        protocol["operator_cache_equivalence_result_sha256"] = sha(args.cache_check)
    descriptor = {key: protocol[key] for key in ("data", "source_hashes", "cases")}
    protocol["group_and_test_generation_descriptor_sha256"] = hashlib.sha256(
        json.dumps(descriptor, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if len({case_name(c) for c in cases}) != len(cases):
        raise ValueError("Duplicate case names")
    dump(target, protocol)
    print(json.dumps({"path": str(target), "sha256": sha(target), "cases": len(cases),
                      "ridge": chosen, "groups": {g: sum(c["group"] == g for c in cases)
                                                  for g in sorted({c["group"] for c in cases})}}))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("pilot", "formal"), required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--diagnosis", required=True)
    p.add_argument("--pilot-result")
    p.add_argument("--cache-check")
    p.add_argument("--max-updates", type=int, default=96)
    p.add_argument("--cpu-budget", type=float, default=30.)
    p.add_argument("--wall-budget", type=float, default=45.)
    p.add_argument("--physical-lr", type=float, default=1e-5)
    build(p.parse_args())
