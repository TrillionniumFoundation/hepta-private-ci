"""Actual fixed-population edge comparisons, with separately retained outcomes."""

import argparse
from pathlib import Path
import resource
import time

from edge_execution import GraphExecutor
from edge_budget import usage
from edge_observations import observe_source
from edge_policy import EdgePolicy, fit_edges
from edge_protocol import protocol as registered_protocol
from edge_runtime import EdgeRuntime
from edge_setup import (
    activate_edges,
    exercise_topology,
    prepare_population,
    withdrawal_rebuild,
)
from edge_sources import capture, identity
from evolution_common import digest, read_json, require, retain


def direct_control(runtime, topology, task, *, exact):
    source = runtime.authority.read(task["entity"], "color")
    require(
        source.status.value == "answered",
        "registered direct-control source unavailable",
    )
    if exact:
        return dict(
            task=task,
            status="answered",
            answer=source.answer,
            origin="source_overlay",
            source_roots=list(source.source_roots),
            actual_callbacks=0,
            production_accepted=False,
        )
    selected = [
        name
        for name, version in topology.snapshot()["cells"].items()
        if set(source.source_roots) <= set(version["support_roots"])
    ]
    require(
        len(selected) == 1,
        "direct capability control needs unique current source ownership",
    )
    prompt = "What is the color for " + task["entity"] + "?"
    raw = topology.invoke(
        selected[0],
        list(source.source_roots),
        lambda active: runtime.reader(active, prompt),
    )
    return dict(
        task=task,
        status="generated",
        answer=raw["text"],
        raw=raw,
        origin="parameters",
        selected_cell=selected[0],
        actual_callbacks=1,
        production_accepted=False,
    )


def allocated_dependencies(trained, shared, marginal, observations):
    required = {
        "no-edges": ["hint"],
        "fixed": ["hint", "color-a"],
        "random": list(trained),
        "learned-next-cell": list(trained),
        "capability": list(trained),
        "direct-parameter": ["color-a", "color-b"],
        "exact-source": [],
    }
    result = {}
    for arm, names in required.items():
        selected = [trained[n]["training"] for n in names]
        result[arm] = dict(
            required_trained_cells=names,
            allocated_decoder_updates=sum(t["steps"] for t in selected),
            allocated_training_tokens=sum(t["input_tokens"] for t in selected),
            allocated_training_seconds=sum(t["seconds"] for t in selected),
            shared_base_required=bool(names),
            source_utility_matrix_required=arm == "learned-next-cell",
            source_utility_cost=shared if arm == "learned-next-cell" else None,
            marginal_leaf_work=marginal[arm],
            marginal_arm_observation=observations[arm],
            accounting_origin="allocation of already measured dependency work, not another physical execution",
            sum_across_arm_views_is_not_experiment_total=True,
            complete_standalone_total_cost=False,
        )
    return result


def observed_interval(clock, before):
    after = usage()
    return dict(
        wall_ns=time.monotonic_ns() - clock,
        **{k: after[k] - before[k] for k in ("cpu_ns", "read_bytes", "write_bytes")},
        includes_leaf_effects=True,
        additive_with_leaf_ledger=False,
        io_scope="Linux rusage block IO; not all logical file reads",
    )


