"""Source-only router fitting and costed selection before final population reads."""

import gc
import hashlib
import json
import math
from pathlib import Path
import struct
import time

from learned_router import fit_router, load_router
from parametric_model import SourceMemoryCell, adapter_digest
from population_fixtures import canonical_bytes, validate_sources
from router_features import verify_question_splits


ARMS = ("parent", "single", "split")
RULE = (
    "Parent semantic recall >=0.75; preserve every parent-correct semantic item. "
    "Single needs >=1 additional supported source answer. Split needs >=ceil(0.05*N) "
    "additional answers over the best eligible cheaper arm, equal single/split "
    "adapter bytes and <=1% serialized-router overhead. Ties retain cheaper."
)


def choose_population(source_scores, families, costs):
    """Choose from source-held-out supported correctness, never final metrics."""
    if (
        type(source_scores) is not dict
        or type(costs) is not dict
        or set(source_scores) != set(ARMS)
        or set(costs) != set(ARMS)
    ):
        raise ValueError("registered population arms required")
    if (
        type(families) is not list
        or len(families) != 64
        or {kind: families.count(kind) for kind in set(families)}
        != {"semantic": 16, "episode": 24, "procedure": 24}
    ):
        raise ValueError("registered heterogeneous source cohort required")
    for arm in ARMS:
        values = source_scores[arm]
        if (
            type(values) is not list
            or len(values) != len(families)
            or any(type(v) is not bool for v in values)
        ):
            raise ValueError("aligned boolean source correctness required")
        if type(costs[arm]) is not dict or not {
            "private_parameter_bytes",
            "retained_checkpoint_bytes",
            "optimizer_steps",
            "router_artifact_bytes",
        } <= set(costs[arm]):
            raise ValueError("complete measured candidate costs required")
        if any(
            type(value) is not int or not 0 <= value < 2**63
            for value in costs[arm].values()
        ):
            raise ValueError("finite nonnegative measured byte/update costs required")
        if (
            not costs[arm]["private_parameter_bytes"]
            or not costs[arm]["retained_checkpoint_bytes"]
        ):
            raise ValueError("candidate storage cannot be omitted")
    old = [i for i, kind in enumerate(families) if kind == "semantic"]
    parent_correct = sum(source_scores["parent"][i] for i in old)
    parent_pass = parent_correct / len(old) >= 0.75
    preserved = {
        arm: all(not source_scores["parent"][i] or source_scores[arm][i] for i in old)
        for arm in ARMS
    }
    totals = {arm: sum(source_scores[arm]) for arm in ARMS}
    single_ok = (
        parent_pass and preserved["single"] and totals["single"] >= totals["parent"] + 1
    )
    cheaper = "single" if single_ok else "parent"
    matched = (
        costs["split"]["private_parameter_bytes"]
        == costs["single"]["private_parameter_bytes"]
    )
    overhead = (
        costs["split"]["router_artifact_bytes"] * 100
        <= costs["single"]["private_parameter_bytes"]
    )
    work_matched = (
        costs["single"]["optimizer_steps"] == costs["split"]["optimizer_steps"] > 0
    )
    minimum_gain = math.ceil(0.05 * len(families))
    split_ok = (
        parent_pass
        and preserved["split"]
        and matched
        and overhead
        and work_matched
        and totals["split"] >= totals[cheaper] + minimum_gain
    )
    chosen = "split" if split_ok else cheaper
    return {
        "schema": "hepta.population.source-choice.v1",
        "rule": RULE,
        "chosen_arm": chosen,
        "parent_semantic_correct": parent_correct,
        "parent_semantic_total": len(old),
        "parent_recall_gate": parent_pass,
        "parent_correct_semantic_preserved": preserved,
        "source_correct_counts": totals,
        "single_eligible": single_ok,
        "split_eligible": split_ok,
        "best_eligible_cheaper_arm": cheaper,
        "minimum_split_gain": minimum_gain,
        "split_gain_over_single": totals["split"] - totals["single"],
        "same_single_split_adapter_bytes": matched,
        "matched_optimizer_updates": work_matched,
        "router_within_one_percent": overhead,
        "selected_cost": costs[chosen],
        "final_scores_used": False,
        "production_accepted": False,
    }


