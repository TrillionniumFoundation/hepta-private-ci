"""Read-only metric correction and fair cold-feature replay of frozen readers.

No models, thresholds, task sources, or outcome labels are changed. Original
formal-01 telemetry is retained. Each arm starts with an empty feature cache;
the authenticated base model remains resident and its load cost is separate.
This measures decision latency, not a second end-to-end compiler benchmark.
"""

import argparse
import hashlib
import json
from pathlib import Path
import resource
import sys
import time

import numpy as np
import torch

from features import Encoder
from models import load
from task_experiment import Policies, decision, summarize, write
from tasks import ACTIONS, Task, diagnostic_rule, observation_text, transform


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--encoder", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(2)
    original = json.loads((args.input / "RESULTS.json").read_text())
    for name, digest in original["protocol"]["source_sha256"].items():
        if sha(args.input / "source-snapshot" / name) != digest:
            raise ValueError("original frozen source snapshot mismatch")
    files = [p for p in args.input.rglob("*") if p.is_file()]
    inventory = {str(p.relative_to(args.input)): dict(bytes=p.stat().st_size, sha256=sha(p)) for p in files}
    sources = {name: sha(Path(__file__).parent / name) for name in
               ("task_audit.py", "task_experiment.py", "tasks.py", "models.py", "features.py")}
    protocol = dict(schema="hepta.memory.v11.task-audit-protocol.v1", argv=sys.argv,
                    original_result_sha256=sha(args.input / "RESULTS.json"), sources=sources,
                    cache="empty feature cache separately for every seed/phase/arm, shared resident immutable base",
                    mutation="no training, model updates, recalibration or policy changes",
                    timing_scope="sequential decision calls including cold encoding; original uncached compiler timing separate",
                    original_telemetry_errata=["patch_attempts included None decisions", "tool_calls was an inferred formula", "arm-order shared encoding cache prevents independent cold-latency comparison"])
    write(args.output / "PROTOCOL.json", protocol)
    write(args.output / "ORIGINAL_INPUT_INVENTORY.json", inventory)
    encoder = Encoder(args.encoder)
    corrections, costs = {}, {}
    for seed in original["protocol"]["seeds"]:
        source = args.input / str(seed)
        x = np.load(source / "training-matrices.npz")["x"]
        train_rows = json.loads((source / "training-observations.json").read_text())
        models = {name: load(source / "models" / name) for name in
                  ("single_model", "capacity_control", "semantic", "predictive", "routing")}
        policies = Policies(encoder, x, [r["text"] for r in train_rows],
                            np.array([r["label"] for r in train_rows]), models)
        calibration = json.loads((source / "calibration.json").read_text())
        corrections[str(seed)], costs[str(seed)] = {}, {}
        for phase, arms in original["scores"][str(seed)].items():
            task_rows = json.loads((source / (phase + ".json")).read_text())
            tasks = [Task(**row) for row in task_rows]
            cases = {task.case_id: task for task in tasks}
            corrections[str(seed)][phase], costs[str(seed)][phase] = {}, {}
            for arm, previous in arms.items():
                raw = json.loads((source / (phase + "-" + arm + ".json")).read_text())
                encoder.cache.clear()
                before = encoder.receipt()
                started, cpu = time.perf_counter(), time.process_time()
                decision_wall, decision_cpu = 0.0, 0.0
                compared, decisions_out = 0, []
                for outcome in raw:
                    task = cases[outcome["case_id"]]
                    current = task.source
                    applied = 0
                    for index, step in enumerate(outcome["trace"]):
                        key = hashlib.sha256(current.encode()).hexdigest()
                        if key != step["observed_source_sha256"]:
                            raise ValueError("raw trace cannot be reconstructed from actual source transformations")
                        observation = json.loads((source / "compiler-observations" / (key + ".json")).read_text())
                        began, began_cpu = time.perf_counter(), time.process_time()
                        if arm == "compiler_rule":
                            action = diagnostic_rule(observation)
                        else:
                            probabilities = policies.probabilities(arm, observation_text(current, observation))
                            label = decision(probabilities, calibration[arm]["selected"]["threshold"])
                            action = ACTIONS[label] if label < 4 else None
                        decision_wall += time.perf_counter() - began
                        decision_cpu += time.process_time() - began_cpu
                        if arm != "compiler_rule" and not np.allclose(
                                probabilities, step["information"]["probabilities"], atol=1e-5, rtol=1e-5):
                            raise ValueError("saved reader output changed during cost replay")
                        if action != step["action"]:
                            raise ValueError("policy action changed during read-only replay")
                        compared += 1
                        if action is not None:
                            line = observation["diagnostics"][0]["line"] if observation["diagnostics"] else None
                            updated = transform(current, action, line=line)
                        else:
                            updated = current
                        step["applied"] = updated != current
                        applied += step["applied"]
                        current = updated
                    if hashlib.sha256(current.encode()).hexdigest() != outcome["final"]["source_sha256"]:
                        raise ValueError("raw final source identity differs")
                    outcome["observation_requests"] = 1 + applied
                    outcome["actual_compiler_calls"] = 1 + applied
                    outcome["cache_hits"] = 0
                    decisions_out.append(dict(case_id=outcome["case_id"], original_outcome_unchanged=True,
                                              observed_requests=1 + applied, applied_patches=applied))
                corrected = summarize(raw, tasks)
                if corrected["tool_calls"] != previous["actual_compiler_calls"]:
                    raise ValueError("reconstructed requests disagree with measured original compiler calls")
                corrections[str(seed)][phase][arm] = corrected
                after = encoder.receipt()
                costs[str(seed)][phase][arm] = dict(decision_events=compared,
                    decision_wall_seconds=decision_wall, decision_cpu_seconds=decision_cpu,
                    audit_loop_wall_seconds=time.perf_counter() - started,
                    audit_loop_cpu_seconds=time.process_time() - cpu,
                    encoding_wall_seconds=after["encode_wall_seconds"] - before["encode_wall_seconds"],
                    encoding_cpu_seconds=after["encode_cpu_seconds"] - before["encode_cpu_seconds"],
                    encoded_texts=after["encoded_texts"] - before["encoded_texts"],
                    padded_tokens=after["padded_tokens"] - before["padded_tokens"],
                    feature_cache_payload_bytes=after["cache_payload_bytes"],
                    original_uncached_compiler_wall_seconds=previous["compiler_wall_seconds"],
                    observation_requests=corrected["tool_calls"], predictions_verified_identical=True)
                write(args.output / f"{seed}-{phase}-{arm}.json", dict(costs=costs[str(seed)][phase][arm],
                      corrected_counts=corrected, decisions=decisions_out))
                print(json.dumps(dict(seed=seed, phase=phase, arm=arm, **costs[str(seed)][phase][arm])), flush=True)
    if any(sha(Path(__file__).parent / name) != digest for name, digest in sources.items()):
        raise RuntimeError("audit source changed during run")
    if any(sha(args.input / name) != entry["sha256"] for name, entry in inventory.items()):
        raise RuntimeError("original evidence changed during audit")
    write(args.output / "RESULTS.json", dict(protocol=protocol, corrected_counts=corrections, costs=costs,
          encoder=encoder.receipt(), peak_process_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
          complete=True, note="Reconstructed counters and separately measured decision costs supersede the original derived telemetry fields; original success outcomes remain unchanged."))


if __name__ == "__main__":
    main()
