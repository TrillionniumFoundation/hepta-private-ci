"""Execute acquired-prefix AV inference with complete local-process receipts.

Policies are ordinary controls over the same frozen content encoder. The
mechanism study separately supplies the analytic/ordinary 2x2 comparison.
"""

import argparse
import json
from pathlib import Path
import resource
import subprocess
import sys
import time

import numpy as np

from .av_probe import load_encoder, predict_prefix
from .process_meter import digest, measured, write_json
from .stream_runtime import FeatureSource, State, checkpoint, create_store, restore, run, step


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = Path(__file__).resolve().parent
MODULE = "experiments.hcsn_causal_execution_v3.stream_study"
POLICIES = {"all": dict(kind="all"),
    "periodic": dict(kind="periodic", period_seconds=.1),
    **{f"confidence_{threshold:g}": dict(kind="confidence", threshold=threshold, minimum_reads=4)
       for threshold in (.6, .75, .9)}}


def local_path(recorded):
    """Relocate archived namespace paths without modifying frozen records."""
    marker = "/experiments/hcsn_causal_execution_v3/"
    text = str(recorded)
    if marker in text:
        return PACKAGE / text.split(marker, 1)[1]
    path = Path(recorded)
    return path if path.is_absolute() else ROOT / path


def freeze(output):
    output.mkdir(parents=True, exist_ok=False)
    sources = ["stream_study.py", "stream_runtime.py", "process_meter.py", "av_probe.py"]
    models = {task: PACKAGE / "results/av_probe" / task / "selected_encoder.npz"
              for task in ("async_av", "av_binding")}
    protocol = dict(schema="hcsn-causal-stream-v3", policies=POLICIES, policy_order=list(POLICIES), tasks=list(models),
        sources={name: digest(PACKAGE / name) for name in sources},
        models={task: dict(path=str(path), sha256=digest(path)) for task, path in models.items()},
        selection="validation accuracy >= read-all and CE <= read-all + .1; minimize encoder calls; declared-order ties",
        mandatory_baseline="read-all using identical frozen encoder and exact observation store",
        validation_ce_tolerance=.1, timing_repeats=3, recovery_after_headers=2,
        recovery="serialize full acquired history and counters; new Python process/model load resumes each episode",
        quality_claim="No advantage claim unless encoder quality and independent noninferiority are established",
        data_status="Previously observed small CREMA-D cohort; follow-up exploration, not fresh actor confirmation",
        payload="Only 16 prepared features, 64 bytes/READ; recompute deltas from accepted history",
        cost_boundary="Local prepared-feature store through prediction/evidence/restart; raw decoding and live network absent",
        unavailable_measurements=["raw media decoding", "live communication", "physical sensor cost", "joule energy"],
        frozen_at_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    write_json(output / "PROTOCOL.json", protocol)


def check_protocol(output):
    plan = json.loads((output / "PROTOCOL.json").read_text())
    for name, expected in plan["sources"].items():
        if digest(PACKAGE / name) != expected:
            raise ValueError(f"Frozen source changed: {name}")
    for model in plan["models"].values():
        if digest(local_path(model["path"])) != model["sha256"]:
            raise ValueError("Frozen common encoder changed")
    return plan


def prepare(output, split):
    from experiments.hcsn_mechanism_content_v2.data import load_data
    from .av_probe import labels_of

    plan = check_protocol(output)
    if split == "test" and not (output / "SELECTION_COMPLETE.json").exists():
        raise PermissionError("Select both policies before current test preparation")
    for task in plan["tasks"]:
        job = dict(task=task, av_directory=str(ROOT / "experiments/hcsn_task_value_v1/results/async_frontend001/data"),
                   av_window_seconds=.1, binding_deadline_seconds=1.5, binding_pair_seed=2026110173)
        data = load_data(job, split, allow_heldout=split == "test")
        labels, rows = labels_of(data), []
        for index in range(len(data["x"])):
            directory = output / "stores" / split / task / f"sample{index:03}"
            receipt = create_store(directory, data["x"][index], data["timestamps"][index], data["valid"][index])
            rows.append(dict(directory=str(directory), sample_id=str(data["ids"][index]),
                actor=str(data["group_ids"][index]), label=int(labels[index]), **receipt))
        write_json(output / "stores" / split / task / "MANIFEST.json",
            dict(rows=rows, source_array_sha256=data["metadata"]["array_sha256"],
                 source_data_sha256=data["metadata"]["source_sha256"]))


def resume_episode(checkpoint_path, model_path, output):
    identity = digest(model_path)
    model = load_encoder(model_path)
    record = json.loads(Path(checkpoint_path).read_text())
    source, state, policy, recovery = restore(checkpoint_path, encoder_identity=identity,
        source_directory=local_path(record["source_directory"]))
    predictor = lambda rows: predict_prefix(model, rows, np.ones(len(rows), bool))
    run(source, state, policy, predictor)
    write_json(output, dict(state=vars(state), payload_reads=source.payload_reads,
                           payload_bytes=source.payload_bytes, recovery=recovery))
    source.close()


def worker(output, task, split, policy_name, destination, recover=False):
    plan = check_protocol(output)
    model_path = str(local_path(plan["models"][task]["path"]))
    model = load_encoder(model_path)
    identity = digest(model_path)
    predictor = lambda rows: predict_prefix(model, rows, np.ones(len(rows), bool))
    policy = plan["policies"][policy_name]
    directory = output / "stores" / split / task
    manifest = json.loads((directory / "MANIFEST.json").read_text())
    destination.mkdir(parents=True, exist_ok=False)
    rows = []
    for index, record in enumerate(manifest["rows"]):
        wall, cpu = time.perf_counter(), time.process_time()
        source = FeatureSource(local_path(record["directory"]))
        state = State(2 if task == "av_binding" else 6)
        recovery_cost = None
        if recover:
            for _ in range(plan["recovery_after_headers"]):
                if not step(source, state, policy, predictor):
                    break
            path = destination / f"sample{index:03}.checkpoint.json"
            serialized = checkpoint(source, state, policy, path, encoder_identity=identity)
            source.close()
            result_path = destination / f"sample{index:03}.resumed.json"
            restart_start = time.perf_counter()
            subprocess.run([sys.executable, "-m", MODULE, "resume", "--checkpoint", str(path),
                            "--model", model_path, "--destination", str(result_path)], check=True)
            recovered = json.loads(result_path.read_text())
            state = State(**recovered["state"])
            reads, byte_count = recovered["payload_reads"], recovered["payload_bytes"]
            recovery_cost = dict(serialization=serialized, restore=recovered["recovery"],
                process_restart_wall_seconds=time.perf_counter() - restart_start,
                model_reload_in_new_process=True)
        else:
            run(source, state, policy, predictor)
            reads, byte_count = source.payload_reads, source.payload_bytes
            source.close()
        if reads != state.encoder_calls or byte_count != reads * 64:
            raise AssertionError("Actual acquisition and encoder counters disagree")
        rows.append(dict(sample_id=record["sample_id"], actor=record["actor"], label=record["label"],
            probability=state.probabilities, encoder_calls=state.encoder_calls, payload_reads=reads,
            logical_payload_bytes=byte_count, trace=state.trace, recovery=recovery_cost,
            episode_wall_seconds=time.perf_counter() - wall,
            parent_episode_cpu_seconds=time.process_time() - cpu,
            encoder_cpu_seconds=state.encode_cpu_seconds, decision_cpu_seconds=state.decision_cpu_seconds,
            acquisition_cpu_seconds=state.acquisition_cpu_seconds,
            prepared_events=record["events"], boundary_solver_calls=0,
            latency_kind="Computed replay wall time; logical timestamps are not slept in real time"))
    probability = np.array([row["probability"] for row in rows])
    labels = np.array([row["label"] for row in rows])
    result = dict(task=task, split=split, policy_name=policy_name, recovered=recover,
        accuracy=float(np.mean(probability.argmax(1) == labels)),
        ce=float(-np.log(np.maximum(probability[np.arange(len(labels)), labels], 1e-15)).mean()),
        examples=len(rows), encoder_calls=sum(row["encoder_calls"] for row in rows),
        logical_payload_bytes=sum(row["logical_payload_bytes"] for row in rows),
        episode_latency_p50_ms=float(np.median([row["episode_wall_seconds"] for row in rows]) * 1000),
        episode_latency_p95_ms=float(np.quantile([row["episode_wall_seconds"] for row in rows], .95) * 1000),
        rows=rows, model_sha256=identity)
    write_json(destination / "RESULT.json", result)


def execute(output, training_python):
    plan = check_protocol(output)
    def call(arguments, name, python=sys.executable):
        return measured([python, "-m", MODULE, *arguments], output / "meter" / (name + ".json"), ROOT)
    call(["prepare", "--output", str(output), "--split", "val"], "prepare_val", training_python)
    selection = {}
    for task in plan["tasks"]:
        candidates = []
        for name in plan["policy_order"]:
            destination = output / "validation" / task / name
            call(["worker", "--output", str(output), "--task", task, "--split", "val",
                  "--policy", name, "--destination", str(destination)], f"validation_{task}_{name}")
            candidates.append(json.loads((destination / "RESULT.json").read_text()))
        baseline = candidates[0]
        eligible = [row for row in candidates if row["accuracy"] >= baseline["accuracy"]
                    and row["ce"] <= baseline["ce"] + plan["validation_ce_tolerance"]]
        best = min(eligible, key=lambda row: row["encoder_calls"])
        selection[task] = dict(policy_name=best["policy_name"], validation_accuracy=best["accuracy"],
            validation_ce=best["ce"], encoder_calls=best["encoder_calls"],
            baseline_accuracy=baseline["accuracy"], baseline_encoder_calls=baseline["encoder_calls"])
    write_json(output / "SELECTION_COMPLETE.json", selection)
    call(["prepare", "--output", str(output), "--split", "test"], "prepare_test", training_python)
    for task in plan["tasks"]:
        selected = selection[task]["policy_name"]
        for repeat in range(plan["timing_repeats"]):
            names = ["all", selected] if repeat % 2 == 0 else [selected, "all"]
            for order, name in enumerate(names):
                tag = f"test_{task}_r{repeat}_o{order}_{name}"
                destination = output / "test" / tag
                call(["worker", "--output", str(output), "--task", task, "--split", "test",
                      "--policy", name, "--destination", str(destination)], tag)
        destination = output / "test" / f"recovery_{task}_{selected}"
        call(["worker", "--output", str(output), "--task", task, "--split", "test", "--recover",
              "--policy", selected, "--destination", str(destination)], f"recovery_{task}_{selected}")
    analyze(output)


def analyze(output, summary_path=None):
    plan = check_protocol(output)
    selection = json.loads((output / "SELECTION_COMPLETE.json").read_text())
    summary = {}
    for task in plan["tasks"]:
        runs = []
        for path in sorted((output / "test").glob(f"test_{task}_*/RESULT.json")):
            record = json.loads(path.read_text())
            record["receipt_name"] = path.parent.name
            runs.append(record)
        baseline = next(row for row in runs if row["policy_name"] == "all")
        selected = next(row for row in runs if row["policy_name"] == selection[task]["policy_name"])
        recovery_path = output / "test" / f"recovery_{task}_{selected['policy_name']}" / "RESULT.json"
        recovered = json.loads(recovery_path.read_text())
        same = all((a["trace"], a["probability"], a["encoder_calls"], a["logical_payload_bytes"]) ==
                   (b["trace"], b["probability"], b["encoder_calls"], b["logical_payload_bytes"])
                   for a, b in zip(selected["rows"], recovered["rows"], strict=True))
        with np.load(PACKAGE / "results/av_probe" / task / "test_normal.npz", allow_pickle=False) as old:
            baseline_error = float(np.max(np.abs(np.array([r["probability"] for r in baseline["rows"]]) - old["probabilities"])))
            equivalent_baseline = baseline_error <= 1e-12
        public = lambda row: {key: value for key, value in row.items() if key not in ("rows", "receipt_name")}
        def aggregate_repeat_costs(reference):
            repeated = [row for row in runs if row["policy_name"] == reference["policy_name"]]
            for row in repeated:
                if [(r["trace"], r["probability"]) for r in row["rows"]] != [(r["trace"], r["probability"]) for r in reference["rows"]]:
                    raise AssertionError("Repeated execution changed actions or predictions")
            times = [r["episode_wall_seconds"] for row in repeated for r in row["rows"]]
            receipts = [json.loads((output / "meter" / (row["receipt_name"] + ".json")).read_text()) for row in repeated]
            result = public(reference)
            result.update(timing_repeats=len(repeated),
                episode_latency_p50_ms=float(np.median(times) * 1000),
                episode_latency_p95_ms=float(np.quantile(times, .95) * 1000),
                repeat_episode_p50_ms=[r["episode_latency_p50_ms"] for r in repeated],
                repeat_worker_cpu_seconds=[r["cpu_seconds"] for r in receipts],
                median_worker_cpu_seconds=float(np.median([r["cpu_seconds"] for r in receipts])),
                median_worker_wall_seconds=float(np.median([r["wall_seconds"] for r in receipts])),
                peak_individual_worker_rss_bytes=max(r["peak_rss_bytes"] for r in receipts),
                timing_note="Repeated measurements of identical examples, not independent quality observations")
            return result
        paired = []
        for base, chosen in zip(baseline["rows"], selected["rows"], strict=True):
            paired.append(dict(sample_id=base["sample_id"], actor=base["actor"],
                accuracy_difference=int(np.argmax(chosen["probability"]) == base["label"]) -
                    int(np.argmax(base["probability"]) == base["label"]),
                encoder_calls_saved=base["encoder_calls"] - chosen["encoder_calls"]))
        summary[task] = dict(baseline=aggregate_repeat_costs(baseline), selected=aggregate_repeat_costs(selected),
            recovery=public(recovered), recovery_matches_all_actions_probabilities_counts=same,
            read_all_matches_frozen_full_input_probe_within_1e12=equivalent_baseline,
            read_all_max_probability_difference=baseline_error, paired=paired,
            quality_advantage_established=False,
            limitation="Small reused actors and weak frontend; descriptive execution result only")
        if not same or not equivalent_baseline:
            raise AssertionError("Runtime equivalence or recovery failed")
    meters = {p.stem: json.loads(p.read_text()) for p in (output / "meter").glob("*.json")}
    write_json(summary_path or output / "SUMMARY.json", dict(tasks=summary, process_receipts=meters,
        metered_worker_cpu_seconds=sum(row["cpu_seconds"] for row in meters.values()),
        metered_worker_wall_seconds=sum(row["wall_seconds"] for row in meters.values()),
        maximum_individual_worker_rss_bytes=max(row["peak_rss_bytes"] for row in meters.values()),
        unmeasured=plan["unavailable_measurements"], energy_joules=None))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["freeze", "execute", "prepare", "worker", "resume", "analyze"])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--split", choices=["val", "test"])
    parser.add_argument("--task", choices=["async_av", "av_binding"])
    parser.add_argument("--policy")
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--recover", action="store_true")
    parser.add_argument("--training-python", default=sys.executable)
    args = parser.parse_args()
    if args.action == "freeze":
        freeze(args.output.resolve())
    elif args.action == "execute":
        execute(args.output.resolve(), args.training_python)
    elif args.action == "prepare":
        prepare(args.output.resolve(), args.split)
    elif args.action == "worker":
        worker(args.output.resolve(), args.task, args.split, args.policy, args.destination, args.recover)
    elif args.action == "resume":
        resume_episode(args.checkpoint, args.model, args.destination)
    else:
        analyze(args.output.resolve(), args.destination)


if __name__ == "__main__":
    main()