def _checkpoint_cost(versions):
    private = retained = updates = 0
    for version in versions:
        directory = Path(version["directory"])
        with (directory / "adapter_model.safetensors").open("rb") as stream:
            length = struct.unpack("<Q", stream.read(8))[0]
            if not 0 < length <= 1024 * 1024:
                raise ValueError("bounded safetensors header required")
            header = json.loads(stream.read(length))
        for name, entry in header.items():
            if name == "__metadata__":
                continue
            if entry["dtype"] != "F32":
                raise ValueError("registered float32 adapter cost required")
            private += entry["data_offsets"][1] - entry["data_offsets"][0]
        retained += sum(
            path.stat().st_size for path in directory.iterdir() if path.is_file()
        )
        manifest_bytes = (directory / "lineage.json").read_bytes()
        if hashlib.sha256(manifest_bytes).hexdigest() != version["manifest_sha256"]:
            raise ValueError("cost metadata differs from pinned checkpoint")
        updates += json.loads(manifest_bytes)["training"]["steps"]
    return {
        "private_parameter_bytes": private,
        "retained_checkpoint_bytes": retained,
        "optimizer_steps": updates,
        "router_artifact_bytes": 0,
        "router_parameter_bytes": 0,
    }


def _generate(model, version, scope, probes):
    started = time.perf_counter()
    cell = SourceMemoryCell(Path(model), rank=version["rank"], seed=version["seed"])
    try:
        cell.load(
            Path(version["directory"]),
            expected_manifest_sha256=version["manifest_sha256"],
            scope=scope,
            allowed_roots=set(version["roots"]),
            revoked=set(),
        )
        before = adapter_digest(cell.reader.model)
        rows = cell.generate([probe["question"] for probe in probes])
        if adapter_digest(cell.reader.model) != before:
            raise ValueError("source inference changed adapter")
        if [row["question"] for row in rows] != [probe["question"] for probe in probes]:
            raise ValueError("source generation/query alignment changed")
        return {
            "version": version,
            "rows": rows,
            "wall_seconds": time.perf_counter() - started,
            "adapter_state_sha256": before,
            "final_scores_used": False,
        }
    finally:
        del cell
        gc.collect()


