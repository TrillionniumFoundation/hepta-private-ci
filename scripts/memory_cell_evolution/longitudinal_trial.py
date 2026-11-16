"""Execute the frozen longitudinal stream; quality never changes later events."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
import resource
import time

from evolution_common import digest, read_json, require, retain
from longitudinal_campaign import load_stream
from longitudinal_runtime import (
    apply_events,
    background_job,
    costs,
    deny_dirty_reads,
    imports,
    pin_start,
    read_panel,
    source_identity,
    train,
    wait_candidate,
)
from longitudinal_scoring import quality_gates, questions, score_round
from topology_owner import ActualOwners
from topology_store import TopologyStore


def run(args):
    protocol = load_stream(args.campaign, args.campaign_sha256, args.seed)
    output, repo, model = (
        args.output.absolute(),
        args.repo.resolve(),
        args.model.resolve(),
    )
    require(not output.exists(), "new immutable experiment output required")
    output.mkdir(parents=True)
    started, cpu = time.monotonic(), time.process_time()
    child_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    identity = pin_start(repo, model, output, protocol, args.campaign_sha256)
    require(
        digest(identity) == args.source_sha256,
        "launch source pin differs from prepared code",
    )
    MemoryService, run_child, run_decoder = imports(repo)
    service = MemoryService(
        output / "source-owner",
        protocol["scope"],
        protocol["cell_id"],
        protocol["role"],
    )

    def provider():
        current = service.snapshot()
        return {k: current[k] for k in ("scope", "epoch", "roots", "revoked")}

    topology = TopologyStore(
        output / "topology", protocol["scope"], provider, ActualOwners(repo / "scripts")
    )
    scores, controls, round_receipts, entities = [], {}, [], set()
    previous = None
    try:
        for index, item in enumerate(protocol["rounds"]):
            require(
                time.monotonic() - started
                < protocol["runtime_limits"]["whole_trial_seconds"],
                "whole trial wall deadline exhausted",
            )
            directory = output / f"round-{index}-{item['label']}"
            directory.mkdir()
            phase_started = time.monotonic_ns()
            events = list(item["before_background"]) + list(item["events"])
            entities.update(e["entity"] for e in events)
            before_records = apply_events(service, item["before_background"])
            retain(directory / "before-background-events.json", before_records)
            background = None
            if item["background_steps"]:
                job = background_job(before_records)
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(
                        train,
                        service,
                        model,
                        output,
                        f"round-{index}-background",
                        item["background_steps"],
                        protocol,
                        repo,
                        run_child,
                    )
                    observed = wait_candidate(service, job, future)
                    retain(
                        directory / "background-construction-observed.json", observed
                    )
                    records = apply_events(service, item["events"])
                    retain(directory / "during-background-events.json", records)
                    deny = deny_dirty_reads(service, entities)
                    retain(directory / "dirty-admission.json", deny)
                    background = future.result()
                require(
                    background["status"] == "superseded",
                    "background candidate unexpectedly published",
                )
                source_path = (
                    Path(observed["candidate_directory"]) / "checkpoint/lineage.json"
                )
                saved = read_json(source_path)["training"]
                require(
                    saved["steps"] == item["background_steps"],
                    "background work was skipped, not an actual training attempt",
                )
                retain(
                    directory / "superseded-training.json",
                    dict(result=background, actual_training=saved),
                )
            else:
                records = apply_events(service, item["events"])
                retain(directory / "events.json", records)
                deny = deny_dirty_reads(service, entities)
                retain(directory / "dirty-admission.json", deny)
            frozen = service.snapshot()
            require(
                len(frozen["facts"]) == protocol["expected_live_fact_counts"][index],
                "registered source-state count differs",
            )
            retain(directory / "source-snapshot.json", frozen)
            published = train(
                service,
                model,
                output,
                f"round-{index}-clean",
                protocol["clean_steps"],
                protocol,
                repo,
                run_child,
            )
            require(
                published["status"] == "published"
                and published["training"]["steps"] == protocol["clean_steps"],
                "clean publication did not complete",
            )
            require(
                published["training"]["templates_sha256"]
                == digest(protocol["train_templates"]),
                "trainer template contract changed",
            )
            binding = service.parameter_binding()
            require(
                binding is not None
                and binding["epoch"] == frozen["epoch"]
                and binding["active"].manifest_sha256 == published["manifest_sha256"],
                "source/parameter binding mismatch",
            )
            active = binding["active"]
            require(
                not set(active.roots) & set(frozen["revoked"]),
                "clean replay contains a withdrawn ancestor",
            )
            candidate = dict(
                cell_id=protocol["cell_id"],
                role=protocol["role"],
                directory=active.directory,
                manifest_sha256=active.manifest_sha256,
                support_roots=[f["source_digest"] for f in frozen["facts"]],
                derivation="clean_replay",
            )
            generation = topology.snapshot()["generation"]
            prepared = topology.prepare(
                f"publication-{index}",
                "bootstrap" if index == 0 else "refresh",
                expected_generation=generation,
                inputs=[] if index == 0 else [protocol["cell_id"]],
                candidates=[candidate],
            )
            committed = topology.commit(f"publication-{index}")
            retain(
                directory / "topology-publication.json",
                dict(
                    prepared=prepared, committed=committed, source_publication=published
                ),
            )
            query = questions(frozen, protocol["read_templates"])
            journal = read_panel(
                topology,
                protocol["cell_id"],
                frozen,
                query,
                model,
                directory,
                "adapter",
                "adapter",
                protocol,
                run_decoder,
            )
            score = score_round(
                frozen, previous, events, journal, protocol["read_templates"]
            )
            retain(directory / "parameter-score.json", score)
            scores.append(score)
            if index in protocol["control_rounds"]:
                controls[str(index)] = {}
                for control in protocol["controls"]:
                    raw = read_panel(
                        topology,
                        protocol["cell_id"],
                        frozen,
                        query,
                        model,
                        directory,
                        control,
                        control,
                        protocol,
                        run_decoder,
                    )
                    controls[str(index)][control] = score_round(
                        frozen, previous, events, raw, protocol["read_templates"]
                    )
                retain(directory / "controls.json", controls[str(index)])
            record = dict(
                index=index,
                source_epoch=frozen["epoch"],
                topology_generation=committed["generation"],
                parameter_generation=active.generation,
                phase_wall_ns=time.monotonic_ns() - phase_started,
                superseded_background=background is not None,
                dirty_parameter_callbacks=deny["model_callbacks"],
                overlay_accuracy_in_parameter_metrics=False,
            )
            retain(directory / "round-receipt.json", record)
            round_receipts.append(record)
            previous = frozen
        after = source_identity(repo)
        retain(output / "source-identity-after.json", after)
        require(identity == after, "executed sources changed")
        cost = costs(output)
        require(
            cost["saved_optimizer_updates"] == protocol["decoder_optimizer_updates"]
            and cost["counted_raw_rows"] == protocol["expected_parameter_query_rows"],
            "actual model cost count differs from registered execution",
        )
        gates = quality_gates(scores, protocol)
        child_after = resource.getrusage(resource.RUSAGE_CHILDREN)
        result = dict(
            schema="hepta.longitudinal.result.v1",
            seed=args.seed,
            campaign_sha256=args.campaign_sha256,
            completed=True,
            source_integrity_verified=True,
            quality_gates=gates,
            quality_passed=all(gates.values()),
            scores=scores,
            controls=controls,
            rounds=round_receipts,
            costs=cost
            | dict(
                wall_seconds=time.monotonic() - started,
                parent_cpu_seconds=time.process_time() - cpu,
                child_cpu_seconds=child_after.ru_utime
                + child_after.ru_stime
                - child_before.ru_utime
                - child_before.ru_stime,
                parent_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                * 1024,
            ),
            independent_natural_task_groups=0,
            future_generalization_established=False,
            sustained_arrival_rate_qualified=False,
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
                completed_rounds=len(scores),
                saved_rounds=round_receipts,
                observed_cost_lower_bound=costs(output),
                complete_result=False,
                failed_attempt_retained=True,
                production_accepted=False,
            ),
        )
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--campaign-sha256", required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = run(args)
    print(
        f"completed seed={args.seed} quality_passed={result['quality_passed']} updates={result['costs']['saved_optimizer_updates']}"
    )
    raise SystemExit(0 if result["quality_passed"] else 2)
