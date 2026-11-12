"""Execute a synthetic F/L/R campaign; retained bytes are not owner authority.

F keeps model and learner fixed. L trains with a frozen proposal distribution.
R proposes an A-only update to that distribution and inherits it only when B
selects the corresponding model. C cold-loads the selected artifacts. D is read
only after the search seal. This single-process reference has no independent
evaluator, real task sources, OS-enforced data isolation, or RSI qualification.
"""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np

from ._causal_checks import _number, _pin, _require, _sha
from .evolve1_reference import (
    POLICIES,
    accuracy,
    bind,
    data_pin,
    dataset,
    ledger,
    meter,
    save_json,
    stream_seed,
    train,
)


class ReferenceStore:
    """Retain immutable content and check local bytes, without granting trust."""

    def __init__(self, root):
        self.root = Path(root)
        self.sequence = 0
        plan = self.root / "plan.json"
        self.plan_digest = _sha(json.loads(plan.read_text())) if plan.exists() else None

    def put(self, folder, pin, value):
        path = self.root / folder / f"{pin}.json"
        if path.exists():
            _require(json.loads(path.read_text()) == value, "FLR_ARTIFACT_COLLISION")
        else:
            save_json(path, value)
        return pin

    def model(self, weights):
        return self.put("models", bind(weights), weights.tolist())

    def learner(self, value):
        return self.put("learners", _sha(value), value)

    def cold_load(self, model, learner):
        _require(_pin(model) and _pin(learner), "FLR_ARTIFACT_PIN")
        weights = np.asarray(
            json.loads((self.root / "models" / f"{model}.json").read_text())
        )
        rule = json.loads((self.root / "learners" / f"{learner}.json").read_text())
        _require(bind(weights) == model and _sha(rule) == learner, "FLR_COLD_READBACK")
        return weights, rule

    def emit(self, kind, run_id, owner, **values):
        _require(_pin(self.plan_digest), "FLR_PLAN_NOT_FROZEN")
        self.sequence += 1
        record = {
            "kind": kind,
            "run_id": run_id,
            "actor_id": owner,
            "sequence": self.sequence,
            "plan_digest": self.plan_digest,
            **values,
        }
        return self.put("evidence", _sha(record), record)

    def read(self, kind, reference):
        _require(_pin(reference), "FLR_EVIDENCE_PIN")
        path = self.root / "evidence" / f"{reference}.json"
        if not path.exists():
            return None
        record = json.loads(path.read_text())
        _require(
            _sha(record) == reference and record.get("kind") == kind,
            "FLR_EVIDENCE_READBACK",
        )
        return record

    def verify(self, kind, record, owner):
        return (
            record.get("actor_id") == owner and self.read(kind, _sha(record)) == record
        )

    def samples(self, plan, source_id):
        _require(_sha(plan) == self.plan_digest, "FLR_REFERENCE_PLAN_CHANGED")
        source = plan["sources"][source_id]
        if source["split"] == "D":
            from .flr_contract import summarize_campaign

            sealed = json.loads((self.root / "records.json").read_text())
            _require(sealed["seal"] is not None, "FLR_D_REQUIRES_SEARCH_SEAL")
            # Replay only the search prefix; never recursively open D evidence.
            sealed["audits"] = {arm: None for arm in "FLR"}
            prefix = summarize_campaign(
                plan, sealed, read_evidence=self.read, verify_evidence=self.verify
            )
            _require(
                prefix["complete_rounds"] == 3 * plan["generations"],
                "FLR_D_REQUIRES_COMPLETE_SEARCH",
            )
        folder = "sealed-data" if source["split"] == "D" else "data"
        value = json.loads(
            (self.root / folder / f"{source['digest']}.json").read_text()
        )
        result = tuple(np.asarray(part) for part in value)
        _require(data_pin(result) == source["digest"], "FLR_SOURCE_READBACK")
        return result