def prepare_selection(model, data, training, output, write_json):
    """Read only sources/router-training/source-selection fields of the dataset."""
    sources = validate_sources(data["sources"])
    allowed = {row["source_digest"] for row in sources}
    versions = json.loads(json.dumps(training["versions"]))
    if set(versions) != set(ARMS) or [len(versions[a]) for a in ARMS] != [1, 1, 2]:
        raise ValueError("one parent, one single, two split versions required")
    for arm in ARMS:
        for version in versions[arm]:
            if not set(version["roots"]) <= allowed or not version["roots"]:
                raise ValueError("candidate has undeclared source ancestry")
    if [v["rank"] for arm in ARMS for v in versions[arm]] != [4, 8, 4, 4]:
        raise ValueError("registered matched-budget ranks required")
    router_probes = data["router_training"] + data["router_reject_training"]
    selection_probes = data["source_selection"]
    if (
        len(data["router_training"]) != 64
        or len(data["router_reject_training"]) != 12
        or len(selection_probes) != 64
    ):
        raise ValueError("registered source-router and selection cohorts required")
    verify_question_splits(
        {
            "router_training": [p["question"] for p in router_probes],
            "source_selection": [p["question"] for p in selection_probes],
        }
    )
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    split_raw = [
        _generate(model, version, data["scope"], router_probes + selection_probes)
        for version in versions["split"]
    ]
    observations = []
    for index, probe in enumerate(router_probes):
        utilities = [
            float(
                raw["rows"][index]["text"] == probe["value"]
                and bool(probe["source_roots"])
                and set(probe["source_roots"]) <= set(version["roots"])
            )
            for raw, version in zip(split_raw, versions["split"], strict=True)
        ]
        observations.append(
            {
                "question": probe["question"],
                "utilities": utilities,
                "reject": index >= len(data["router_training"]),
            }
        )
    provenance = {
        "sources_sha256": hashlib.sha256(canonical_bytes(sources)).hexdigest(),
        "expert_manifests": [v["manifest_sha256"] for v in versions["split"]],
        "observations": observations,
    }
    router = fit_router(
        observations,
        expert_ids=["split-0", "split-1"],
        source_sha256=hashlib.sha256(canonical_bytes(provenance)).hexdigest(),
    )
    router_path = output / "learned-router.bin"
    router_receipt = router.save(router_path)
    router = load_router(router_path, expected_sha256=router_receipt["sha256"])
    routes = [router.predict({"question": p["question"]}) for p in selection_probes]
    raw = {
        arm: [_generate(model, versions[arm][0], data["scope"], selection_probes)]
        for arm in ("parent", "single")
    }
    raw["split"] = split_raw
    scores = {arm: [] for arm in ARMS}
    assessment = []
    for index, probe in enumerate(selection_probes):
        row = {
            "probe_id": probe["probe_id"],
            "family": probe["family"],
            "route": routes[index],
        }
        for arm in ARMS:
            slot = routes[index]["slot"] if arm == "split" else 0
            source_index = len(router_probes) + index if arm == "split" else index
            text = (
                raw[arm][slot]["rows"][source_index]["text"]
                if slot is not None
                else "unknown"
            )
            supported = (
                slot is not None
                and bool(probe["source_roots"])
                and set(probe["source_roots"]) <= set(versions[arm][slot]["roots"])
            )
            correct = bool(supported and text == probe["value"])
            scores[arm].append(correct)
            row[arm] = {
                "raw_text": text,
                "source_supported": supported,
                "raw_correct": text == probe["value"],
                "supported_correct": correct,
            }
        assessment.append(row)
    costs = {arm: _checkpoint_cost(versions[arm]) for arm in ARMS}
    parent_history_updates = costs["parent"]["optimizer_steps"]
    costs["parent"]["optimizer_steps"] = 0
    costs["split"].update(
        router_artifact_bytes=router_receipt["artifact_bytes"],
        router_parameter_bytes=router_receipt["private_parameter_bytes"],
    )
    families = [probe["family"] for probe in selection_probes]
    choice = choose_population(scores, families, costs)
    write_json(output / "source-generations.json", raw)
    write_json(output / "router-observations.json", provenance)
    write_json(output / "source-assessments.json", assessment)
    generated = [row for arm in ARMS for entry in raw[arm] for row in entry["rows"]]
    report = {
        "schema": "hepta.population.precommitted-selection.v1",
        "scope": data["scope"],
        "choice": choice,
        "versions": versions,
        "costs": costs,
        "source_scores": scores,
        "source_families": families,
        "observations": observations,
        "sources_sha256": provenance["sources_sha256"],
        "router_source_sha256": router.source_sha256,
        "router_path": str(router_path),
        "router_receipt": router_receipt,
        "parent_historical_updates": parent_history_updates,
        "source_work": {
            "queries": len(generated),
            "input_tokens": sum(r["input_tokens"] for r in generated),
            "generated_tokens": sum(r["generated_tokens"] for r in generated),
            "generation_seconds": sum(r["seconds"] for r in generated),
            "model_load_and_generation_wall_seconds": sum(
                entry["wall_seconds"] for entries in raw.values() for entry in entries
            ),
        },
        "final_scores_used": False,
        "source_authority": "pinned_local_research_sources",
        "production_accepted": False,
    }
    path = output / "precommitted-selection.json"
    write_json(path, report)
    return {
        **report,
        "selection_path": str(path),
        "selection_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
