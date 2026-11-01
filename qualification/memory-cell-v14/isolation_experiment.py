"""Real V13-feature qualification of isolated retention and legal fallback.

These are the already inspected V13 authored tasks, not a new held population.
Project names and current source operation bindings are public input semantics.
"""

import argparse
import json
from pathlib import Path
import time

import numpy as np

from isolation import IsolatedMemory, canonical, dataset, sha, tasks
from provenance_run import source_body


ROOT = Path(__file__).resolve().parent


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def payload(inputs, name, project=None, event=None):
    _, rows = dataset(inputs, name)
    ids = [i for i, row in enumerate(rows) if project is None or row.get("project") == project]
    return json.loads(source_body(inputs, name, [rows[i] for i in ids], ids, event))


def evaluate(memory, inputs, frontier, label):
    traces = []
    for name in ["test"] + ([f"profile-{frontier}-test"] if frontier else []):
        X, rows = dataset(inputs, name)
        for i, row in enumerate(rows):
            kind, key = ("project", row["project"]) if "project" in row else ("skill", "skills")
            receipt = memory.read(kind, key, X[i:i + 1], scope=memory.scope,
                                  encoder_hash=memory.encoder_hash)
            score = tasks.score_prediction(row, receipt["predictions"][0]) if receipt["predictions"] else {
                "correct": False, "label_correct": False, "output": None, "error": "refused"}
            traces.append(dict(id=row["id"], kind=kind, key=key, query=row["text"],
                               expected_output=row["expected"], receipt=receipt, **score))
    return dict(stage=label, frontier=frontier, requests=len(traces),
                served=sum(t["receipt"]["mode"] != "refused" for t in traces),
                skill_correct=sum(t["correct"] for t in traces if t["kind"] == "skill"),
                project_correct=sum(t["correct"] for t in traces if t["kind"] == "project"),
                modes={m: sum(t["receipt"]["mode"] == m for t in traces)
                       for m in ("learned", "fallback", "refused")}, traces=traces)


def semantic(result):
    return [(r["id"], r["receipt"]["mode"], r["receipt"]["predictions"],
             r["receipt"]["artifact"], r["receipt"].get("source_revision")) for r in result["traces"]]


