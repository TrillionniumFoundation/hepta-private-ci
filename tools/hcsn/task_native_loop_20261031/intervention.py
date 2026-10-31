"""DEV-only frozen trained-boundary intervention; never selects primary models."""
import argparse
import copy
from datetime import datetime, timezone
import json
import math
from pathlib import Path, PurePosixPath
import resource
import struct
import tarfile
import time

from .experiment import archive_chunks, augment_public, native_process, verify_build, verify_training
from .train import HERE, announce
from ..task_value_factorial_20261030.task import save, sha

VARIANTS = ("baseline", "boundary_minus3", "boundary_plus3")
CHANGES = {"baseline": None, "boundary_minus3": -3.0, "boundary_plus3": 3.0}
EPSILON = 1e-10


def unpack_validation(archive, work, seed, count):
    """Extract regular VAL public/packet files; leave label bytes in the archive."""
    expected = {f"validation_seed{seed}_{i:04d}" for i in range(count)}
    files, labels, seen = {}, {}, set()
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            path = PurePosixPath(member.name)
            if not path.parts or path.parts[0] not in expected:
                continue
            if path.is_absolute() or len(path.parts) != 2 or ".." in path.parts or not member.isfile():
                raise ValueError(("Unsafe VAL archive member", member.name))
            if member.name in seen or member.size > 1_000_000:
                raise ValueError(("Duplicate or oversized member", member.name))
            seen.add(member.name)
            if path.name == "evaluator_labels.json":
                labels[path.parts[0]] = member.name
                continue
            if path.name != "public.json" and not path.name.startswith("job"):
                raise ValueError(("Unexpected VAL input", member.name))
            destination = work / "inputs" / member.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write(tar.extractfile(member).read())
            files[member.name] = sha(destination)
    actual = {p.parent.name for p in (work / "inputs").glob("*/public.json")}
    if actual != expected or set(labels) != expected:
        raise ValueError("VAL archive does not contain exactly the declared sessions")
    return sorted(expected), labels, files


def checked_run(raw, snapshot, expected):
    native = raw.get("payload")
    if raw["returncode"] != 0 or not native or native.get("schema") != "hcsn.task.native.run.v1":
        raise ValueError("Native process did not return a successful receipt")
    for key, value in expected.items():
        if native.get(key) != value:
            raise ValueError(("Native identity mismatch", key))
    if native["start"]["sequence"] != 0 or native["start"]["task"]["history"]:
        raise ValueError("Each intervention must use a fresh owner")
    if not native["end"]["task"]["terminal"]:
        raise ValueError("Native run incomplete; labels remain unopened")
    if sha(snapshot) != native["acknowledged_sha256"] or json.loads(snapshot.read_text()) != native["end"]:
        raise ValueError("Persisted acknowledged state differs from native receipt")
    if native["end"]["task"]["counts"]["failed_read_attempts"]:
        raise ValueError("Failed READ retained as failed diagnostic, never replaced")
    return native


def outcome(native, labels):
    task = native["end"]["task"]
    if not task["terminal"]:
        raise ValueError("Nonterminal outcome cannot be scored")
    correct = sum(answer["prediction"] == labels[answer["job"]] for answer in task["answers"])
    reward = 2 * correct - len(task["answers"])
    return dict(reward=reward, utility=reward-task["charged_cost"], charged_cost=task["charged_cost"],
                query_cost=task["query_cost"], latency_cost=task["latency_cost"],
                completed_jobs=len(task["answers"]), correct_jobs=correct,
                labels_accessed_after_all_three_terminal=True)


def read_schedule(native):
    return [dict(sequence=r["sequence"], job=r["before"]["job"], tick=r["before"]["tick"],
                 elapsed_micros=r["before"]["elapsed_micros"], duration=r["event"]["duration"])
            for r in native["receipts"] if r["action"] == "READ"]


def horizon_count(receipt):
    value = receipt["cell_features"][2]
    return value / (1-value)