def _settle(costs, wall, cpu):
    """Add the disjoint run-envelope residual, including bookkeeping and I/O."""
    elapsed = {
        "wall_seconds": time.perf_counter() - wall,
        "cpu_seconds": time.process_time() - cpu,
    }
    old = costs["controller"]["values"]
    values = {
        unit: old.get(unit, 0)
        + max(
            0.0,
            value - sum(cell["values"].get(unit, 0) or 0 for cell in costs.values()),
        )
        for unit, value in elapsed.items()
    }
    costs["controller"] = {
        "status": "measured",
        "values": {**values, "energy_joules": None, "provider_charges": None},
        "evidence": "disjoint local envelope residual; energy and charges unknown",
    }


def _check_budget(plan, records, row, wall, cpu):
    """Cooperatively stop new work on known overrun; unknown meters stay unknown."""
    for unit, elapsed in (
        ("wall_seconds", time.perf_counter() - wall),
        ("cpu_seconds", time.process_time() - cpu),
    ):
        previous = sum(
            cell["values"].get(unit, 0) or 0
            for other in records["rounds"]
            if other["arm"] == row["arm"] and other is not row
            for cell in other["costs"].values()
        )
        shared = sum(
            cell["values"].get(unit, 0) or 0
            for cell in records["publication_costs"].values()
        )
        _require(
            previous + shared + elapsed < plan["budget"]["limits"][unit],
            "FLR_REFERENCE_RESOURCE_BUDGET",
        )


def _propose_learner(weights, prior, samples, seed, admit, store, plan, records, row):
    """Fit proposal probabilities on A only; the meta-update algorithm is fixed."""
    fitting = tuple(part[:128] for part in samples)
    development = tuple(part[128:] for part in samples)
    scores = []
    for index, policy in enumerate(POLICIES):
        _require(
            len(row["learner_search"]) < plan["budget"]["learner_trials"],
            "FLR_LEARNER_TRIAL_BUDGET",
        )
        trial_id = f"{row['run_id']}/learner-trial-{index}"
        trial = {
            "trial_id": trial_id,
            "operation_id": trial_id + "/operation",
            "training_sources": plan["schedule"][row["generation"]]["A"],
            "training_model": row["model_before"],
            "training_learner": row["learner_before"],
            "status": "UNKNOWN",
            "result_model": None,
            "utility": None,
        }
        row["learner_search"].append(trial)
        save_json(store.root / "records.json", records)
        try:
            admit()
            candidate = train(weights, fitting, policy, seed + index, steps=16)
            trial["result_model"] = store.model(candidate)
            trial["utility"] = accuracy(candidate, development)
            trial["status"] = "SUCCEEDED"
        except BaseException as error:
            if isinstance(error, Exception):
                trial["status"] = "FAILED"
            raise
        finally:
            save_json(store.root / "records.json", records)
        scores.append(trial["utility"])
    logits = np.log(np.asarray(prior["probabilities"])) + 8 * np.asarray(scores)
    probabilities = np.exp(logits - max(logits))
    probabilities = 0.9 * probabilities / probabilities.sum() + 0.1 / len(POLICIES)
    return {
        "schema": "hepta.flr.reference-learner.v1",
        "policies": [list(p) for p in POLICIES],
        "probabilities": probabilities.tolist(),
        "parent": _sha(prior),
    }