def run_seed(inputs, directory, encoder_hash, seed, skill_seed):
    directory.mkdir()
    scope = f"v14-isolated-seed-{seed}"
    memory = IsolatedMemory(directory / "owner", scope, encoder_hash)
    memory.put("skill", "skills", payload(inputs, "train"), expected_revision=0)
    candidates = [memory.fit_publish("skill", "skills", inputs, "calibration", seed=skill_seed)]
    if candidates[0]["status"] != "published":
        raise RuntimeError("initial independent skill model did not qualify")
    stages = [evaluate(memory, inputs, 0, "initial_skills")]
    initial = stages[0]["skill_correct"]
    for frontier in (3, 4, 5, 6):
        changed = []
        for event in tasks.profile_journal():
            if (frontier == 3 and event["sequence"] <= 3) or event["sequence"] == frontier:
                key = event["project"]
                old = memory.owner.source(scope, "project:" + key)
                memory.put("project", key, payload(inputs, f"profile-{frontier}-train", key, event),
                           expected_revision=old["revision"] if old else 0)
                changed.append(key)
        stages.append(evaluate(memory, inputs, frontier, "source_changed_before_candidate"))
        if frontier > 3:
            # A declared resource-limited candidate, not a forced validator switch.
            candidates.append(memory.fit_publish("project", changed[0], inputs,
                              f"profile-{frontier}-calibration", seed=seed, steps=1, lr=1e-6))
            stages.append(evaluate(memory, inputs, frontier, "after_one_small_actual_update"))
        for key in changed:
            candidates.append(memory.fit_publish("project", key, inputs,
                              f"profile-{frontier}-calibration", seed=seed))
        stages.append(evaluate(memory, inputs, frontier, "after_full_candidate"))
    source, current = memory._source("project", "amber")
    memory.put("project", "amber", current, expected_revision=source["revision"], active=False)
    stages.append(evaluate(memory, inputs, 6, "amber_revoked"))
    before = stages[-1]
    hashes = {row["cell"]: memory.owner.load(row["artifact"], scope, encoder_hash)[0].state_hash()
              for row in memory.owner.db.execute("SELECT * FROM releases WHERE scope=?", (scope,))}
    memory.close()
    memory = IsolatedMemory(directory / "owner", scope, encoder_hash)
    after = evaluate(memory, inputs, 6, "restart")
    stages.append(after)
    restored = {row["cell"]: memory.owner.load(row["artifact"], scope, encoder_hash)[0].state_hash()
                for row in memory.owner.db.execute("SELECT * FROM releases WHERE scope=?", (scope,))}
    checks = dict(skill_retention_exact=all(s["skill_correct"] == initial for s in stages),
                  active_frontiers_serviceable=all(s["served"] == s["requests"] for s in stages[:-2]),
                  current_project_outputs=all(s["project_correct"] == (12 if s["frontier"] else 0) for s in stages[:-2]),
                  revoked_only_amber=before["modes"]["refused"] == 4 and all(
                      t["key"] == "amber" for t in before["traces"] if t["receipt"]["mode"] == "refused"),
                  restart_semantic_identity=semantic(before) == semantic(after),
                  complete_state_identity=hashes == restored,
                  actual_rejection_observed=any(c["status"] == "rejected" for c in candidates))
    result = dict(project_seed=seed, fixed_skill_seed=skill_seed, checks=checks, candidates=candidates, stages=stages,
                  complete_state_hashes=restored, historical_weights_erased=False,
                  identical_v13_tasks_not_new_generalization_evidence=True)
    write(directory / "RESULTS.json", result)
    memory.close()
    return dict(project_seed=seed, fixed_skill_seed=skill_seed, checks=checks, initial_skill_correct=initial,
                candidates=len(candidates), rejected=sum(c["status"] == "rejected" for c in candidates),
                training_seconds=sum(c["training"]["seconds"] for c in candidates),
                checkpoint_bytes=sum(c["checkpoint_bytes"] for c in candidates),
                stages=[{k: v for k, v in s.items() if k != "traces"} for s in stages])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, default=ROOT.parent / "memory-cell-v13/evidence/inputs")
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/isolation-qualified-parent")
    parser.add_argument("--skill-seed", type=int, default=713)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((args.inputs / "encoder_manifest.json").read_text())
    plan = dict(project_seeds=[713, 971, 1237], fixed_skill_seed=args.skill_seed,
                skill_steps=240, project_steps=240, batch_size=20,
                correction_resource_limited_candidate=dict(steps=1, lr=1e-6),
                fresh_parameters_for_each_source=True, shared_skill_weights_never_project_trained=True,
                skill_gate="40/48 calibration", project_gate="all current project calibration outputs",
                source_sha256={p: sha((ROOT / p).read_bytes()) for p in ("isolation.py", "isolation_experiment.py")},
                input_sha256={p.name: sha(p.read_bytes()) for p in args.inputs.iterdir() if p.is_file()},
                original_backend=manifest, no_new_encoder_inference=True,
                note="V13 pretrained features reused; encoder preparation costs are inherited, not timed as zero.")
    write(args.output / "PLAN.json", plan)
    start, cpu = time.perf_counter(), time.process_time()
    reports = [run_seed(args.inputs, args.output / f"seed-{seed}", manifest["encoder_hash"], seed, args.skill_seed)
               for seed in plan["project_seeds"]]
    write(args.output / "SUMMARY.json", dict(runs=reports, all_lifecycle_checks=all(
        all(r["checks"].values()) for r in reports), wall_seconds=time.perf_counter() - start,
        cpu_seconds=time.process_time() - cpu,
        bytes_on_disk=sum(p.stat().st_size for p in args.output.rglob("*") if p.is_file()),
        efficacy_advantage_over_exact_storage_established=False,
        scope="single SQLite owner with independent cell artifacts; no production or unlearning claim"))
    print(json.dumps(reports, indent=2))


if __name__ == "__main__":
    main()
