"""Run a bounded, synthetic replay-policy transfer pilot, without adoption.

This is a CPU reference learner, not HeptaCore or a real-task qualification.
The local evaluator callback checks retained bytes only: it is not an independent
owner attestation. Unknown energy/charges and native consumption remain unknown.
"""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np

from ._causal_checks import COST_STAGES, COST_UNITS, _sha
from .evolve1 import summarize_transfer
from .evolve1_reference import (
    POLICIES,
    accuracy,
    bind,
    data_pin,
    dataset,
    discover,
    ledger,
    meter,
    save_json,
    stream_seed,
    train,
)


def run_block(seed, attempts_per_arm, out, records, raw_results):
    lineage = f"lineage-{seed}"
    child, historical = discover(seed)
    parent = {
        "schema": "evolve1.frozen-proposer.v1",
        "policies": POLICIES,
        "probabilities": [1 / len(POLICIES)] * len(POLICIES),
    }
    samples = {
        part: dataset(
            stream_seed(seed, part),
            256,
            "uniform" if part in {"holdout", "retention"} else "gaussian",
        )
        for part in ("training", "development", "acceptance", "holdout", "retention")
    }
    groups = {
        part: [f"synthetic-generator-v1:{data_pin(data)}"]
        for part, data in samples.items()
    }
    groups["training"].append(
        f"synthetic-generator-v1:{child['discovery_training_data']}"
    )
    groups["development"].append(
        f"synthetic-generator-v1:{child['discovery_development_data']}"
    )
    with meter(historical, "preparation"):
        s0 = train(np.zeros(9), samples["training"], (1.0, 0.12), seed, steps=120)
        s1 = train(s0, samples["training"], (0.5, 0.03), seed + 1, steps=16)
    starts = [s0, s1]
    plan = {
        "schema": "ndu.causal.improver-comparison.v1",
        "improvers": {
            "parent": {"artifact_digest": _sha(parent), "parent_digest": None},
            "child": {"artifact_digest": _sha(child), "parent_digest": _sha(parent)},
        },
        "runs": [],
        "cost_penalty": {"unit": "cpu_seconds", "per_unit": 0.0},
    }
    registry = {
        "schema": "ndu.causal.improver-attempt-registry.v1",
        "sealed": False,
        "entries": [],
        "run_overheads": {},
        "finals": {},
    }
    results = []
    prepared_artifacts = {
        "parent": parent,
        "child": child,
        "S0": s0.tolist(),
        "S1": s1.tolist(),
        "S1_origin": "fixed_preparation_update_not_evolved_solver",
        "source_groups": groups,
        "historical_cost_ledger": historical,
    }

    def checkpoint():
        save_json(
            out / f"{lineage}-journal.json",
            {
                "plan": plan,
                "registry": registry,
                "attempts": results,
                "evaluation_records": {
                    key: value
                    for key, value in records.items()
                    if value["run_id"].startswith(lineage + ":")
                },
                "prepared_artifacts": prepared_artifacts,
            },
        )

    checkpoint()
    for row, start in enumerate(starts):
        for role, improver in (("parent", parent), ("child", child)):
            run_wall, run_cpu = time.perf_counter(), time.process_time()
            run_id = f"{lineage}:S{row}:{role}"
            run = {
                "run_id": run_id,
                "pair_id": f"{lineage}:S{row}",
                "role": role,
                "improver_digest": _sha(improver),
                "producer_owner": "pilot-producer",
                "evaluator_owner": "pilot-local-evaluator",
                "common_start": {
                    "initial_bundle": bind(start),
                    "seed": seed,
                    "source_cluster": lineage,
                    "training_data": data_pin(samples["training"]),
                    "development_data": data_pin(samples["development"]),
                    "acceptance_data": data_pin(samples["acceptance"]),
                    "holdout_data": data_pin(samples["holdout"]),
                    "training_families": ["gaussian-linear-classification"],
                    "holdout_family": "uniform-linear-classification",
                },
                "full_budget_contract": {
                    "scope": list(COST_STAGES),
                    "limits": {"wall_seconds": 30.0, "cpu_seconds": 15.0},
                    "candidate_attempts": attempts_per_arm,
                },
                "acceptance_profile": _sha(
                    {"selection": "new accuracy with old loss <= 0.15"}
                ),
                "holdout_profile": _sha(
                    {"final": "uniform new accuracy and separate old retention"}
                ),
            }
            plan["runs"].append(run)
            overhead = ledger()
            registry["run_overheads"][run_id] = overhead
            with meter(overhead, "search"):
                proposal_ids = np.random.default_rng(seed + 500).choice(
                    len(POLICIES), size=attempts_per_arm, p=improver["probabilities"]
                )
            chosen, chosen_weights, best = (
                None,
                start.copy(),
                accuracy(start, samples["acceptance"]),
            )
            for number, policy_index in enumerate(proposal_ids):
                if (
                    time.perf_counter() - run_wall >= 29
                    or time.process_time() - run_cpu >= 14
                ):
                    raw_results.append(
                        {
                            "run_id": run_id,
                            "dispatch_stopped": "cooperative_budget_limit",
                            "unused_candidate_opportunities": attempts_per_arm - number,
                        }
                    )
                    break
                attempt_id = f"{run_id}:attempt-{number}"
                policy = POLICIES[policy_index]
                request = {
                    "run": run_id,
                    "bundle": bind(start),
                    "improver": _sha(improver),
                    "policy": policy,
                    "seed": seed + number,
                    "steps": 64,
                }
                entry = {
                    "attempt_id": attempt_id,
                    "run_id": run_id,
                    "operation_id": attempt_id,
                    "request_sha256": _sha(request),
                    "retry_of": None,
                    "original_attempt_reference": f"pilot:{attempt_id}",
                }
                registry["entries"].append(entry)
                costs = ledger()
                record = {
                    **{
                        key: entry[key]
                        for key in (
                            "attempt_id",
                            "run_id",
                            "operation_id",
                            "request_sha256",
                        )
                    },
                    "terminal_status": "UNKNOWN",
                    "candidate_digest": None,
                    "validity": "UNKNOWN",
                    "evaluation_reference": None,
                    "rolled_back": False,
                    "rollback_reference": None,
                    "costs": costs,
                }
                results.append(record)
                with meter(costs, "io"):
                    checkpoint()
                try:
                    with meter(costs, "training"):
                        candidate = train(
                            start, samples["training"], policy, seed + number
                        )
                    with meter(costs, "evaluation"):
                        value = accuracy(candidate, samples["acceptance"])
                        loss = accuracy(start, samples["acceptance"], True) - accuracy(
                            candidate, samples["acceptance"], True
                        )
                        accepted = (
                            value > accuracy(start, samples["acceptance"])
                            and loss <= 0.15
                        )
                        evaluation = {
                            "kind": "acceptance",
                            "run_id": run_id,
                            "actor_id": run["evaluator_owner"],
                            "candidate_bundle": bind(candidate),
                            "baseline_bundle": bind(start),
                            "evaluation_profile": run["acceptance_profile"],
                            "data_digest": run["common_start"]["acceptance_data"],
                            "evidence_digest": _sha(
                                {
                                    "candidate": candidate.tolist(),
                                    "score": value,
                                    "loss": loss,
                                }
                            ),
                            "observed_unix_seconds": int(time.time()),
                            "baseline_utility": accuracy(start, samples["acceptance"]),
                            "candidate_utility": value,
                            "attempt_id": attempt_id,
                            "operation_id": attempt_id,
                            "accepted": accepted,
                        }
                        reference = _sha(evaluation)
                        records[reference] = evaluation
                    record.update(
                        terminal_status="SUCCEEDED",
                        candidate_digest=bind(candidate),
                        validity="VALID",
                        evaluation_reference=reference,
                    )
                    if accepted and value > best:
                        chosen, chosen_weights, best = (
                            attempt_id,
                            candidate.copy(),
                            value,
                        )
                except (ValueError, FloatingPointError) as error:
                    record.update(terminal_status="FAILED", validity="INVALID")
                    raw_results.append(
                        {
                            "attempt_id": attempt_id,
                            "failed": type(error).__name__,
                            "reason": str(error),
                        }
                    )
                if _sha(improver) != run["improver_digest"]:
                    raise ValueError("IMPROVER_MUTATED_DURING_TEST")
                with meter(costs, "io"):
                    checkpoint()
            with meter(overhead, "io"):
                selection = {
                    "run_id": run_id,
                    "attempt_id": chosen,
                    "candidate_bundle": bind(chosen_weights),
                    "weights": chosen_weights.tolist(),
                    "improver_digest": _sha(improver),
                    "committed_unix_seconds": int(time.time()),
                }
                selection_digest = _sha(selection)
                save_json(out / f"{lineage}-S{row}-{role}-selection.json", selection)
                checkpoint()
            with meter(overhead, "evaluation"):
                # The inherited receipt contract uses whole seconds and strict ordering.
                while int(time.time()) <= selection["committed_unix_seconds"]:
                    time.sleep(0.02)
                final = {
                    "kind": "heldout_final",
                    "run_id": run_id,
                    "actor_id": run["evaluator_owner"],
                    "candidate_bundle": bind(chosen_weights),
                    "baseline_bundle": bind(start),
                    "evaluation_profile": run["holdout_profile"],
                    "data_digest": run["common_start"]["holdout_data"],
                    "evidence_digest": _sha(
                        {
                            "selection": selection,
                            "heldout": data_pin(samples["holdout"]),
                        }
                    ),
                    "observed_unix_seconds": int(time.time()),
                    "baseline_utility": accuracy(start, samples["holdout"]),
                    "candidate_utility": accuracy(chosen_weights, samples["holdout"]),
                    "selection_digest": selection_digest,
                    "selection_committed_unix_seconds": selection[
                        "committed_unix_seconds"
                    ],
                    "task_family": run["common_start"]["holdout_family"],
                    "retention_baseline": accuracy(start, samples["retention"], True),
                    "retention_candidate": accuracy(
                        chosen_weights, samples["retention"], True
                    ),
                    "retention_data_digest": data_pin(samples["retention"]),
                }
                final_reference = _sha(final)
                records[final_reference] = final
            registry["finals"][run_id] = {
                "attempt_id": chosen,
                "candidate_bundle": bind(chosen_weights),
                "selection_digest": selection_digest,
                "evaluation_reference": final_reference,
            }
            run_ledgers = [overhead] + [
                result["costs"] for result in results if result["run_id"] == run_id
            ]
            accounted = {
                unit: sum(
                    cell["values"].get(unit, 0)
                    for costs in run_ledgers
                    for cell in costs.values()
                )
                for unit in ("wall_seconds", "cpu_seconds")
            }
            overhead["preparation"] = {
                "status": "measured",
                "values": {
                    "wall_seconds": max(
                        0, time.perf_counter() - run_wall - accounted["wall_seconds"]
                    ),
                    "cpu_seconds": max(
                        0, time.process_time() - run_cpu - accounted["cpu_seconds"]
                    ),
                    "energy_joules": None,
                    "provider_charges": None,
                },
                "evidence": "run envelope residual: hashing, scoring, bookkeeping and unallocated CPU work",
            }
            checkpoint()
            raw_results.append(
                {
                    "run_id": run_id,
                    "decision": "selected_for_research" if chosen else "NoUpdate",
                    "gain": final["candidate_utility"] - final["baseline_utility"],
                    "retention_loss": max(
                        0, final["retention_baseline"] - final["retention_candidate"]
                    ),
                    "native_adoption": "not_submitted",
                    "native_next_use": "unobserved",
                }
            )
    registry["sealed"] = True
    checkpoint()
    historical_totals = {
        unit: sum(
            cell["values"][unit]
            for cell in historical.values()
            if cell["status"] == "measured"
        )
        if unit in ("wall_seconds", "cpu_seconds")
        else None
        for unit in COST_UNITS
    }
    save_json(out / f"{lineage}-improvers.json", prepared_artifacts)
    return {
        "lineage_id": lineage,
        "plan": plan,
        "registry": registry,
        "attempts": results,
        "solver_rows": {bind(s0): "S0", bind(s1): "S1"},
        "historical_costs": historical_totals,
        "source_groups": groups,
        "retention_data_digest": data_pin(samples["retention"]),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--seeds", type=int, nargs="+", default=[104729, 130363, 155921]
    )
    parser.add_argument("--attempts", type=int, default=6)
    args = parser.parse_args()
    if (
        not 1 <= len(args.seeds) <= 16
        or len(set(args.seeds)) != len(args.seeds)
        or not 1 <= args.attempts <= 32
        or any(seed < 0 or seed > 2**31 for seed in args.seeds)
    ):
        parser.error("use 1..16 unique nonnegative seeds and 1..32 attempts")
    args.output.mkdir(parents=True, exist_ok=False)
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    preregistration = {
        "schema": "evolve1.synthetic-pilot.v1",
        "seeds": args.seeds,
        "registered_run_ids": [
            f"lineage-{seed}:S{row}:{role}"
            for seed in args.seeds
            for row in (0, 1)
            for role in ("parent", "child")
        ],
        "attempts_per_arm": args.attempts,
        "minimum_gain": 0.05,
        "maximum_retention_loss": 0.15,
        "policies": POLICIES,
        "learner": "numpy-linear-sgd-reference-not-HeptaCore",
        "solver_descendant_origin": "fixed_preparation_update",
        "input_family": "generated-gaussian",
        "holdout_family": "generated-uniform",
        "independent_owner": False,
        "budget_enforcement": "cooperative_between_bounded_candidates_not_process_hard_quota",
        "python": platform.python_version(),
        "numpy": np.__version__,
        "source_sha256": {
            name: hashlib.sha256(
                Path(__file__).with_name(name).read_bytes()
            ).hexdigest()
            for name in (
                "evolve1_pilot.py",
                "evolve1_reference.py",
                "evolve1.py",
                "causal_improver.py",
                "_causal_checks.py",
                "__init__.py",
            )
        },
    }
    save_json(args.output / "preregistration.json", preregistration)
    records, raw_results = {}, []
    blocks = [
        run_block(seed, args.attempts, args.output, records, raw_results)
        for seed in args.seeds
    ]
    # Byte binding here is deliberately only a local fixture verifier.
    try:
        report = summarize_transfer(
            blocks,
            minimum_gain=0.05,
            maximum_retention_loss=0.15,
            read_evaluation=lambda kind, ref: records.get(ref),
            verify_evaluation=lambda kind, record, owner: (
                records.get(_sha(record)) == record and record.get("actor_id") == owner
            ),
        )
    except ValueError as error:
        report = {
            "status": "HOLD_PROTOCOL_REJECTED",
            "error": str(error),
            "authority_granted": False,
        }
    campaign = {
        "schema": "evolve1.synthetic-pilot-result.v1",
        "preregistration": preregistration,
        "blocks": blocks,
        "evaluation_records": records,
        "raw_results": raw_results,
        "report": report,
        "measured_driver_wall_seconds": time.perf_counter() - start_wall,
        "measured_driver_cpu_seconds": time.process_time() - start_cpu,
        "scope": "controlled_synthetic_pilot_only",
        "scientific_efficacy_qualified": False,
        "production_adoption_qualified": False,
        "unknowns": [
            "energy",
            "provider_charges",
            "independent_evaluator_attestation",
            "native_successor_consumption",
            "real_task_transfer",
            "end_to_end_meter_provenance",
        ],
    }
    campaign["unallocated_driver_work"] = (
        "driver envelope additionally includes generation, startup/setup after imports, final accounting and checkpoint overhead; process imports and final result serialization require external metering"
    )
    save_json(args.output / "campaign.json", campaign)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "registered_runs": 4 * len(blocks),
                "registered_attempts": sum(
                    len(block["registry"]["entries"]) for block in blocks
                ),
                "raw_results": raw_results,
                "scientific_efficacy_qualified": False,
                "production_adoption_qualified": False,
            },
            sort_keys=True,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