def _round(store, plan, records, states, generation, arm, seed):
    wall, cpu = time.perf_counter(), time.process_time()
    model, learner = states[arm]
    run_id = f"{plan['campaign_id']}/{generation}/{arm}"
    row = {
        "run_id": run_id,
        "arm": arm,
        "generation": generation,
        "information": plan["information"],
        "model_before": model,
        "learner_before": learner,
        "attempts": [],
        "learner_search": [],
        "decision": {
            "kind": "UNAVAILABLE",
            "selected_attempt": None,
            "model_after": model,
            "learner_after": learner,
            "evidence_ref": None,
        },
        "use_ref": None,
        "costs": ledger(),
    }
    records["rounds"].append(row)
    costs = row["costs"]

    def admit():
        _check_budget(plan, records, row, wall, cpu)

    try:
        save_json(store.root / "records.json", records)
        admit()
        with meter(costs, "recovery"):
            start, rule = store.cold_load(model, learner)
        selected = None
        best = None
        if arm != "F":
            with meter(costs, "collection"):
                training = store.samples(plan, plan["schedule"][generation]["A"][0])
            proposed = rule
            with meter(costs, "search"):
                if arm == "R":
                    proposed = _propose_learner(
                        start,
                        rule,
                        training,
                        stream_seed(seed, f"meta-{generation}"),
                        admit,
                        store,
                        plan,
                        records,
                        row,
                    )
                proposed_pin = store.learner(proposed)
                proposals = np.random.default_rng(
                    stream_seed(seed, f"proposals-{generation}")
                ).choice(
                    len(POLICIES),
                    size=plan["budget"]["candidate_attempts"],
                    p=proposed["probabilities"],
                )
            for number, policy_index in enumerate(proposals):
                attempt_id = f"{run_id}/attempt-{number}"
                attempt = {
                    "attempt_id": attempt_id,
                    "operation_id": attempt_id + "/operation",
                    "candidate_model": model,
                    "candidate_learner": proposed_pin,
                    "training_sources": plan["schedule"][generation]["A"],
                    "training_model": model,
                    "training_learner": learner,
                    "status": "UNKNOWN",
                    "b_queries": 0,
                    "evaluation_ref": None,
                }
                row["attempts"].append(attempt)
                save_json(store.root / "records.json", records)
                try:
                    admit()
                    with meter(costs, "training"):
                        candidate = train(
                            start,
                            training,
                            POLICIES[policy_index],
                            stream_seed(seed, f"train-{generation}-{number}"),
                        )
                    with meter(costs, "io"):
                        attempt["candidate_model"] = store.model(candidate)
                    # Reserve and persist B access before opening the selection data.
                    used = sum(
                        a["b_queries"]
                        for r in records["rounds"]
                        if r["arm"] == arm
                        for a in r["attempts"]
                    )
                    _require(
                        used < plan["budget"]["b_queries"], "FLR_B_BUDGET_EXHAUSTED"
                    )
                    admit()
                    attempt["b_queries"] = 1
                    save_json(store.root / "records.json", records)
                    with meter(costs, "evaluation"):
                        selection = store.samples(
                            plan, plan["schedule"][generation]["B"][0]
                        )
                        utility, baseline = (
                            accuracy(candidate, selection),
                            accuracy(start, selection),
                        )
                        attempt["evaluation_ref"] = store.emit(
                            "B",
                            run_id,
                            plan["evaluation_owner"],
                            attempt_id=attempt_id,
                            operation_id=attempt["operation_id"],
                            source_ids=plan["schedule"][generation]["B"],
                            model=attempt["candidate_model"],
                            learner=proposed_pin,
                            baseline_model=model,
                            utility=utility,
                            baseline_utility=baseline,
                        )
                        attempt["status"] = "SUCCEEDED"
                    if (
                        utility > baseline
                        and utility - baseline >= plan["minimum_gain"]
                        and (best is None or utility > best)
                    ):
                        selected, best = attempt, utility
                except BaseException as error:
                    if isinstance(error, Exception):
                        attempt["status"] = "FAILED"
                    save_json(store.root / "records.json", records)
                    raise
                save_json(store.root / "records.json", records)
        decision = row["decision"]
        admit()
        decision["kind"] = "FROZEN_CONTROL" if arm == "F" else "NO_UPDATE"
        if selected is not None:
            decision.update(
                kind="ADOPT",
                selected_attempt=selected["attempt_id"],
                model_after=selected["candidate_model"],
                learner_after=selected["candidate_learner"],
            )
        with meter(costs, "evaluation"):
            decision["evidence_ref"] = store.emit(
                "selection",
                run_id,
                plan["evaluation_owner"],
                attempts_digest=_sha(row["attempts"]),
                learner_search_digest=_sha(row["learner_search"]),
                decision=decision["kind"],
                selected_attempt=decision["selected_attempt"],
                model=decision["model_after"],
                learner=decision["learner_after"],
            )
        save_json(store.root / "records.json", records)
        states[arm] = decision["model_after"], decision["learner_after"]
        with meter(costs, "recovery"):
            retained, _ = store.cold_load(*states[arm])
        admit()
        with meter(costs, "evaluation"):
            source_ids = plan["schedule"][generation]["C"]
            scores = {
                source_id: accuracy(retained, store.samples(plan, source_id))
                for source_id in source_ids
            }
            row["use_ref"] = store.emit(
                "C",
                run_id,
                plan["evaluation_owner"],
                source_ids=source_ids,
                model=states[arm][0],
                learner=states[arm][1],
                entrypoint=plan["ordinary_entrypoint"],
                scores=scores,
            )
    finally:
        _settle(costs, wall, cpu)
        save_json(store.root / "records.json", records)