def compare(base, changed, base_score, changed_score):
    if base["start"]["task"] != changed["start"]["task"]:
        raise ValueError("Intervention initial public task state differs")
    prefix, first = [], None
    for left, right in zip(base["receipts"], changed["receipts"]):
        if left["before"] != right["before"] or left["public_features"] != right["public_features"]:
            raise ValueError("Task prefix changed before the first native action disagreement")
        delta = max(abs(a-b) for a, b in zip(left["cell_features"], right["cell_features"]))
        entry = dict(sequence=left["sequence"], task={k: left["before"][k] for k in
                     ("job", "tick", "budget", "posterior", "elapsed_micros")},
                     baseline_action=left["action"], intervention_action=right["action"],
                     baseline_cell5=left["cell_features"], intervention_cell5=right["cell_features"],
                     baseline_q=left["q"], intervention_q=right["q"], max_cell_feature_delta=delta,
                     baseline_expected_count=horizon_count(left), intervention_expected_count=horizon_count(right),
                     max_q_delta=max(abs(a-b) for a, b in zip(left["q"], right["q"])))
        prefix.append(entry)
        if left["action"] != right["action"]:
            first = entry
            break
    if first is None and len(base["receipts"]) != len(changed["receipts"]):
        raise ValueError("Different trace lengths without an earlier action disagreement")
    a, b = read_schedule(base), read_schedule(changed)
    latent = max((r["max_cell_feature_delta"] for r in prefix), default=0.0)
    return dict(first_disagreement=first, same_prefix_diagnostics=prefix,
                actions_changed=first is not None, reads_changed=len(a) != len(b), read_schedule_changed=a != b,
                baseline_read_schedule=a, intervention_read_schedule=b,
                read_delta=len(b)-len(a), utility_delta=changed_score["utility"]-base_score["utility"],
                latent_changed=latent > EPSILON, latent_only=latent > EPSILON and first is None,
                max_same_prefix_cell_feature_delta=latent,
                max_same_prefix_expected_count_delta=max((abs(r["baseline_expected_count"]-r["intervention_expected_count"]) for r in prefix), default=0.0),
                max_same_prefix_q_delta=max((r["max_q_delta"] for r in prefix), default=0.0))


def summarize(rows):
    reports = {}
    for variant in VARIANTS[1:]:
        selected = [r["comparisons"][variant] for r in rows if variant in r["comparisons"]]
        reports[variant] = dict(paired_cases=len(selected),
            **{key+"_cases": sum(r[key] for r in selected) for key in
               ("actions_changed", "reads_changed", "read_schedule_changed", "latent_changed", "latent_only")},
            total_read_delta=sum(r["read_delta"] for r in selected),
            mean_utility_delta=sum(r["utility_delta"] for r in selected)/len(selected) if selected else None,
            **{key: max((r[key] for r in selected), default=None) for key in
               ("max_same_prefix_cell_feature_delta", "max_same_prefix_expected_count_delta", "max_same_prefix_q_delta")})
    return reports


