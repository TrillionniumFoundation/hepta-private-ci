"""Executed finite CI-memory comparison. Historical cases are development only."""

import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np
import torch

try:
    import resource
except ImportError:  # Windows has no resource module.
    resource = None

from domain_baselines import RetrievalBaselines, dense_nearest
from domain_data import (
    source_groups,
    FINAL_TEMPLATE,
    SELECT_TEMPLATE,
    TRAIN_TEMPLATES,
    canonical,
    load_dataset,
    probes,
    sha,
    write_json,
)
from domain_training import encode, read, train
from exact_baselines import measure_baselines
from learned_router import fit_router, load_router
from population_protocol import source_identity
from pretrained import file_inventory
from router_features import checked_config


def identity():
    result = source_identity()
    result["domain_sources"] = {
        p.name: sha(p.read_bytes()) for p in sorted(Path(__file__).parent.glob("*.py"))
    }
    return result


def run(dataset, expected_sha256, model, output, seed=19031, visits=8):
    if not 4 <= visits <= 64 or visits % len(TRAIN_TEMPLATES):
        raise ValueError("visits must be a bounded multiple of all four templates")
    data = load_dataset(dataset, expected_sha256)
    known = [c for c in data["cases"] if c["id"] in data["partitions"]["train"]]
    if not 2 <= len(known) <= 64 or len(source_groups(known)) < 2:
        raise ValueError(
            "two independent train groups required; no copied pseudo-cases"
        )
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    before = identity()
    protocol = dict(
        schema="hepta.domain.trial.v1",
        mode="finite_development",
        seed=seed,
        visits=visits,
        learning_rate=0.001,
        dataset_sha256=expected_sha256,
        dataset_path=str(Path(dataset).resolve()),
        candidate_ranks={
            "single": [4],
            "expanded": [8],
            "split": [4, 4],
            "random_split": [4, 4],
        },
        train_ids=[c["id"] for c in known],
        partitions=data["partitions"],
        router_config=checked_config({"seed": seed}),
        source_identity=before,
        templates=TRAIN_TEMPLATES,
        selection_template=SELECT_TEMPLATE,
        final_template=FINAL_TEMPLATE,
        selection_rule="highest source-only supported accuracy, then measured deployment artifact bytes, then name; retrieval is eligible",
        unknowns="synthetic unrecorded-checksum requests crossed with every positive template",
        heldout_model_or_threshold_selection=False,
        production_accepted=False,
    )
    write_json(output / "protocol.json", protocol)
    torch.set_num_threads(2)
    scope, allowed = data["scope"], {c["source_digest"] for c in known}
    training = train(model, known, scope, output / "training", seed, visits)
    versions = training["versions"]
    source_probes = probes(known, TRAIN_TEMPLATES) + probes(
        known, TRAIN_TEMPLATES, unknown=True
    )
    select = probes(known, [SELECT_TEMPLATE]) + probes(
        known, [SELECT_TEMPLATE], unknown=True
    )
    routers, source_rows, source_choices, router_costs, journal = {}, {}, {}, {}, []
    work = dict(
        source_model_reads=0,
        selected_dispatch_reads=0,
        diagnostic_model_reads=0,
        input_tokens=0,
        generated_tokens=0,
        model_generation_seconds=0.0,
    )

    def execute(version, questions, category):
        call_start = time.perf_counter()
        rows = read(model, version, scope, allowed, questions)
        journal.append(
            dict(
                category=category,
                version=version,
                rows=rows,
                wall_seconds=time.perf_counter() - call_start,
                checkpoint_reload_executed=bool(questions),
            )
        )
        work[category] += len(rows)
        for row in rows:
            work["input_tokens"] += row["input_tokens"]
            work["generated_tokens"] += row["generated_tokens"]
            work["model_generation_seconds"] += row["seconds"]
        return rows

    for arm, vs in versions.items():
        requested = source_probes + select if len(vs) == 2 else select
        rows = [
            execute(v, [p["question"] for p in requested], "source_model_reads")
            for v in vs
        ]
        source_rows[arm] = rows
        if len(vs) == 2:
            observations = [
                dict(
                    question=p["question"],
                    reject=p["synthetic_unknown"],
                    utilities=[
                        float(p["root"] in v["roots"] and r[i]["text"] == p["answer"])
                        for v, r in zip(vs, rows)
                    ],
                )
                for i, p in enumerate(source_probes)
            ]
            router_start = time.perf_counter()
            router = fit_router(
                observations,
                expert_ids=[arm + "-0", arm + "-1"],
                source_sha256=sha(canonical([expected_sha256, observations])),
                config=protocol["router_config"],
            )
            receipt = router.save(output / (arm + ".router.bin"))
            write_json(
                output / (arm + ".router.json"),
                dict(observations=observations, receipt=receipt),
            )
            routers[arm] = load_router(
                receipt["path"], expected_sha256=receipt["sha256"]
            )
            router_costs[arm] = dict(
                receipt=receipt,
                fit_save_load_seconds=time.perf_counter() - router_start,
            )
            slots = [
                routers[arm].predict({"question": p["question"]})["slot"]
                for p in select
            ]
            offset = len(source_probes)
        else:
            slots, offset = [0] * len(select), 0
        outcomes = []
        for i, (p, slot) in enumerate(zip(select, slots)):
            answer = rows[slot][offset + i]["text"] if slot is not None else "unknown"
            supported = slot is not None and p["root"] in vs[slot]["roots"]
            outcomes.append(
                answer == p["answer"] and (supported or p["synthetic_unknown"])
            )
        source_choices[arm] = dict(
            correct=sum(outcomes), denominator=len(outcomes), outcomes=outcomes
        )
    retrieval_start = time.perf_counter()
    baseline = RetrievalBaselines(known, output / "retrieval.sqlite3")
    write_json(
        output / "tfidf-index.json",
        dict(
            idf=baseline.idf,
            vectors=baseline.vectors,
            labels=[c["repair_id"] for c in known],
        ),
    )
    source_retrieved = [baseline.predict(p["question"]) for p in select]
    retrieval_seconds = time.perf_counter() - retrieval_start
    source_predictions = {
        arm: [r[arm] for r in source_retrieved] for arm in source_retrieved[0]
    }
    dense_source = probes(known, [TRAIN_TEMPLATES[0]])
    source_features, source_feature_cost = encode(
        model,
        versions["parent"][0],
        scope,
        allowed,
        [p["question"] for p in dense_source + select],
    )
    np.savez(output / "source-features.npz", features=source_features)
    np.savez(
        output / "dense-source-index.npz",
        features=source_features[: len(known)],
        labels=np.array([p["answer"] for p in dense_source]),
    )
    source_predictions.update(
        dense_nearest(
            source_features[: len(known)],
            source_features[len(known) :],
            [p["answer"] for p in dense_source],
        )
    )
    for arm, values in source_predictions.items():
        outcomes = [answer == p["answer"] for answer, p in zip(values, select)]
        source_choices[arm] = dict(
            correct=sum(outcomes), denominator=len(outcomes), outcomes=outcomes
        )
    base_bytes = sum(v["bytes"] for v in file_inventory(Path(model)).values())
    manifest_bytes = (Path(dataset).parent / "input-manifest.json").stat().st_size
    common_bytes = data["source_bytes"] + Path(dataset).stat().st_size + manifest_bytes
    deployment_bytes = {
        arm: common_bytes
        + base_bytes
        + training["costs"][arm]["checkpoint_bytes"]
        + training["costs"]["parent"]["checkpoint_bytes"]
        + (router_costs[arm]["receipt"]["artifact_bytes"] if arm in router_costs else 0)
        for arm in versions
        if arm != "parent"
    }
    deployment_bytes["expanded"] += sum(
        p.stat().st_size
        for p in (output / "training" / "expanded-parent").rglob("*")
        if p.is_file()
    )
    deployment_bytes.update(
        exact_source=common_bytes,
        bm25=common_bytes + (output / "retrieval.sqlite3").stat().st_size,
        tfidf=common_bytes + (output / "tfidf-index.json").stat().st_size,
    )
    for arm in ("dense_nearest", "dense_centroid"):
        deployment_bytes[arm] = (
            common_bytes
            + base_bytes
            + training["costs"]["parent"]["checkpoint_bytes"]
            + (output / "dense-source-index.npz").stat().st_size
        )
    chosen = min(
        deployment_bytes,
        key=lambda a: (-source_choices[a]["correct"], deployment_bytes[a], a),
    )
    write_json(output / "source-reads.json", source_rows)
    selection = dict(
        chosen=chosen,
        scores=source_choices,
        deployment_artifact_bytes=deployment_bytes,
        source_retrieval_predictions=source_predictions,
        protocol_sha256=sha(canonical(protocol)),
        byte_exclusions="runtime/OS/activation RAM; byte comparison is storage, not equal system cost",
        final_outputs_seen=False,
    )
    write_json(output / "selection.json", selection)
    selection_pin = sha((output / "selection.json").read_bytes())
    final, panels = [], {}
    for name in ("train", "validation", "future"):
        cases = [c for c in data["cases"] if c["id"] in data["partitions"][name]]
        panel = probes(cases, [FINAL_TEMPLATE])
        panels["known_recall" if name == "train" else name] = list(
            range(len(final), len(final) + len(panel))
        )
        final.extend(panel)
    unknown = probes(known, [FINAL_TEMPLATE], unknown=True)
    panels["synthetic_unknown"] = list(range(len(final), len(final) + len(unknown)))
    final.extend(unknown)
    questions = [p["question"] for p in final]
    routes = {
        arm: [router.predict({"question": q}) for q in questions]
        for arm, router in routers.items()
    }
    write_json(output / "frozen-routes.json", routes)
    predictions, diagnostics = {}, {}
    for arm, vs in versions.items():
        if len(vs) == 1:
            predictions[arm] = [
                r["text"] for r in execute(vs[0], questions, "selected_dispatch_reads")
            ]
        else:
            dispatched = ["unknown"] * len(final)
            for slot, version in enumerate(vs):
                indices = [i for i, r in enumerate(routes[arm]) if r["slot"] == slot]
                raw = execute(
                    version, [questions[i] for i in indices], "selected_dispatch_reads"
                )
                for i, row in zip(indices, raw):
                    dispatched[i] = row["text"]
            predictions[arm] = dispatched
            # This separate full-expert cost buys oracle/random diagnostics. It
            # is never passed to the already frozen dispatch policy.
            raw = [execute(v, questions, "diagnostic_model_reads") for v in vs]
            diagnostics[arm] = raw
            for i, route in enumerate(routes[arm]):
                if (
                    route["slot"] is not None
                    and raw[route["slot"]][i]["text"] != dispatched[i]
                ):
                    raise ValueError(
                        "immutable checkpoint dispatch/diagnostic mismatch"
                    )
    retrieval_start = time.perf_counter()
    retrieved = [baseline.predict(q) for q in questions]
    baseline.close()
    retrieval_seconds += time.perf_counter() - retrieval_start
    predictions.update({arm: [r[arm] for r in retrieved] for arm in retrieved[0]})
    features, feature_cost = encode(
        model, versions["parent"][0], scope, allowed, questions
    )
    np.savez(output / "frozen-features.npz", features=features)
    predictions.update(
        dense_nearest(
            source_features[: len(known)], features, [p["answer"] for p in dense_source]
        )
    )
    scores = {
        arm: {
            panel: dict(
                correct=sum(values[i] == final[i]["answer"] for i in ids),
                denominator=len(ids),
                accuracy=(
                    sum(values[i] == final[i]["answer"] for i in ids) / len(ids)
                    if ids
                    else None
                ),
            )
            for panel, ids in panels.items()
        }
        for arm, values in predictions.items()
    }
    for arm, vs in versions.items():
        for panel, ids in panels.items():
            if panel != "known_recall":
                # A novel task's source root cannot be a prior training root.
                # Future policy transfer requires its own execution outcome,
                # not exact-fact ancestry admission against that future root.
                scores[arm][panel].update(
                    source_admitted_correct=None, source_admitted_accuracy=None
                )
                continue
            admitted = 0
            for i in ids:
                slot = routes[arm][i]["slot"] if arm in routes else 0
                support = final[i]["synthetic_unknown"] or (
                    slot is not None and final[i]["root"] in vs[slot]["roots"]
                )
                admitted += bool(support and predictions[arm][i] == final[i]["answer"])
            scores[arm][panel].update(
                source_admitted_correct=admitted,
                source_admitted_accuracy=admitted / len(ids) if ids else None,
            )
    diagnostic_scores = {}
    for arm, raw in diagnostics.items():
        eligible = [
            [
                p["root"] in version["roots"] and rows[i]["text"] == p["answer"]
                for version, rows in zip(versions[arm], raw)
            ]
            for i, p in enumerate(final)
        ]
        ids = panels["known_recall"]
        diagnostic_scores[arm] = dict(
            eligible_oracle=sum(any(eligible[i]) for i in ids) / len(ids),
            expected_uniform=sum(sum(eligible[i]) / 2 for i in ids) / len(ids),
        )
    write_json(
        output / "final-reads.json",
        dict(
            probes=final, predictions=predictions, full_expert_diagnostics=diagnostics
        ),
    )
    write_json(output / "executed-reads.json", journal)
    exact = measure_baselines(known, output / "exact-baselines")
    after = identity()
    if before != after or selection_pin != sha(
        (output / "selection.json").read_bytes()
    ):
        raise ValueError("source or frozen selection changed")
    load_dataset(dataset, expected_sha256)
    costs = dict(
        training=training["costs"],
        decoder_optimizer_updates=training["actual_optimizer_updates"],
        router_optimizer_updates=sum(
            c["receipt"]["training"]["optimizer_updates"] for c in router_costs.values()
        ),
        gradient_probe=training["gradient_probe"],
        work=work,
        frozen_encoder=dict(source=source_feature_cost, final=feature_cost),
        routers=router_costs,
        retrieval_fit_and_query_seconds=retrieval_seconds,
        retrieval_index_bytes=(output / "retrieval.sqlite3").stat().st_size
        + (output / "tfidf-index.json").stat().st_size,
        dense_source_index_bytes=(output / "dense-source-index.npz").stat().st_size,
        shared_base_bytes=base_bytes,
        deployment_artifact_bytes=deployment_bytes,
        original_source_bytes=data["source_bytes"],
        dataset_bytes=Path(dataset).stat().st_size,
        original_manifest_bytes=manifest_bytes,
        retained_experiment_bytes_before_result=sum(
            p.stat().st_size for p in output.rglob("*") if p.is_file()
        ),
        domain_source_code_bytes=sum(
            p.stat().st_size for p in Path(__file__).parent.glob("*.py")
        ),
        memory_dependency_source_code_bytes=sum(
            (Path(__file__).resolve().parents[1] / p).stat().st_size
            for p in before["files_sha256"]
        ),
        process_peak_rss_bytes=(
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            * (1 if sys.platform == "darwin" else 1024)
        )
        if resource
        else None,
        wall_seconds=time.perf_counter() - started,
        cpu_seconds=time.process_time() - cpu,
        equal_total_system_cost=False,
        includes_all_executed_diagnostic_reads=True,
        runtime_and_os_bytes_included=False,
        net_compression_established=False,
        measurement_scope="in-process trial after dataset validation; import/cold-start time and energy not measured",
    )
    result = dict(
        schema="hepta.domain.result.v1",
        mode="finite_development",
        chosen=chosen,
        scores=scores,
        diagnostics=diagnostic_scores,
        costs=costs,
        exact_baselines=exact,
        independent_source_groups=data["independent_groups"],
        panels=panels,
        missing_validation=not panels["validation"],
        missing_future=not panels["future"],
        primary_scores="raw exact text; ancestry admission applies only to known exact-fact recall",
        future_policy_execution_evaluated=False,
        router_positive_and_negative_wording_fully_crossed=True,
        split_and_random_partition_identical=training["partitions"]["split"]["slots"]
        == training["partitions"]["random_split"]["slots"],
        prospective_generalization_established=False,
        capacity_advantage_established=False,
        source_integrity_verified=True,
        production_accepted=False,
    )
    write_json(output / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("dataset", "dataset-sha256", "model", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--seed", type=int, default=19031)
    parser.add_argument("--visits", type=int, default=8)
    args = parser.parse_args()
    result = run(
        args.dataset,
        args.dataset_sha256,
        args.model,
        args.output,
        args.seed,
        args.visits,
    )
    print(
        json.dumps(
            {key: result[key] for key in ("chosen", "scores", "costs")}, indent=2
        )
    )