def run_campaign(
    output,
    source_commit,
    source_tree,
    *,
    generations=3,
    seed=41,
    attempts=3,
    wall_budget=600.0,
    cpu_budget=300.0,
):
    """Run and persist a new campaign; interruptions preserve an incomplete journal."""
    from .flr_contract import summarize_campaign
    from .flr_plan import validate_plan

    _require(_pin(source_commit, 40) and _pin(source_tree, 40), "FLR_SOURCE_IDENTITY")
    _require(
        type(generations) is int
        and 2 <= generations <= 16
        and type(seed) is int
        and 0 <= seed < 2**32
        and type(attempts) is int
        and 1 <= attempts <= 16,
        "FLR_REFERENCE_BOUNDS",
    )
    _require(
        all(
            _number(value, minimum=0) and value > 0
            for value in (wall_budget, cpu_budget)
        ),
        "FLR_REFERENCE_BUDGET",
    )
    wall, cpu = time.perf_counter(), time.process_time()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    for folder in ("models", "learners", "evidence", "data", "sealed-data"):
        (output / folder).mkdir()
    store = ReferenceStore(output)
    publication = ledger()
    publication["io"] = {
        "status": "unknown",
        "values": {
            "wall_seconds": None,
            "cpu_seconds": None,
            "energy_joules": None,
            "provider_charges": None,
        },
        "evidence": "imports and final report publication require external metering",
    }
    with meter(publication, "preparation"):
        sources, schedule = {}, []
        for generation in range(generations):
            schedule.append({})
            for split in ("A", "B", "C"):
                source_id = f"g{generation}-{split}"
                samples = dataset(
                    stream_seed(seed, source_id),
                    256,
                    "uniform" if split == "C" else "gaussian",
                )
                pin = data_pin(samples)
                store.put("data", pin, [part.tolist() for part in samples])
                sources[source_id] = {
                    "group": f"synthetic-reference-{split}",
                    "split": split,
                    "digest": pin,
                }
                schedule[generation][split] = [source_id]
        # Precompute and retain D to bind its real bytes; the actor never reads it.
        # This process-level convention is explicitly not independent data custody.
        audit = dataset(stream_seed(seed, "external-D"), 256, "uniform")
        pin = data_pin(audit)
        store.put("sealed-data", pin, [part.tolist() for part in audit])
        sources["external-D"] = {
            "group": "synthetic-reference-D",
            "split": "D",
            "digest": pin,
        }
        del audit
        initial_model = store.model(np.zeros(9))
        initial_learner = store.learner(
            {
                "schema": "hepta.flr.reference-learner.v1",
                "policies": [list(p) for p in POLICIES],
                "probabilities": [1 / len(POLICIES)] * len(POLICIES),
                "parent": None,
            }
        )
        plan = {
            "schema": "hepta.flr.plan.v1",
            "campaign_id": f"synthetic-flr-{seed}",
            "source": {"commit": source_commit, "tree": source_tree},
            "initial_model": initial_model,
            "initial_learner": initial_learner,
            "generations": generations,
            "information": _sha({"sources": sources, "schedule": schedule}),
            "budget": {
                "candidate_attempts": attempts,
                "learner_trials": len(POLICIES),
                "b_queries": generations * attempts,
                "limits": {
                    "wall_seconds": wall_budget,
                    "cpu_seconds": cpu_budget,
                    "energy_joules": 1e9,
                    "provider_charges": 1e9,
                },
            },
            "minimum_gain": 0.01,
            "sources": sources,
            "schedule": schedule,
            "audit_sources": ["external-D"],
            "evaluation_owner": "local-reference-evaluator",
            "ordinary_entrypoint": "flr_reference.cold_load_then_score",
        }
        validate_plan(plan)
        save_json(output / "plan.json", plan)
        store.plan_digest = _sha(plan)
        context = {
            "schema": "hepta.flr.reference-execution.v1",
            "seed": seed,
            "python": platform.python_version(),
            "numpy": np.__version__,
            "source_sha256": {
                name: hashlib.sha256(
                    Path(__file__).with_name(name).read_bytes()
                ).hexdigest()
                for name in (
                    "flr_reference.py",
                    "flr_contract.py",
                    "flr_plan.py",
                    "evolve1_reference.py",
                    "_causal_checks.py",
                    "causal_improver.py",
                )
            },
            "candidate_steps": 64,
            "candidate_batch_size": 32,
            "R_A_only_meta_trials_per_generation": len(POLICIES),
            "R_meta_steps_per_trial": 16,
            "D_custody": "same-process sealed file; no OS or independent-owner isolation",
            "meter_scope": "local CPU execution; imports and final report publication excluded",
            "budget_enforcement": "cooperative wall/CPU admission between bounded calls; energy/charges unknown",
            "independent_real_sources": 0,
            "independent_owner": False,
            "native_ordinary_entrypoint": False,
            "scientific_efficacy_qualified": False,
            "production_adoption_qualified": False,
            "rsi_qualified": False,
        }
        save_json(output / "execution.json", context)
    records = {
        "schema": "hepta.flr.run.v1",
        "plan_digest": _sha(plan),
        "rounds": [],
        "seal": None,
        "audits": {arm: None for arm in "FLR"},
        "publication_costs": publication,
    }
    save_json(output / "records.json", records)
    states = {arm: (initial_model, initial_learner) for arm in "FLR"}
    for generation in range(generations):
        for arm in "FLR":
            try:
                _round(store, plan, records, states, generation, arm, seed)
            except BaseException:
                save_json(output / "records.json", records)
                raise
    store.sequence += 1
    records["seal"] = {
        "rounds_digest": _sha(records["rounds"]),
        "sequence": store.sequence,
    }
    save_json(output / "records.json", records)
    for arm in "FLR":
        try:
            _check_budget(
                plan, records, {"arm": arm}, time.perf_counter(), time.process_time()
            )
            with meter(publication, "recovery"):
                retained, _ = store.cold_load(*states[arm])
            with meter(publication, "evaluation"):
                scores = {
                    source_id: accuracy(retained, store.samples(plan, source_id))
                    for source_id in plan["audit_sources"]
                }
                records["audits"][arm] = store.emit(
                    "D",
                    f"{plan['campaign_id']}/{arm}",
                    plan["evaluation_owner"],
                    source_ids=plan["audit_sources"],
                    model=states[arm][0],
                    learner=states[arm][1],
                    scores=scores,
                )
        finally:
            save_json(output / "records.json", records)
    # Subtract disjoint arm envelopes before settling campaign overhead.
    row_wall = sum(
        cell["values"].get("wall_seconds", 0) or 0
        for row in records["rounds"]
        for cell in row["costs"].values()
    )
    row_cpu = sum(
        cell["values"].get("cpu_seconds", 0) or 0
        for row in records["rounds"]
        for cell in row["costs"].values()
    )
    _settle(publication, wall + row_wall, cpu + row_cpu)
    save_json(output / "records.json", records)
    # Reopen retained originals; callbacks authenticate local bytes only.
    plan = json.loads((output / "plan.json").read_text())
    records = json.loads((output / "records.json").read_text())
    report = summarize_campaign(
        plan, records, read_evidence=store.read, verify_evidence=store.verify
    )
    save_json(output / "report.json", report)
    return {"plan": plan, "records": records, "report": report, "execution": context}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--generations", type=int, default=3)
    parser.add_argument("--seed", type=int, default=41)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--wall-budget", type=float, default=600.0)
    parser.add_argument("--cpu-budget", type=float, default=300.0)
    args = parser.parse_args()
    result = run_campaign(
        args.output,
        args.source_commit,
        args.source_tree,
        generations=args.generations,
        seed=args.seed,
        attempts=args.attempts,
        wall_budget=args.wall_budget,
        cpu_budget=args.cpu_budget,
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "status": result["report"].get("status"),
                "scientific_efficacy_qualified": False,
                "rsi_qualified": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
