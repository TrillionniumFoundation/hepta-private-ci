"""Actual stochastic fits on retained TRAIN/DEV observations, never confirmation.

Global/dense fits use previously executed/recomputed features. Only the public
head is executed on live OCR here. Reused DEV is calibration, not a new test.
"""

import argparse
from pathlib import Path
import random

from perc1 import acquisition, document_actor as actor
from perc1.document_pilot import _score
from perc1.mlp_head import train_head
from perc1.producer import _json
from perc1.schema import Dataset, PHASES, canonical, require, sha

SEEDS = (1101, 2202, 3303)


def _read(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(128 * 1024 * 1024 + 1)
    require(len(raw) <= 128 * 1024 * 1024, "bounded JSON input required")
    return _json(raw), sha(raw)


def _write(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value) + b"\n")


def run(input_root, output_dir):
    root, output = Path(input_root).resolve(), Path(output_dir)
    output.mkdir(parents=True, mode=0o700)
    inputs, input_hash = _read(root / "inputs.json")
    require(
        inputs["confirmation_execution_allowed"] is False
        and set(inputs["pairs"]) == {"global", "dense", "public"},
        "development inputs required",
    )
    dataset_value, dataset_file_hash = _read(root / "dataset.json")
    dataset = Dataset(dataset_value, root)
    splits = {
        s: sorted({e["group"] for e in dataset.episodes.values() if e["split"] == s})
        for s in ("train", "dev", "confirmation")
    }
    code_paths = [
        Path(__file__),
        *sorted((Path(__file__).parent / "perc1").glob("*.py")),
    ]
    code = {str(p.resolve()): sha(p.read_bytes()) for p in code_paths}
    _write(
        output / "FREEZE.json",
        dict(
            inputs_sha256=input_hash,
            dataset_file_sha256=dataset_file_hash,
            code=code,
            seeds=list(SEEDS),
            steps=200,
            hidden=8,
            batch=32,
            learning_rate=0.02,
            momentum=0.9,
            cost_value=0.5 / 1_000_000,
            independent_evaluation=False,
        ),
    )
    heads, summaries = {}, []
    for condition, spec in inputs["pairs"].items():
        path = (root / spec["path"]).resolve()
        require(path.is_relative_to(root), "pair path escapes input root")
        pairs, file_hash = _read(path)
        require(
            file_hash == spec["sha256"]
            and all(p["split"] in ("train", "dev") for p in pairs),
            "pairs changed or include confirmation",
        )
        train, dev = (
            [p for p in pairs if p["split"] == split] for split in ("train", "dev")
        )
        heads[condition] = []
        for seed in SEEDS:
            head = train_head(
                train,
                dev,
                splits,
                feature_extractor_sha256=spec["feature_extractor_sha256"],
                seed=seed,
                steps=200,
                hidden=8,
                batch=32,
                learning_rate=0.02,
                momentum=0.9,
                threshold=0.0,
                cost_value=0.5 / 1_000_000,
            )
            name = f"{condition}-{seed}-head.json"
            acquisition.save_head(output / name, head)
            require(
                acquisition.load_head(output / name, sha(head)) == head,
                "head persistence changed",
            )
            receipt = head["training_receipt"]
            predictions = [acquisition.predict(head, p["features"]) for p in dev]
            _write(output / f"{condition}-{seed}-dev-predictions.json", predictions)
            summaries.append(
                dict(
                    condition=condition,
                    seed=seed,
                    head_sha256=sha(head),
                    initial_parameters_sha256=receipt["initial_parameters_sha256"],
                    final_parameters_sha256=receipt["final_parameters_sha256"],
                    order_sha256=receipt["order_sha256"],
                    trace_sha256=receipt["trace_sha256"],
                    steps=receipt["steps"],
                    train_count=len(train),
                    dev_count=len(dev),
                    parameters_changed=receipt["initial_parameters_sha256"]
                    != receipt["final_parameters_sha256"],
                    elapsed_ns=receipt["elapsed_ns"],
                    cpu_ns=receipt["cpu_ns"],
                )
            )
            heads[condition].append((seed, head))
        for key in (
            "initial_parameters_sha256",
            "order_sha256",
            "final_parameters_sha256",
        ):
            require(
                len({s[key] for s in summaries if s["condition"] == condition})
                == len(SEEDS),
                "training seeds did not produce distinct trajectories",
            )
    require(
        all(
            head["training_receipt"]["feature_extractor_sha256"]
            == sha(Path(actor.__file__).read_bytes())
            for _, head in heads["public"]
        ),
        "public feature extractor differs from training pin",
    )
    targets, targets_hash = _read(root / "training-targets.json")
    target_map = {t["episode_id"]: t for t in targets}
    require(
        len(target_map) == len(targets)
        and set(target_map)
        == {
            e["id"] for e in dataset.episodes.values() if e["split"] in ("train", "dev")
        },
        "development label scope changed",
    )
    _write(output / "DEV_LABEL_PIN.json", dict(file_sha256=targets_hash))
    collector = actor.Collector(dataset, None, None, output / "collector")
    rows = []
    for seed, head in heads["public"]:
        manifest = dict(
            budget=dict(cap=actor.CAP, tariff=dict.fromkeys(PHASES, 1)),
            controller=dict(training_runs=[dict(seed=seed)]),
            head_sha256=sha(head),
        )
        _write(output / f"public-{seed}-DEV_FREEZE.json", manifest)
        for episode in dataset.episodes.values():
            if episode["split"] != "dev":
                continue
            modes = ["public_active", "direct_roi"]
            random.Random(int(sha([seed, episode["id"]])[:16], 16)).shuffle(modes)
            for mode in modes:
                result = actor.execute(
                    collector, episode, "global", mode, manifest, head
                )
                rows.append(
                    dict(
                        seed=seed,
                        episode_id=episode["id"],
                        mode=mode,
                        correct=_score(
                            result["trace"]["answer"], target_map[episode["id"]]
                        ),
                        cost=result["spent"],
                        execution_sha256=sha(result),
                    )
                )
    _write(output / "DEV_ROWS.json", rows)
    finalization = collector.finalize()
    require(
        code == {str(p.resolve()): sha(p.read_bytes()) for p in code_paths},
        "source changed during campaign",
    )
    _write(output / "FITS.json", summaries)
    report = dict(
        schema="perc1.stochastic-development.v1",
        status="HOLD",
        scientific_qualified=False,
        independent_evaluation=False,
        source_reused=True,
        fits=len(summaries),
        optimizer_steps=sum(s["steps"] for s in summaries),
        neural_policy_evaluation_performed=False,
        public_policy_evaluation="DEV calibration diagnostics only",
        actual_encoder_calls=0,
        observations=len(collector.records),
        dev_executions=len(rows),
        by_seed={
            str(seed): {
                mode: dict(
                    tasks=len(
                        selected := [
                            r for r in rows if r["seed"] == seed and r["mode"] == mode
                        ]
                    ),
                    correct=sum(r["correct"] for r in selected),
                    cost=sum(r["cost"] for r in selected),
                )
                for mode in ("public_active", "direct_roi")
            }
            for seed in SEEDS
        },
        finalization=finalization,
        provider_billing=None,
        energy_joules=None,
        scope="Actual seeded SGD repeats and public-head OCR execution on known TRAIN/DEV; no fresh four-family qualification or production source authority",
    )
    _write(output / "REPORT.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    run(args.input_root, args.output)


if __name__ == "__main__":
    main()
