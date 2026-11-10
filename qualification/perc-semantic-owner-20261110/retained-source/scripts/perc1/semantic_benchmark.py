"""Execute bounded synthetic semantic PERC comparisons with real frozen encoding.

Synthetic confirmation validates engineering. It never qualifies scientific benefit,
ordinary daemon capture authority, independent real sources, energy or paid cost.
"""

import argparse
import base64
import gzip
import io
import json
import random
import time
from pathlib import Path

import numpy as np
from PIL import Image

from .native import wire_bytes
from .producer import FrozenMobileNet, produce
from .projection import fit_projection
from .schema import canonical, require, sha
from .semantic_contract import validate_arm_budgets, validate_split_registry
from .semantic_data import make_panel
from .semantic_policy import (
    current_candidates,
    execute,
    fit_head,
    head_scores,
    rank,
    rule_scores,
    vectors,
)

ARMS = ("rules", "global", "dense")
SEEDS = (1101, 2202, 3303)
SOURCE_FILES = (
    "semantic_benchmark",
    "semantic_data",
    "semantic_policy",
    "semantic_contract",
    "producer",
    "projection",
    "native",
    "raster",
    "schema",
)


def _write(path, value):
    with Path(path).open("xb") as handle:
        handle.write(canonical(value) + b"\n")


def _read(root, relative, expected, limit=4 * 1024 * 1024):
    path = (root / relative).resolve()
    require(
        path.is_relative_to(root.resolve()) and path.stat().st_size <= limit,
        "source escapes root/bounds",
    )
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    require(
        0 < len(raw) <= limit and sha(raw) == expected,
        "source content changed/exceeded bounds",
    )
    return raw


def _images(root, task, record):
    images, count = {}, 0
    for capture in task["packet"]["captures"]:
        raw = _read(root, record["captures"][capture["capture_id"]], capture["sha256"])
        image = Image.open(io.BytesIO(raw)).convert("RGB")
        require(
            image.size == (capture["width"], capture["height"]),
            "capture geometry changed",
        )
        images[capture["capture_id"]] = image
        count += len(raw)
    return images, count


def _reader(root, record):
    def read(candidate_id):
        source = record["sources"][candidate_id]
        return _read(root, source["path"], source["sha256"], 8192)

    return read


def _regions(packet, capture):
    return [
        dict(
            evidence_id=f"tile-{i}",
            x=c["rectangle"][0],
            y=c["rectangle"][1],
            width=c["rectangle"][2],
            height=c["rectangle"][3],
        )
        for i, c in enumerate(packet["candidates"])
        if c["capture_id"] == capture["capture_id"]
    ]


def _encode(root, task, record, worker, projection, arm, phase, archive):
    packet, embeddings, receipts = task["packet"], [], []
    for capture in packet["captures"]:
        request = dict(
            schema="perc1.producer-request.v1",
            operation_id=f"{phase}:{arm}:{packet['task_id']}:{capture['frame_index']}",
            capture_path=str(root / record["captures"][capture["capture_id"]]),
            capture_sha256=capture["sha256"],
            source_id=capture["capture_id"],
            observed_at_micros=time.time_ns() // 1000,
            regions=_regions(packet, capture),
            representation=arm,
            scope_digest=sha(packet),
            source_frontier=sha(capture),
            exact_text=None,
        )
        result = produce(worker, request, projection)
        wire = wire_bytes(result["observation"])
        require(
            sha(wire) == result["observation_sha256"],
            "producer native wire digest mismatch",
        )
        embeddings.append(
            np.asarray([v["values_q24"] for v in result["observation"]["latents"]])
            / 2**24
        )
        receipts.append(result["receipt_sha256"])
        archive.write(
            canonical(
                dict(
                    phase=phase,
                    arm=arm,
                    task_id=packet["task_id"],
                    producer_request=request,
                    native_wire_base64=base64.b64encode(wire).decode("ascii"),
                    native_wire_sha256=sha(wire),
                    receipt=result,
                )
            )
            + b"\n"
        )
    return vectors(packet, embeddings, arm), receipts