def run(args):
    wall, cpu = time.perf_counter(), time.process_time()
    child_start = resource.getrusage(resource.RUSAGE_CHILDREN)
    training, binary, content, out = (p.resolve() for p in (args.training, args.binary, args.content_model, args.out))
    freeze, protocol = verify_training(training, args.training_freeze_sha)
    build = verify_build(binary, args.build_report.resolve())
    if len(protocol["seeds"]) != 5 or protocol["validation_sessions"] != 16:
        raise ValueError("Diagnostic was declared for five fits and sixteen VAL sessions per fit")
    out.mkdir(parents=True, exist_ok=False)
    sources = {str(p.relative_to(HERE.parent)): sha(p) for p in
               (Path(__file__).resolve(), HERE / "experiment.py", HERE / "train.py",
                HERE.parent / "task_value_factorial_20261030/task.py")}
    artifacts, policies = {}, {}
    for seed in protocol["seeds"]:
        original_path = training / "models" / f"seed{seed}_analytic_value.json"
        original = json.loads(original_path.read_text())
        if (original["family"], original["controller"]) != ("distribution", "value"):
            raise ValueError("Only the frozen trained analytic value policy is admissible")
        for variant, value in CHANGES.items():
            derived = copy.deepcopy(original)
            if value is not None:
                derived["parameters"][3] = value
            unchanged = copy.deepcopy(derived)
            unchanged["parameters"][3] = original["parameters"][3]
            if unchanged != original:
                raise ValueError("Intervention changed a field besides boundary raw parameter")
            path = out / "models" / f"seed{seed}_{variant}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            if variant == "baseline":
                with path.open("xb") as stream:
                    stream.write(original_path.read_bytes())
            else:
                save(path, derived)
            policies[(seed, variant)] = (path, derived)
            artifacts[str(path.relative_to(out))] = dict(sha256=sha(path), original_sha256=sha(original_path),
                parameter_index=3, raw_boundary=derived["parameters"][3],
                physical_boundary=0.8+0.4/(1+math.exp(-derived["parameters"][3])), only_boundary_changed=True)
    save(out / "PLAN.json", dict(schema="hcsn.trained-boundary-intervention.plan.v1",
        created_at=datetime.now(timezone.utc).isoformat(), scope="DEV secondary mechanism diagnostic; not heldout confirmation or efficacy selection",
        seeds=protocol["seeds"], sessions_per_seed=16, variants=CHANGES, planned_native_runs=240,
        source_sha256=sources, models=artifacts, training_freeze_sha256=args.training_freeze_sha,
        original_development_archives=freeze["development_archives"], binary_sha256=sha(binary),
        build_report_sha256=sha(args.build_report), native_source_digest=build["source_digest"], content_model_sha256=sha(content),
        boundary_formula="0.8 + 0.4*sigmoid(theta[3]); finite five-state regenerative CTMC",
        first_disagreement="Compare only identical public task prefixes; stop comparison at first autonomous action mismatch",
        tolerance=EPSILON, run_order="Rotate three variants by (seed_index + session_index) modulo 3",
        labels="Do not extract evaluator_labels; parse them from frozen source archive only after all three native trajectories terminate",
        failure_rule="Keep all failed runs, no replacement or parameter search; failed pairs excluded with explicit count",
        read_timing="Public task tick and elapsed_micros; content_nanos measures call duration, not a wall-clock invocation timestamp",
        no_primary_updates=True, production_activation=False))
    rows, archives, result_files, native_runs, failed_runs = [], {}, {}, 0, 0
    for seed_index, seed in enumerate(protocol["seeds"]):
        work = out / "_work" / f"seed{seed}"
        archive = training / "data" / f"development_seed{seed}.tar.gz"
        sessions, labels_members, inputs = unpack_validation(archive, work, seed, 16)
        seed_rows, raw_files = [], {}
        for index, session in enumerate(sessions):
            folder = work / "inputs" / session
            original_public = json.loads((folder / "public.json").read_text())
            public = augment_public(folder, protocol)
            augmented = json.loads(public.read_text())
            if {k: augmented[k] for k in original_public} != original_public:
                raise ValueError("Public metadata changed beyond generation-side augmentation")
            order = VARIANTS[(seed_index+index) % 3:] + VARIANTS[:(seed_index+index) % 3]
            raw_runs, valid, errors = {}, {}, {}
            for variant in order:
                path, policy = policies[(seed, variant)]
                snapshot = work / "owners" / session / variant / "owner.json"
                raw = native_process(binary, public, content, path, policy, snapshot)
                native_runs += 1
                try:
                    valid[variant] = checked_run(raw, snapshot, dict(source_digest=build["source_digest"],
                        public_sha256=sha(public), policy_sha256=sha(path), content_model_sha256=sha(content),
                        family="distribution", controller="value", native_neuron_runtime=True,
                        production_activation=False, authority="DENY_ALL"))
                except Exception as exc:
                    errors[variant] = dict(type=type(exc).__name__, message=str(exc))
                    failed_runs += 1
                receipt_path = work / "receipts" / f"{session}_{variant}.json"
                save(receipt_path, raw)
                raw_files[f"{session}/{variant}"] = str(receipt_path.relative_to(work))
                raw_runs[variant] = raw
            row = dict(seed=seed, session=session, public_sha256=sha(public), order=order, errors=errors,
                       scores={}, comparisons={}, native={})
            if len(valid) == 3:
                with tarfile.open(archive, "r:gz") as tar:
                    labels = json.loads(tar.extractfile(labels_members[session]).read())["labels"]
                row["scores"] = {variant: outcome(native, labels) for variant, native in valid.items()}
                row["comparisons"] = {variant: compare(valid["baseline"], valid[variant],
                    row["scores"]["baseline"], row["scores"][variant]) for variant in VARIANTS[1:]}
            for variant, raw in raw_runs.items():
                native = valid.get(variant)
                row["native"][variant] = dict(receipt=raw_files[f"{session}/{variant}"],
                    **{key: raw[key] for key in ("child_cpu_seconds", "parent_cpu_seconds", "runtime_cpu_seconds", "runtime_wall_seconds")},
                    counts=native["end"]["task"]["counts"] if native else None,
                    load_nanos=native["load_nanos"] if native else None,
                    artifact_load_nanos=native["artifact_load_nanos"] if native else None,
                    stage_costs_nanos={key: sum(r["stage_costs"][key] for r in native["receipts"])
                                      for key in native["receipts"][0]["stage_costs"]} if native else None,
                    final_expected_latent_events=struct.unpack(">d", bytes.fromhex(native["end"]["cell"]["event_count_bits"]))[0] if native else None)
            rows.append(row)
            seed_rows.append(row)
        seed_archives, members = archive_chunks(out, work, f"runs/seed{seed}")
        archives.update(seed_archives)
        for row in seed_rows:
            for item in row["native"].values():
                item["receipt"] = members[item["receipt"]]
        result_path = out / "results" / f"seed{seed}.json"
        save(result_path, dict(rows=seed_rows, original_input_sha256=inputs,
                              archive_members=members, summary=summarize(seed_rows)))
        result_files[str(result_path.relative_to(out))] = sha(result_path)
        announce("trained_boundary_intervention_seed", seed=seed, summary=summarize(seed_rows))
    verify_training(training, args.training_freeze_sha)
    verify_build(binary, args.build_report.resolve())
    if any(sha(HERE.parent / path) != digest for path, digest in sources.items()):
        raise ValueError("Intervention runner source changed during execution")
    if any(sha(out / path) != item["sha256"] for path, item in artifacts.items()):
        raise ValueError("Intervention artifact changed during execution")
    child_end = resource.getrusage(resource.RUSAGE_CHILDREN)
    save(out / "SUMMARY.json", dict(schema="hcsn.trained-boundary-intervention.summary.v1",
        scope="DEV secondary mechanism diagnostic only; neither heldout evidence nor primary model selection",
        plan_sha256=sha(out / "PLAN.json"), native_runs=native_runs, planned_native_runs=240, failed_runs=failed_runs,
        paired_sessions=sum(len(r["comparisons"]) == 2 for r in rows), summary=summarize(rows),
        by_fit={str(seed): summarize([r for r in rows if r["seed"] == seed]) for seed in protocol["seeds"]},
        result_files=result_files, archives=archives,
        wall_seconds=time.perf_counter()-wall, parent_cpu_seconds=time.process_time()-cpu,
        child_cpu_seconds=child_end.ru_utime+child_end.ru_stime-child_start.ru_utime-child_start.ru_stime,
        native_child_cpu_seconds=sum(v["child_cpu_seconds"] for r in rows for v in r["native"].values()),
        cost_scope="Outer parent+child CPU includes extraction, all native startup/actions, scoring, receipt writes and archive checks. Per-run costs are nested, not additive to this campaign total.",
        primary_model_update=False, energy_joules=None, production_activation=False))
    announce("trained_boundary_intervention_complete", output=str(out), native_runs=native_runs, failed_runs=failed_runs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training", type=Path, required=True)
    parser.add_argument("--training-freeze-sha", required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--build-report", type=Path, required=True)
    parser.add_argument("--content-model", type=Path, default=HERE.parent / "round9_20261031/native/fixtures/fullhx.json")
    parser.add_argument("--out", type=Path, required=True)
    run(parser.parse_args())
