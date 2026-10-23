"""Source-only fitted routers, nearest-source controls and immutable route plans."""

from collections import Counter
from pathlib import Path
import re
import time

import numpy as np

from diagnosis_common import digest, file_sha, retain
from diagnosis_execution import cpu_delta, cpu_snapshot


def observations(probes, raw, versions, capabilities):
    from population_scoring import probe_eligibility

    if len(raw) != 2 or len(versions) != 2:
        raise ValueError("exactly two fixed experts required")
    questions = [p["question"] for p in probes]
    if any([row["question"] for row in rows] != questions for rows in raw):
        raise ValueError("source questions differ from fresh raw observations")
    result, evidence = [], []
    for index, probe in enumerate(probes):
        eligibility = [
            probe_eligibility(probe, version, capabilities) for version in versions
        ]
        utilities = [
            float(
                rows[index]["text"] == probe["value"] and allowed["capability_allowed"]
            )
            for rows, allowed in zip(raw, eligibility, strict=True)
        ]
        result.append(
            {
                "question": probe["question"],
                "utilities": utilities,
                "reject": probe["reject"],
            }
        )
        evidence.append(
            {
                "probe_id": probe["probe_id"],
                "family": probe["family"],
                "wording": probe["wording"],
                "raw_text": [rows[index]["text"] for rows in raw],
                "eligibility": eligibility,
                "utilities": utilities,
                "explicit_reject": probe["reject"],
            }
        )
    return result, evidence


def prototype_targets(rows, minimum):
    result = []
    for row in rows:
        best = max(row["utilities"])
        result.append(
            None if row["reject"] or best < minimum else row["utilities"].index(best)
        )
    return result


def unit_rows(values):
    values = np.asarray(values, dtype=np.float64)
    if values.ndim != 2 or not np.isfinite(values).all():
        raise ValueError("finite feature matrix required")
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    return np.divide(values, norms, out=np.zeros_like(values), where=norms > 0)


def terms(question):
    tokens = re.findall(r"\w+", " ".join(question.casefold().split()))
    return Counter(
        ["w:" + token for token in tokens]
        + ["b:" + left + "/" + right for left, right in zip(tokens, tokens[1:])]
    )


def lexical_index(questions):
    documents = [terms(question) for question in questions]
    vocabulary = sorted({term for document in documents for term in document})
    frequency = Counter(term for document in documents for term in document)
    idf = np.array(
        [
            np.log((1 + len(documents)) / (1 + frequency[term])) + 1
            for term in vocabulary
        ],
        dtype=np.float64,
    )
    return {"vocabulary": vocabulary, "idf": idf.tolist()}, lexical_encode(
        questions, vocabulary, idf
    )


def lexical_encode(questions, vocabulary, idf):
    slots = {term: index for index, term in enumerate(vocabulary)}
    vectors = np.zeros((len(questions), len(vocabulary)), dtype=np.float64)
    for row, question in enumerate(questions):
        for term, count in terms(question).items():
            if term in slots:
                vectors[row, slots[term]] = count * idf[slots[term]]
    return unit_rows(vectors)


def nearest_routes(source, queries, targets):
    source, queries = unit_rows(source), unit_rows(queries)
    if source.shape[0] != len(targets) or source.shape[1] != queries.shape[1]:
        raise ValueError("source and query feature alignment mismatch")
    routes = []
    for vector in queries:
        if not np.any(vector):
            routes.append(
                {
                    "slot": None,
                    "reason": "no_matching_source_features",
                    "source_index": None,
                }
            )
            continue
        similarities = source @ vector
        nearest = int(np.argmax(similarities))
        slot = targets[nearest]
        routes.append(
            {
                "slot": slot,
                "reason": "nearest_source_reject" if slot is None else "routed",
                "source_index": nearest,
                "cosine": float(similarities[nearest]),
            }
        )
    return routes