def _run_actor(root, task, record, worker, projection, arm, head, phase, archive):
    wall, cpu, calls = time.perf_counter_ns(), time.process_time_ns(), worker.calls
    begin = time.perf_counter_ns()
    images, capture_bytes = _images(root, task, record)
    capture_ns = time.perf_counter_ns() - begin
    packet = task["packet"]
    begin = time.perf_counter_ns()
    if arm == "rules":
        features, receipts = None, []
    else:
        features, receipts = _encode(
            root, task, record, worker, projection, arm, phase, archive
        )
    encoding_ns = time.perf_counter_ns() - begin
    begin = time.perf_counter_ns()
    scores = (
        rule_scores(packet, images) if arm == "rules" else head_scores(head, features)
    )
    ranking = rank(packet, scores)
    decision_ns = time.perf_counter_ns() - begin
    result = execute(packet, ranking, _reader(root, record))
    require(
        len(packet["captures"]) + result["reads"]
        <= len(packet["captures"]) + packet["read_budget"],
        "total source acquisition budget exceeded",
    )
    return dict(
        task_id=packet["task_id"],
        family=task["family"],
        arm=arm,
        result=result,
        public_packet_sha256=sha(packet),
        initial_images_sha256=sha({k: sha(v.tobytes()) for k, v in images.items()}),
        head_sha256=None if head is None else sha(head),
        ranking=ranking,
        producer_receipts=receipts,
        encoder_calls=worker.calls - calls,
        measurements=dict(
            online_wall_ns=time.perf_counter_ns() - wall,
            cpu_ns=time.process_time_ns() - cpu,
            initial_capture_read_ns=capture_ns,
            encoding_and_receipt_ns=encoding_ns,
            ranking_ns=decision_ns,
            initial_reads=len(packet["captures"]),
            initial_capture_bytes=capture_bytes,
            source_bytes=result["source_bytes"],
            energy_joules=None,
            provider_billing=None,
        ),
    )


def _summary(rows):
    return {
        arm: dict(
            tasks=len(selected := [r for r in rows if r["arm"] == arm]),
            correct=sum(r["correct"] for r in selected),
            reads=sum(r["result"]["reads"] for r in selected),
            total_source_reads=sum(
                r["result"]["reads"] + r["measurements"].get("initial_reads", 0)
                for r in selected
            ),
            encoder_calls=sum(r["encoder_calls"] for r in selected),
            online_wall_ns=sum(r["measurements"]["online_wall_ns"] for r in selected),
            cpu_ns=sum(r["measurements"]["cpu_ns"] for r in selected),
        )
        for arm in (*ARMS, "direct_roi_oracle")
    }


