"""Run the bounded FUNSD quality-recovery pilot; all scientific gates stay HOLD.

This offline driver owns evaluator labels. document_actor receives only public
dataset objects, acquired observations, frozen heads and budget metadata.
"""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import random
import time

import numpy as np
from PIL import Image

from . import document_actor as actor
from .acquisition import save_head, train_head
from .document_report import evaluate
from .experiment import capture_identity
from .producer import FrozenMobileNet, PREPROCESS
from .projection import fit_projection
from .schema import Cost, Dataset, PHASES, canonical, load, manifest, require, sha

COST_VALUE = 0.5 / 1_000_000
SEED = 0


def _micro(ns):
    return max(1, (ns + 999) // 1000)


def _add(*costs):
    return asdict(Cost(**{p: sum(c[p] for c in costs) for p in PHASES}))


def _write(path, value):
    with Path(path).open("xb") as output:
        output.write(canonical(value) + b"\n")


def _evidence(dataset, receipts):
    return [
        {
            "source_id": r["source_id"],
            "receipt_sha256": r["receipt_sha256"],
            "capture_sha256": capture_identity(dataset.sources[r["source_id"]]),
        }
        for r in receipts
    ]


def _score(answer, target):
    return float(
        answer["text"] == target["answer"]
        and all(answer["fields"].get(k) == v for k, v in target["fields"].items())
    )


def _projection(dataset, worker, output):
    stage_started = time.perf_counter_ns()
    features, captures, groups, receipts = [], [], [], []
    cost = asdict(Cost())
    for episode in dataset.episodes.values():
        if episode["split"] != "train":
            continue
        for source_id in episode["initial_ids"]:
            started = time.perf_counter_ns()
            raw = dataset.read(source_id)
            acquisition = _micro(time.perf_counter_ns() - started)
            with Image.open(dataset.root / dataset.sources[source_id]["path"]) as image:
                regions = actor.regions_for(image)
            started = time.perf_counter_ns()
            _, values, receipt = worker.features(raw, regions)
            cost = _add(
                cost,
                asdict(
                    Cost(
                        acquisition=acquisition,
                        encoding=_micro(time.perf_counter_ns() - started),
                    )
                ),
            )
            features.extend(values)
            captures.extend([{"sha256": sha(raw), "split": "train"}] * len(values))
            groups.extend([episode["group"]] * len(values))
            receipts.append({"source_id": source_id, "execution": receipt})
    projection = fit_projection(
        np.asarray(features),
        captures=captures,
        groups=groups,
        backbone_sha256=worker.weights_sha256,
        dimension=8,
    )
    cost["training"] += _micro(projection["training"]["wall_ns"])
    _write(output / "projection.json", projection)
    _write(output / "projection-executions.json", receipts)
    cost["training"] += max(
        0, _micro(time.perf_counter_ns() - stage_started) - Cost.parse(cost).total
    )
    return projection, cost


def _actor_pairs(dataset, collector, representation, solver_sha256, output):
    """Collect controlled executions before any evaluator labels enter these rows."""
    records, cost = [], asdict(Cost())
    for episode in dataset.episodes.values():
        if episode["split"] not in ("train", "dev"):
            continue
        require(len(episode["initial_ids"]) == 1, "pilot requires one initial capture")
        initial = collector.observe(episode["initial_ids"][0], representation)
        initial_cost = collector.accounted_cost(initial)
        cost = _add(cost, initial_cost)
        before_start = time.perf_counter_ns()
        before_answer = actor.terminal(dataset, episode, [initial])
        before_solver = asdict(
            Cost(inference=_micro(time.perf_counter_ns() - before_start))
        )
        cost = _add(cost, before_solver)
        prefix = {
            "task": episode["task"],
            "catalog": [
                {"id": i, "description": dataset.sources[i]["description"]}
                for i in episode["source_ids"]
            ],
            "acquired_receipt_sha256s": [initial["receipt_sha256"]],
        }
        for candidate in episode["source_ids"]:
            if candidate in episode["initial_ids"]:
                continue
            started = time.perf_counter_ns()
            public = actor.public_features(
                dataset,
                episode,
                [initial],
                candidate,
                prefix,
                max(0, actor.CAP - Cost.parse(initial_cost).total),
                representation,
            )
            feature_cost = asdict(
                Cost(decision=_micro(time.perf_counter_ns() - started))
            )
            extra = collector.observe(candidate, representation)
            extra_cost = collector.accounted_cost(extra)
            started = time.perf_counter_ns()
            after_answer = actor.terminal(dataset, episode, [initial, extra])
            after_solver = asdict(
                Cost(inference=_micro(time.perf_counter_ns() - started))
            )
            cost = _add(cost, feature_cost, extra_cost, after_solver)
            common = dict(
                prefix_sha256=sha(prefix),
                solver_sha256=solver_sha256,
                inference_seed=SEED,
            )
            pair = dict(
                schema="perc1.acquisition-pair.v1",
                source_group=episode["group"],
                split=episode["split"],
                candidate_id=candidate,
                features=public,
                without=dict(
                    common,
                    evidence=_evidence(dataset, [initial]),
                    score=None,
                    cost=_add(initial_cost, before_solver),
                ),
            )
            pair["with"] = dict(
                common,
                evidence=_evidence(dataset, [initial, extra]),
                score=None,
                cost=_add(initial_cost, extra_cost, after_solver, feature_cost),
            )
            records.append(
                {
                    "episode_id": episode["id"],
                    "pair": pair,
                    "without_answer": before_answer,
                    "with_answer": after_answer,
                }
            )
    _write(output / (representation + "-actor-pairs.json"), records)
    return records, cost


def run(dataset_dir, weights, weights_sha256, output_dir):
    started = time.perf_counter_ns()
    root, output = Path(dataset_dir), Path(output_dir)
    require(
        not output.exists(),
        "fresh output directory required; preserve earlier attempts",
    )
    output.mkdir(parents=True)
    dataset = Dataset(load(root / "dataset.json"), root)
    panel = load(root / "panel.json")
    require(
        panel["dataset_sha256"] == sha(dataset.value), "panel/dataset identity changed"
    )
    splits = {
        s: sorted({e["group"] for e in dataset.episodes.values() if e["split"] == s})
        for s in ("train", "dev", "confirmation")
    }
    # Cheap cross-split check before importing weights or collecting training data.
    identities = {}
    for source in dataset.sources.values():
        for identity in (source["sha256"], source["locator"]["origin_sha256"]):
            require(
                identity not in identities or identities[identity] == source["split"],
                "source identity crosses splits",
            )
            identities[identity] = source["split"]
    worker = FrozenMobileNet(weights, weights_sha256)
    projection, projection_cost = _projection(dataset, worker, output)
    training_cost = projection_cost.copy()
    collector = actor.Collector(dataset, worker, projection, output / "collector")
    code = {p.name: sha(p.read_bytes()) for p in Path(__file__).parent.glob("*.py")}
    solver_sha256 = sha(
        {
            "actor": code["document_actor.py"],
            "collector": code["document_collector.py"],
            "ocr_engine": collector.engine,
            "solver": "frozen OCR plus public coverage selection",
        }
    )
    _write(
        output / "EXECUTION_PINS.json",
        {
            "schema": "perc1.document-execution-pins.v1",
            "dataset_sha256": sha(dataset.value),
            "backbone_sha256": worker.weights_sha256,
            "projection_sha256": sha(projection),
            "code": code,
            "preprocess_sha256": sha(PREPROCESS),
            "solver_sha256": solver_sha256,
            "ocr_engine": collector.engine,
            "collector_root": "collector",
            "cost_value": COST_VALUE,
            "online_budget": actor.CAP,
            "acquisition_quote": actor.READ_QUOTE,
            "scientific_qualified": False,
        },
    )
    actor_rows, collection_costs = {}, {}
    for representation in ("global", "dense"):
        actor_rows[representation], cost = _actor_pairs(
            dataset, collector, representation, solver_sha256, output
        )
        collection_costs[representation] = cost
        training_cost = _add(training_cost, cost)
    evaluation_started = time.perf_counter_ns()
    training_targets = load(root / "training-targets.json")
    target_map = {t["episode_id"]: t for t in training_targets}
    require(
        len(target_map) == len(training_targets)
        and set(target_map)
        == {
            e["id"] for e in dataset.episodes.values() if e["split"] in ("train", "dev")
        },
        "training labels include holdout or omit development episodes",
    )
    label_read_cost = asdict(
        Cost(training=_micro(time.perf_counter_ns() - evaluation_started))
    )
    training_cost = _add(training_cost, label_read_cost)
    labeled, label_costs = {}, {}
    for representation, records in actor_rows.items():
        label_started = time.perf_counter_ns()
        labeled[representation] = []
        for record in records:
            pair = record["pair"]
            target = target_map[record["episode_id"]]
            pair["without"]["score"] = _score(record["without_answer"], target)
            pair["with"]["score"] = _score(record["with_answer"], target)
            labeled[representation].append(pair)
        _write(
            output / (representation + "-labeled-pairs.json"), labeled[representation]
        )
        label_costs[representation] = asdict(
            Cost(training=_micro(time.perf_counter_ns() - label_started))
        )
        training_cost = _add(training_cost, label_costs[representation])
    label_evaluation_ns = time.perf_counter_ns() - evaluation_started
    heads, head_costs = {}, {}
    for representation, pairs in labeled.items():
        fit_started = time.perf_counter_ns()
        heads[representation] = train_head(
            [p for p in pairs if p["split"] == "train"],
            [p for p in pairs if p["split"] == "dev"],
            splits,
            feature_extractor_sha256=code["document_actor.py"],
            seed=SEED,
            cost_value=COST_VALUE,
            ridge=1.0,
            threshold=0.0,
        )
        save_head(output / (representation + "-head.json"), heads[representation])
        head_costs[representation] = asdict(
            Cost(training=_micro(time.perf_counter_ns() - fit_started))
        )
        training_cost = _add(training_cost, head_costs[representation])
    training_receipt = {
        "schema": "perc1.document-training.v1",
        "seed": SEED,
        "independent_training_replicate": False,
        "projection_sha256": sha(projection),
        "head_sha256s": {k: sha(v) for k, v in heads.items()},
        "cost": training_cost,
        "cost_scope": "actual actor collection and deterministic fitting; local measured time/byte proxy",
        "model_load_ns_separate": worker.cold_load_ns,
        "label_preparation_ns_in_training": label_evaluation_ns,
        "components": {
            "projection": projection_cost,
            "collection": collection_costs,
            "head_fit": head_costs,
            "label_preparation": label_costs,
            "label_source_read": label_read_cost,
        },
        "pair_cost_scope": "extra capture, completed receipt persistence, candidate feature construction, and actual frozen OCR/terminal continuation; not-yet-fitted head scoring is absent from labels and charged in online traces",
        "provider_billing": None,
        "energy_joules": None,
        "code": code,
    }
    _write(output / "training-receipt.json", training_receipt)
    evaluator = {
        "schema": "perc1.evaluator.v1",
        "identity_sha256": code["document_report.py"],
        "rubric_sha256": sha(
            "case-sensitive exact transcription and selected_word field; no target normalization"
        ),
        "canaries": ["PRIVATE_PERC_LABEL_" + sha(dataset.value)],
        "receipt_sha256": sha(
            {"code": code["document_report.py"], "targets": panel["targets_sha256"]}
        ),
        "cost": asdict(Cost()),
    }
    frozen = {
        "schema": "perc1.manifest.v1",
        "dataset_sha256": sha(dataset.value),
        "encoder": {
            "kind": "external_artifact",
            "checkpoint_sha256": collector.encoder_sha256,
            "preprocessor_sha256": sha(PREPROCESS),
            "dimension": 8,
        },
        "controller": {
            "sha256": sha(
                {
                    "heads": training_receipt["head_sha256s"],
                    "actor": code["document_actor.py"],
                }
            ),
            "training_runs": [
                {
                    "seed": SEED,
                    "receipt_sha256": sha(training_receipt),
                    "cost": training_cost,
                }
            ],
        },
        "evaluator": {
            "identity_sha256": evaluator["identity_sha256"],
            "rubric_sha256": evaluator["rubric_sha256"],
            "targets_sha256": panel["targets_sha256"],
            "canaries_sha256": sha(evaluator["canaries"]),
        },
        "teacher_sha256": None,
        "budget": {
            "unit": "microcredits_v1",
            "cap": actor.CAP,
            "tariff": {p: 1 for p in PHASES},
        },
        "splits": splits,
        "thresholds": None,
    }
    manifest(frozen, dataset)
    _write(output / "manifest.json", frozen)
    executions = []
    orders = {}
    for episode in dataset.episodes.values():
        if episode["split"] == "confirmation":
            conditions = [
                (r, m) for r in ("global", "dense") for m in ("fixed", "active")
            ]
            conditions += [("global", m) for m in ("ocr_only", "direct_roi", "random")]
            random.Random(int(sha([episode["id"], "condition_order"])[:8], 16)).shuffle(
                conditions
            )
            orders[episode["id"]] = conditions
    _write(output / "execution-order.json", orders)
    with (output / "executions.jsonl").open("x") as journal:
        for episode in dataset.episodes.values():
            if episode["split"] != "confirmation":
                continue
            for representation, mode in orders[episode["id"]]:
                result = actor.execute(
                    collector,
                    episode,
                    representation,
                    mode,
                    frozen,
                    heads[representation],
                    random_seed=int(sha(episode["id"])[:8], 16),
                )
                executions.append(result)
                journal.write(canonical(result).decode() + "\n")
                journal.flush()
    finalization = collector.finalize()
    overheads = {
        "training_once": training_cost,
        "projection_once": projection_cost,
        "collection_by_representation": collection_costs,
        "head_fit_by_representation": head_costs,
        "label_preparation_by_representation": label_costs,
        "label_source_read_once": label_read_cost,
        "model_load_once": {
            "wall_ns": worker.cold_load_ns,
            "proxy_microcredits": _micro(worker.cold_load_ns),
        },
        "collector_startup_once": {
            "wall_ns": collector.index["startup_ns"],
            "proxy_microcredits": _micro(collector.index["startup_ns"]),
        },
        "ocr_init_once": {
            "wall_ns": collector.index["ocr_init_ns"],
            "proxy_microcredits": _micro(collector.index["ocr_init_ns"]),
        },
        "audit_finalization_once": finalization["cost"],
        "provider_billing": None,
        "energy_joules": None,
    }
    evaluation_started = time.perf_counter_ns()
    evaluator["targets"] = load(root / "sealed-targets.json")
    require(
        sha(evaluator["targets"]) == panel["targets_sha256"],
        "heldout evaluator changed after freeze",
    )
    evaluator["cost"]["evaluation"] = _micro(
        time.perf_counter_ns() - evaluation_started
    )
    evaluation_started = time.perf_counter_ns()
    report = evaluate(frozen, dataset, executions, evaluator, COST_VALUE, overheads)
    evaluator["cost"]["evaluation"] += _micro(
        time.perf_counter_ns() - evaluation_started
    )
    report["costs"]["evaluation_once"] = evaluator["cost"]
    report["costs"]["campaign_proxy_total_including_evaluation"] = (
        report["costs"]["campaign_proxy_total_excluding_evaluation"]
        + Cost.parse(evaluator["cost"]).total
    )
    report["run_wall_ns"] = time.perf_counter_ns() - started
    report["source_code_sha256s"] = code
    report["execution_pins_sha256"] = sha(load(output / "EXECUTION_PINS.json"))
    report["execution_order_sha256"] = sha(orders)
    report["execution_order_rule"] = (
        "per-document frozen shuffle seeded by SHA256([public episode ID, condition_order]); no target access"
    )
    _write(output / "evaluator.json", evaluator)
    _write(output / "report.json", report)
    artifacts = [
        {
            "path": str(p.relative_to(output)),
            "sha256": sha(p.read_bytes()),
            "bytes": p.stat().st_size,
        }
        for p in sorted(output.rglob("*"))
        if p.is_file()
    ]
    _write(
        output / "ARTIFACTS.json",
        {
            "schema": "perc1.document-artifacts.v1",
            "artifacts": artifacts,
            "publication": "aggregate report and provenance only; captures/answers/receipt payloads remain local",
        },
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("dataset-dir", "weights", "weights-sha256", "output"):
        parser.add_argument("--" + option, required=True)
    args = parser.parse_args()
    try:
        result = run(args.dataset_dir, args.weights, args.weights_sha256, args.output)
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "scientific_qualified": False,
                    "report": str(Path(args.output) / "report.json"),
                }
            )
        )
    except Exception as error:
        output = Path(args.output)
        if output.is_dir() and not (output / "FAILURE.json").exists():
            _write(
                output / "FAILURE.json",
                {
                    "status": "HOLD",
                    "error_type": type(error).__name__,
                    "reason": str(error),
                },
            )
        raise


if __name__ == "__main__":
    main()