def fit_and_freeze(
    original_pin,
    source_rows,
    balanced,
    observations_rows,
    source_provenance,
    parent_vectors,
    final_metadata,
    versions,
    capabilities,
    output,
):
    """No final gold or raw outputs are accepted by this function."""
    from learned_router import fit_router, load_router
    from population_scoring import probe_eligibility

    expected_fields = {"probe_id", "question", "family", "operation", "source_roots"}
    if any(set(probe) != expected_fields for probe in final_metadata):
        raise ValueError("only answer-free final metadata may enter route freezing")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    original = load_router(
        original_pin["original_router_path"],
        expected_sha256=original_pin["original_router_sha256"],
    )
    if (
        original.expert_ids != ("split-0", "split-1")
        or original.config["epochs"] != 400
        or original.config["dimension"] != 512
    ):
        raise ValueError("original router differs from the predeclared protocol")
    routers, receipts = {"original": original}, {}
    for name, indices in (
        ("full_cross", list(range(len(source_rows)))),
        ("balanced", balanced),
    ):
        selected = [observations_rows[i] for i in indices]
        provenance = {
            **source_provenance,
            "source_indices": indices,
            "observations_sha256": digest(selected),
        }
        retain(output / f"{name}-provenance.json", provenance)
        before, started = cpu_snapshot(), time.perf_counter()
        fitted = fit_router(
            selected,
            expert_ids=list(original.expert_ids),
            source_sha256=digest(provenance),
            config=dict(original.config),
        )
        receipt = fitted.save(output / f"{name}-router.bin")
        routers[name] = load_router(receipt["path"], expected_sha256=receipt["sha256"])
        receipt.update(wall_seconds=time.perf_counter() - started, **cpu_delta(before))
        receipts[name] = receipt

    source_questions = [p["question"] for p in source_rows]
    final_questions = [p["question"] for p in final_metadata]
    questions = source_questions + final_questions
    if parent_vectors.shape[0] != len(questions):
        raise ValueError(
            "actual parent features must align to source then final questions"
        )
    targets = prototype_targets(observations_rows, original.config["min_utility"])
    before, started = cpu_snapshot(), time.perf_counter()
    lexicon, lexical_source = lexical_index(source_questions)
    lexical_queries = lexical_encode(
        questions, lexicon["vocabulary"], np.asarray(lexicon["idf"])
    )
    lexical_routes = nearest_routes(lexical_source, lexical_queries, targets)
    prototype = {
        "source_questions": source_questions,
        "targets": targets,
        **lexicon,
        "source_provenance_sha256": digest(source_provenance),
        "answer_values_stored": False,
        "tie_rule": "lowest-source-index; lowest-expert-slot",
    }
    retain(output / "lexical-index.json", prototype)
    np.save(output / "lexical-prototypes.npy", lexical_source, allow_pickle=False)
    receipts["lexical"] = {
        "wall_seconds": time.perf_counter() - started,
        **cpu_delta(before),
    }
    before, started = cpu_snapshot(), time.perf_counter()
    dense_source = unit_rows(parent_vectors[: len(source_rows)])
    dense_routes = nearest_routes(dense_source, parent_vectors, targets)
    np.save(output / "dense-prototypes.npy", dense_source, allow_pickle=False)
    retain(
        output / "dense-index.json",
        {
            "source_questions": source_questions,
            "targets": targets,
            "source_provenance_sha256": digest(source_provenance),
            "answer_values_stored": False,
            "tie_rule": "lowest-source-index; lowest-expert-slot",
            "feature_recipe": "actual-trained-parent-adapter-enabled-final-hidden-state-full-prompt-mean",
        },
    )
    receipts["dense"] = {
        "wall_seconds": time.perf_counter() - started,
        **cpu_delta(before),
        "parent_feature_work_charged_separately": True,
    }
    for name in ("lexical", "dense"):
        artifacts = [output / f"{name}-index.json", output / f"{name}-prototypes.npy"]
        receipts[name]["artifacts"] = [
            {"path": str(path), "sha256": file_sha(path), "bytes": path.stat().st_size}
            for path in artifacts
        ]
        receipts[name]["artifact_bytes"] = sum(
            row["bytes"] for row in receipts[name]["artifacts"]
        )
        receipts[name]["optimizer_updates"] = 0

    before, started = cpu_snapshot(), time.perf_counter()
    predicted = {
        name: [router.predict({"question": question}) for question in questions]
        for name, router in routers.items()
    }
    predicted.update(lexical=lexical_routes, dense=dense_routes)
    prediction_cost = {
        "queries_per_policy": len(questions),
        "policies": list(routers),
        "wall_seconds": time.perf_counter() - started,
        **cpu_delta(before),
        "nearest_neighbor_predictions_in_index_cost": True,
    }
    source_routes = {name: rows[: len(source_rows)] for name, rows in predicted.items()}
    plan = []
    for index, probe in enumerate(final_metadata):
        eligibility = [
            probe_eligibility(probe, version, capabilities)
            for version in versions["split"]
        ]
        eligible = [
            i for i, value in enumerate(eligibility) if value["capability_allowed"]
        ]
        routes = {
            name: rows[len(source_rows) + index] for name, rows in predicted.items()
        }
        routes["metadata"] = {
            "slot": eligible[0] if eligible else None,
            "reason": "metadata_capability",
        }
        plan.append(
            {
                **probe,
                "routes": routes,
                "eligible_slots": eligible,
                "eligibility": eligibility,
                "guarded_slots": {
                    name: route["slot"] if route["slot"] in eligible else None
                    for name, route in routes.items()
                },
            }
        )
    frozen = {
        "rows": plan,
        "versions": versions,
        "router_receipts": receipts,
        "original_router_sha256": original_pin["original_router_sha256"],
        "original_config": dict(original.config),
        "final_gold_received": False,
        "metadata_uses_supplied_structured_operations": True,
        "source_provenance_sha256": digest(source_provenance),
        "final_raw_outputs_received": False,
        "frozen_unix_ns": time.time_ns(),
        "live_dispatch_executed": False,
    }
    retain(output / "route-plan.json", frozen)
    retain(output / "source-routes.json", source_routes)
    retain(
        output / "route-costs.json",
        {"receipts": receipts, "predictions": prediction_cost},
    )
    return frozen, {"receipts": receipts, "predictions": prediction_cost}, source_routes