def run(weights, weights_sha256, output, *, seed=20261110, counts=None, steps=200):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    output = Path(output)
    require(
        not output.exists(), "fresh output required; do not overwrite earlier attempts"
    )
    output.mkdir(parents=True)
    code = {
        name: sha(Path(__file__).with_name(name + ".py").read_bytes())
        for name in SOURCE_FILES
    }
    panel = make_panel(output / "data", seed=seed, counts=counts)
    root = output / "data"
    validate_split_registry(panel["registry"])
    for task in panel["tasks"]:
        p = task["packet"]
        budget = dict(
            public_packet_sha256=sha(p),
            maximum_reads=len(p["captures"]) + p["read_budget"],
            maximum_pixels=sum(c["width"] * c["height"] for c in p["captures"])
            + 2 * 24 * 24,
            maximum_text_bytes=p["read_budget"] * 8192,
            initial_reads=len(p["captures"]),
        )
        validate_arm_budgets({arm: dict(budget) for arm in ARMS})
    worker = FrozenMobileNet(weights, weights_sha256, "cpu")
    _write(
        output / "EXECUTION_PINS.json",
        dict(
            schema="perc1.semantic-execution-pins.v1",
            code=code,
            dataset_sha256=sha(panel),
            backbone_sha256=weights_sha256,
            worker_versions=worker.versions,
            seeds=list(SEEDS),
            steps=steps,
            synthetic_confirmation=True,
            adoption_allowed=False,
            fair_arms=list(ARMS),
            oracle_reference_comparable=False,
            source_scope="generated source text and raster files; no ordinary daemon capture authority",
        ),
    )
    train_tasks = [t for t in panel["tasks"] if t["split"] == "train"]
    features, captures, groups = [], [], []
    pca_start = time.perf_counter_ns()
    with gzip.GzipFile(
        filename=str(output / "ENCODER_RECEIPTS.jsonl.gz"), mode="wb", mtime=0
    ) as archive:
        for task in train_tasks:
            packet, record = task["packet"], panel["records"][task["packet"]["task_id"]]
            for capture in packet["captures"]:
                raw = _read(
                    root, record["captures"][capture["capture_id"]], capture["sha256"]
                )
                _, values, receipt = worker.features(raw, _regions(packet, capture))
                features.extend(values)
                captures.extend(
                    [dict(sha256=capture["sha256"], split="train")] * len(values)
                )
                groups.extend([packet["task_id"]] * len(values))
                archive.write(
                    canonical(
                        dict(
                            phase="train_pca",
                            task_id=packet["task_id"],
                            receipt=receipt,
                        )
                    )
                    + b"\n"
                )
        pca_calls = worker.calls
        projection = fit_projection(
            np.asarray(features),
            captures=captures,
            groups=groups,
            backbone_sha256=weights_sha256,
            dimension=16,
        )
        _write(output / "projection.json", projection)
        np.save(
            output / "TRAIN_BACKBONE_FEATURES.npy",
            np.asarray(features, dtype="<f4"),
            allow_pickle=False,
        )
        pca_ns = time.perf_counter_ns() - pca_start
        print(
            json.dumps(
                dict(
                    stage="projection_ready",
                    path=str(output / "projection.json"),
                    file_sha256=sha((output / "projection.json").read_bytes()),
                    encoder_calls=worker.calls,
                )
            ),
            flush=True,
        )
        train_labels = {
            t["task_id"]: t
            for t in json.loads((root / "train-targets.json").read_bytes())
        }
        training, heads = {a: [] for a in ("global", "dense")}, {}
        collect_start = time.perf_counter_ns()
        for task in train_tasks:
            for arm in training:
                x, _ = _encode(
                    root,
                    task,
                    panel["records"][task["packet"]["task_id"]],
                    worker,
                    projection,
                    arm,
                    "train",
                    archive,
                )
                training[arm].append(x)
        training_collection_ns, training_calls = (
            time.perf_counter_ns() - collect_start,
            worker.calls - pca_calls,
        )
        y = [
            next(
                i
                for i, c in enumerate(current_candidates(t["packet"]))
                if c["candidate_id"]
                == train_labels[t["packet"]["task_id"]]["candidate_id"]
            )
            for t in train_tasks
        ]
        for arm, x in training.items():
            for model_seed in SEEDS:
                head = fit_head(x, y, seed=model_seed, steps=steps)
                head.update(
                    arm=arm,
                    training_features_sha256=sha(np.asarray(x, dtype="<f8").tobytes()),
                    training_targets_sha256=sha(train_labels),
                    projection_sha256=sha(projection),
                    code_sha256=sha(code),
                )
                heads[arm, model_seed] = head
                _write(output / f"head-{arm}-{model_seed}.json", head)
        frozen = dict(
            heads={f"{a}-{s}": sha(h) for (a, s), h in heads.items()},
            projection_sha256=sha(projection),
            panel_sha256=sha(panel),
            code=code,
            confirmation_labels_opened=False,
            hyperparameters_tuned_on_dev=False,
        )
        _write(output / "FROZEN_HEADS.json", frozen)
        print(
            json.dumps(
                dict(
                    stage="heads_frozen",
                    fits=len(heads),
                    optimizer_updates=len(heads) * steps,
                )
            ),
            flush=True,
        )
        rows, online_calls = [], worker.calls
        confirmation = [t for t in panel["tasks"] if t["split"] == "confirmation"]
        for model_seed in SEEDS:
            for task in confirmation:
                order = list(ARMS)
                random.Random(
                    int(sha([model_seed, task["packet"]["task_id"]]), 16)
                ).shuffle(order)
                for arm in order:
                    row = _run_actor(
                        root,
                        task,
                        panel["records"][task["packet"]["task_id"]],
                        worker,
                        projection,
                        arm,
                        heads.get((arm, model_seed)),
                        f"confirmation-{model_seed}",
                        archive,
                    )
                    row["seed"] = model_seed
                    rows.append(row)
            print(
                json.dumps(
                    dict(
                        stage="online_seed_complete",
                        seed=model_seed,
                        rows=len(rows),
                        encoder_calls=worker.calls - online_calls,
                    )
                ),
                flush=True,
            )
        online_calls = worker.calls - online_calls
    # The private synthetic evaluator is opened only after every fair actor has finished.
    targets = {
        t["task_id"]: t
        for t in json.loads((root / "confirmation-targets.json").read_bytes())
    }
    for row in rows:
        target, answer = targets[row["task_id"]], row["result"]["answer"]
        row["correct"] = bool(
            answer
            and answer["candidate_id"] == target["candidate_id"]
            and answer["text"] == target["answer"]
        )
    for model_seed in SEEDS:
        for task in confirmation:
            packet = task["packet"]
            target = targets[packet["task_id"]]
            first = target["candidate_id"]
            ordering = [first] + [
                c["candidate_id"]
                for c in current_candidates(packet)
                if c["candidate_id"] != first
            ]
            wall, cpu_start = time.perf_counter_ns(), time.process_time_ns()
            result = execute(
                packet, ordering, _reader(root, panel["records"][packet["task_id"]])
            )
            rows.append(
                dict(
                    task_id=packet["task_id"],
                    family=task["family"],
                    seed=model_seed,
                    arm="direct_roi_oracle",
                    result=result,
                    encoder_calls=0,
                    oracle_information=True,
                    comparable=False,
                    correct=bool(
                        result["answer"]
                        and result["answer"]["text"] == target["answer"]
                    ),
                    measurements=dict(
                        online_wall_ns=time.perf_counter_ns() - wall,
                        cpu_ns=time.process_time_ns() - cpu_start,
                    ),
                )
            )
    require(
        code
        == {
            name: sha(Path(__file__).with_name(name + ".py").read_bytes())
            for name in SOURCE_FILES
        },
        "source changed during experiment",
    )
    _write(output / "ROWS.json", rows)
    report = dict(
        schema="perc1.synthetic-semantic-report.v1",
        status="HOLD",
        scientific_qualified=False,
        independent_real_sources=False,
        ordinary_daemon_capture_qualified=False,
        terminal_net_utility_qualified=False,
        net_utility=None,
        source_pins_sha256=sha(
            json.loads((output / "EXECUTION_PINS.json").read_bytes())
        ),
        frozen_heads_sha256=sha(frozen),
        dataset_sha256=sha(panel),
        code=code,
        families=sorted({t["family"] for t in confirmation}),
        distinct_confirmation_tasks=len(confirmation),
        training_seeds=list(SEEDS),
        repeated_tasks_are_not_independent_samples=True,
        fits=len(heads),
        optimizer_updates=len(heads) * steps,
        online_encoder_calls=online_calls,
        training_encoder_calls=training_calls,
        projection_encoder_calls=pca_calls,
        total_encoder_calls=worker.calls,
        per_seed={str(s): _summary([r for r in rows if r["seed"] == s]) for s in SEEDS},
        by_family={
            family: _summary([r for r in rows if r["family"] == family])
            for family in sorted({t["family"] for t in confirmation})
        },
        overall=_summary(rows),
        setup=dict(
            worker_cold_load_ns=worker.cold_load_ns,
            pca_ns=pca_ns,
            training_collection_ns=training_collection_ns,
            fits_ns=sum(h["training"]["elapsed_ns"] for h in heads.values()),
        ),
        lifecycle_wall_ns=time.perf_counter_ns() - started,
        lifecycle_cpu_ns=time.process_time_ns() - cpu,
        evidence=dict(
            encoder_receipts_sha256=sha(
                (output / "ENCODER_RECEIPTS.jsonl.gz").read_bytes()
            ),
            rows_sha256=sha((output / "ROWS.json").read_bytes()),
            projection_file_sha256=sha((output / "projection.json").read_bytes()),
            training_backbone_features_sha256=sha(
                (output / "TRAIN_BACKBONE_FEATURES.npy").read_bytes()
            ),
        ),
        limitations=[
            "Controlled synthetic shapes, grammar, templates and generated source streams, not unseen real organizations.",
            "Source-text reads are exact generated originals, not OCR accuracy evidence.",
            "Raster references locate associated cards; numeric codes exist in source text, not painted pixels.",
            "Global uses mean-pooled crop features; dense preserves spatial crop tokens.",
            "Same public images, semantics and read/pixel/text caps; runtime computation costs are measured separately.",
            "total_source_reads counts logical observations; producer re-reads of immutable capture files are extra physical I/O included in wall/CPU, not new observations.",
            "Direct ROI receives evaluator coordinates and is an oracle reference, excluded from fair-arm claims.",
            "DEV is reserved but unused; no hyperparameter selection or real-world confirmation is claimed.",
            "Energy, paid provider bills, complete process-tree resources and ordinary capture authority are unproved.",
            "Lifecycle starts at run entry, excludes Python imports and final report write; online excludes final row serialization.",
        ],
    )
    _write(output / "REPORT.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", required=True)
    parser.add_argument("--weights-sha256", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=20261110)
    parser.add_argument("--steps", type=int, default=200)
    parser.add_argument("--train-per-family", type=int, default=12)
    parser.add_argument("--dev-per-family", type=int, default=4)
    parser.add_argument("--confirmation-per-family", type=int, default=6)
    args = parser.parse_args()
    report = run(
        args.weights,
        args.weights_sha256,
        args.output,
        seed=args.seed,
        steps=args.steps,
        counts=dict(
            train=args.train_per_family,
            dev=args.dev_per_family,
            confirmation=args.confirmation_per_family,
        ),
    )
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "status",
                    "fits",
                    "optimizer_updates",
                    "distinct_confirmation_tasks",
                    "online_encoder_calls",
                    "overall",
                )
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