def run(args):
    p = read_json(args.protocol)
    require(
        digest(p) == args.protocol_sha256 and p == registered_protocol(),
        "edge protocol differs from registration",
    )
    output, repo, budget_scripts = (
        args.output.absolute(),
        args.repo.resolve(),
        args.budget_scripts.resolve(),
    )
    require(not output.exists(), "new edge experiment output required")
    output.mkdir(parents=True)
    started, cpu = time.monotonic_ns(), time.process_time_ns()
    child_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    before_source = capture(repo, budget_scripts, output, args.source_sha256)
    retain(output / "protocol.json", p)
    retain(
        output / "start.json",
        dict(
            protocol_sha256=args.protocol_sha256,
            source_sha256=args.source_sha256,
            started_unix_ns=time.time_ns(),
            model_execution_started=False,
        ),
    )
    runtime = EdgeRuntime(repo, output, budget_scripts, p)
    results, marginal, observations_by_arm = {}, {}, {}
    try:
        topology, trained, groups = prepare_population(runtime)
        old_split = exercise_topology(runtime, topology, trained, groups)
        population_pins = {
            name: v["manifest_sha256"]
            for name, v in topology.snapshot()["cells"].items()
        }
        targets = ["color-a", "color-b"]
        source_policy = EdgePolicy("capability", targets, seed=p["seed"])
        activate_edges(topology, source_policy, "source-observation-policy")
        executor = GraphExecutor(topology, runtime.resolver, runtime.reader)
        source_begin = runtime.budget.ledger.snapshot()["executed_used"]
        source_clock, source_usage = time.monotonic_ns(), usage()
        observations = []
        for wording, template in enumerate(p["source_templates"]):
            runtime.entry_template = template
            for case in p["cases"]:
                task = dict(
                    task_id=case["case_id"] + f"-source-{wording}",
                    entity=case["case_id"],
                    entry_cell="hint",
                )
                source_value = runtime.authority.read(case["case_id"], "color").answer
                observations.append(
                    observe_source(
                        executor,
                        task,
                        targets,
                        source_value,
                        output=output / "source-observations" / task["task_id"],
                    )
                )
        require(
            len(observations) == p["source_utility_cases"],
            "source utility panel cardinality",
        )
        fit_request = dict(
            source_sha256=digest(observations),
            targets=targets,
            seed=p["seed"],
            optimizer_updates=p["router_updates"],
        )

        def fit():
            binding = fit_edges(
                observations,
                targets,
                scripts=repo / "scripts",
                output=output / "learned-policy",
                seed=p["seed"],
            )
            return dict(
                binding=binding, policy=read_json(output / "learned-policy/policy.json")
            )

        fitted = runtime.budget.effect(
            "index",
            fit_request,
            fit,
            lambda value: dict(
                router_updates=value["policy"]["training"]["optimizer_updates"]
            ),
            router_updates=p["router_updates"],
        )
        source_end = runtime.budget.ledger.snapshot()["executed_used"]
        source_cost = {k: source_end[k] - source_begin[k] for k in source_begin}
        source_interval = observed_interval(source_clock, source_usage)
        learned = EdgePolicy(
            "learned-next-cell",
            targets,
            learned_directory=output / "learned-policy",
            scripts=repo / "scripts",
        )
        require(
            learned.binding == fitted["binding"], "saved/reloaded edge policy differs"
        )
        retain(
            output / "final-policy-freeze.json",
            dict(
                population=population_pins,
                learned_policy=learned.binding,
                source_observations_sha256=digest(observations),
                final_outcomes_seen=False,
                frozen_monotonic_ns=time.monotonic_ns(),
            ),
        )
        runtime.entry_template = p["final_template"]
        for arm in p["arms"]:
            require(
                time.monotonic_ns() - started < 900_000_000_000,
                "edge whole-event deadline exhausted",
            )
            arm_clock, arm_usage = time.monotonic_ns(), usage()
            policy = (
                learned
                if arm == "learned-next-cell"
                else EdgePolicy(
                    arm
                    if arm in ("no-edges", "fixed", "random", "capability")
                    else "no-edges",
                    targets,
                    seed=p["seed"],
                )
            )
            published = activate_edges(topology, policy, "final-policy-" + arm)
            require(
                {
                    name: v["manifest_sha256"]
                    for name, v in topology.snapshot()["cells"].items()
                }
                == population_pins,
                "final arms use different decoder populations",
            )
            retain(output / "final" / arm / "edge-publication.json", published)
            before = runtime.budget.ledger.snapshot()["executed_used"]
            rows = []
            for case in p["cases"]:
                task = dict(
                    task_id=case["case_id"] + "-final",
                    entity=case["case_id"],
                    entry_cell="hint",
                )
                receipt = output / "final" / arm / (task["task_id"] + ".json")
                if arm in ("direct-parameter", "exact-source"):
                    result = direct_control(
                        runtime, topology, task, exact=arm == "exact-source"
                    )
                    retain(receipt, result)
                else:
                    result = executor.run(task, policy, receipt_path=receipt)
                source_answer = runtime.authority.read(case["case_id"], "color").answer
                correct = (
                    result["answer"] is not None
                    and result["answer"].strip() == source_answer
                )
                rows.append(
                    dict(
                        task_id=task["task_id"],
                        correct=correct,
                        expected=source_answer,
                        actual=result["answer"],
                        origin=result["origin"],
                        status=result["status"],
                        admitted_reader_callbacks=result["actual_callbacks"],
                    )
                )
            after = runtime.budget.ledger.snapshot()["executed_used"]
            marginal[arm] = {k: after[k] - before[k] for k in before}
            observations_by_arm[arm] = observed_interval(arm_clock, arm_usage)
            results[arm] = dict(
                correct=sum(r["correct"] for r in rows),
                total=len(rows),
                cases=rows,
                population_sha256=digest(population_pins),
                actual_live_dispatch=True,
                marginal_leaf_work=marginal[arm],
                measured_arm_interval=observations_by_arm[arm],
                measured_interval_scope="edge publication, all tasks, raw receipt persistence and scoring; terminal score-file write excluded",
            )
            retain(output / "final" / arm / "score.json", results[arm])
        withdrawal = withdrawal_rebuild(runtime, topology, trained, old_split, learned)
        after_source = identity(repo, budget_scripts)
        retain(output / "source-identity-after.json", after_source)
        require(after_source == before_source, "edge executed sources changed")
        inventory = runtime.component_inventory()
        ledger = runtime.budget.report()
        work = ledger["ledger"]["executed_used"]
        require(
            work["decoder_updates"] == p["decoder_optimizer_updates"]
            and work["router_updates"] == p["router_updates"]
            and work["decoder_queries"] <= p["maximum_total_decoder_queries"],
            "measured work exceeds registered event",
        )
        child_after = resource.getrusage(resource.RUSAGE_CHILDREN)
        result = dict(
            schema="hepta.edge-mechanism.result.v1",
            completed=True,
            protocol_sha256=args.protocol_sha256,
            source_integrity_verified=True,
            arms=results,
            source_utility_and_fit_physical_work=source_cost,
            source_utility_and_fit_observed_interval=source_interval,
            dependency_allocations=allocated_dependencies(
                trained, source_cost, marginal, observations_by_arm
            ),
            physical_work=work,
            budget=ledger,
            inventory=inventory,
            withdrawal=withdrawal,
            wall_ns=time.monotonic_ns() - started,
            parent_cpu_ns=time.process_time_ns() - cpu,
            child_cpu_ns=int(
                round(
                    (
                        child_after.ru_utime
                        + child_after.ru_stime
                        - child_before.ru_utime
                        - child_before.ru_stime
                    )
                    * 1e9
                )
            ),
            model_calls_not_reused_from_final_matrix=True,
            natural_task_groups=0,
            prospective=False,
            learned_fission_established=False,
            learned_edge_advantage_qualified=False,
            complete_total_cost_qualified=False,
            production_accepted=False,
        )
        retain(output / "result.json", result)
        return result
    except BaseException as error:
        retain(
            output / "execution-failure.json",
            dict(
                error_type=type(error).__name__,
                error=str(error),
                completed_arms=results,
                budget=runtime.budget.report(),
                incomplete_effects_are_not_zero_work=True,
                complete_result=False,
                production_accepted=False,
            ),
        )
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("repo", "budget-scripts", "protocol", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--protocol-sha256", required=True)
    parser.add_argument("--source-sha256", required=True)
    result = run(parser.parse_args())
    print(
        "completed edge mechanism; actual decoder queries="
        + str(result["physical_work"]["decoder_queries"])
    )
