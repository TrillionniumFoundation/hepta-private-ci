"""Fit a no-encoder acquisition control; report DEV diagnostics only.

No confirmation evaluator is opened and no confirmation task is executed.
DEV labels calibrate the head, so these outcomes cannot qualify a policy.
"""

import argparse
from pathlib import Path
import random
import time

from . import document_actor as actor
from .acquisition import train_head
from .document_pilot import _actor_pairs, _micro, _score, _write, COST_VALUE
from .schema import Dataset, PHASES, load, require, sha


def run(dataset_dir, output_dir):
    root, output = Path(dataset_dir), Path(output_dir)
    require(not output.exists(), "fresh output required; preserve earlier attempts")
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
    require(all(splits.values()), "public registry must include all three splits")
    identities = {}
    for source in dataset.sources.values():
        for identity in (source["sha256"], source["locator"]["origin_sha256"]):
            require(
                identity not in identities or identities[identity] == source["split"],
                "source identity crosses splits",
            )
            identities[identity] = source["split"]
    collector = actor.Collector(dataset, None, None, output / "collector")
    code = {p.name: sha(p.read_bytes()) for p in Path(__file__).parent.glob("*.py")}
    pins = dict(
        schema="perc1.public-control-pins.v1",
        dataset_sha256=sha(dataset.value),
        code=code,
        ocr_engine=collector.engine,
        cost_value=COST_VALUE,
        cap=actor.CAP,
        read_quote=actor.READ_QUOTE,
        feature_channel="public",
        panel_sha256=sha(panel),
        confirmation_execution_allowed=False,
        scientific_qualified=False,
    )
    _write(output / "EXECUTION_PINS.json", pins)
    solver = sha({"code": code["document_actor.py"], "ocr": collector.engine})
    records, collection_cost = _actor_pairs(
        dataset, collector, "global", solver, output, channel="public"
    )
    label_started = time.perf_counter_ns()
    targets = load(root / "training-targets.json")
    label_pins = dict(
        targets_sha256=sha(targets),
        file_sha256=sha((root / "training-targets.json").read_bytes()),
    )
    _write(output / "TRAINING_LABEL_PINS.json", label_pins)
    target_map = {t["episode_id"]: t for t in targets}
    require(
        len(target_map) == len(targets)
        and set(target_map)
        == {
            e["id"] for e in dataset.episodes.values() if e["split"] in ("train", "dev")
        },
        "training labels omit development or include confirmation",
    )
    pairs = []
    for record in records:
        pair = record["pair"]
        for branch in ("without", "with"):
            pair[branch]["score"] = _score(
                record[branch + "_answer"], target_map[record["episode_id"]]
            )
            require(pair[branch]["cost"]["encoding"] == 0, "neural cost in public pair")
        pairs.append(pair)
    _write(output / "public-labeled-pairs.json", pairs)
    label_cost = _micro(time.perf_counter_ns() - label_started)
    fit_started = time.perf_counter_ns()
    head = train_head(
        [p for p in pairs if p["split"] == "train"],
        [p for p in pairs if p["split"] == "dev"],
        splits,
        feature_extractor_sha256=code["document_actor.py"],
        cost_value=COST_VALUE,
    )
    _write(output / "public-head.json", head)
    fit_cost = _micro(time.perf_counter_ns() - fit_started)
    manifest = dict(
        budget=dict(cap=actor.CAP, tariff=dict.fromkeys(PHASES, 1)),
        controller=dict(training_runs=[dict(seed=0)]),
        pins_sha256=sha(pins),
        head_sha256=sha(head),
        training_label_pins_sha256=sha(label_pins),
    )
    _write(output / "DEV_FREEZE.json", manifest)
    rows = []
    for episode in dataset.episodes.values():
        if episode["split"] != "dev":
            continue
        modes = ["public_active", "direct_roi", "ocr_only"]
        random.Random(int(sha(episode["id"])[:16], 16)).shuffle(modes)
        for mode in modes:
            result = actor.execute(collector, episode, "global", mode, manifest, head)
            rows.append(
                dict(
                    episode_id=episode["id"],
                    mode=mode,
                    success=_score(
                        result["trace"]["answer"], target_map[episode["id"]]
                    ),
                    cost=result["spent"],
                    execution_sha256=sha(result),
                )
            )
    _write(output / "DEV_ROWS.json", rows)
    finalization = collector.finalize()
    require(
        code
        == {p.name: sha(p.read_bytes()) for p in Path(__file__).parent.glob("*.py")},
        "source changed during development execution",
    )
    require(
        all(
            not load(collector.output / e["path"])["encoded"]
            and e["accounted_cost"]["encoding"] == 0
            for e in collector.records
        ),
        "public collector executed neural work",
    )
    summary = {}
    for mode in ("public_active", "direct_roi", "ocr_only"):
        selected = [r for r in rows if r["mode"] == mode]
        summary[mode] = dict(
            tasks=len(selected),
            correct=sum(r["success"] for r in selected),
            cost=sum(r["cost"] for r in selected),
        )
    report = dict(
        schema="perc1.public-control-development.v1",
        status="HOLD",
        scientific_qualified=False,
        independent_evaluation=False,
        source_pins_sha256=sha(pins),
        head_sha256=sha(head),
        paired_rows=len(pairs),
        dev=summary,
        observations=len(collector.records),
        encoder_calls=0,
        setup_cost=dict(
            collection=collection_cost,
            label_preparation=label_cost,
            head_fit=fit_cost,
            collector_startup=_micro(collector.index["startup_ns"]),
        ),
        finalization=finalization,
        scope="DEV calibration diagnostics only; no causal comparison to frozen held-out campaign",
        cost_scope="observed online proxy and listed setup components; imports, complete evaluation/bookkeeping, bills and energy are not fully metered",
        provider_billing=None,
        energy_joules=None,
    )
    _write(output / "REPORT.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    run(args.dataset_dir, args.output)


if __name__ == "__main__":
    main()
