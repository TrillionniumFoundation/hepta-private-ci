"""Frozen native heldout confirmation with terminal-only independent scoring.

One fresh native process completes each trial using --steps 32. The host supplies
no action, posterior, observation or packet choice. NumPy policy/content replay
happens only after that native process has completed, and is evaluator work.
"""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import resource
import shutil
import subprocess
import tarfile
import time

import numpy as np

from ..task_value_factorial_20261030.dataset import state_record
from ..task_value_factorial_20261030.task import (
    ACTIONS, Bellman, ContentAdapter, Owner, build_cohort, save, score_terminal, sha)
from .model import infer
from .reference import play_episode
from .statistics import analyze
from .train import HERE, announce, packed, source_identity

REPO = HERE.parents[2]
MAX_BLOB_BYTES = 480000


def archive_chunks(out, work, prefix):
    """Bounded archives preserve each original byte before retiring this workdir."""
    if work.parent != out / "_work":
        raise ValueError("Only this run's direct _work children may be retired")
    files = sorted(p for p in work.rglob("*") if p.is_file())
    if any(p.is_symlink() for p in work.rglob("*")):
        raise ValueError("Generated evidence must not contain symlinks")
    archives, members = {}, {}

    def emit(group):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as tar:
            for path in group:
                data = path.read_bytes()
                info = tarfile.TarInfo(str(path.relative_to(work)))
                info.size, info.mode, info.mtime = len(data), 0o600, 0
                tar.addfile(info, io.BytesIO(data))
        data = gzip.compress(buffer.getvalue(), mtime=0)
        if len(data) > MAX_BLOB_BYTES:
            if len(group) == 1:
                raise ValueError(("One compressed evidence member exceeds blob budget", str(group[0])))
            middle = len(group)//2
            emit(group[:middle])
            emit(group[middle:])
            return
        path = out / f"{prefix}_part{len(archives):04d}.tar.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(data)
        relative = str(path.relative_to(out))
        archives[relative] = sha(path)
        with tarfile.open(path, "r:gz") as tar:
            for member in tar.getmembers():
                digest = hashlib.sha256(tar.extractfile(member).read()).hexdigest()
                if digest != sha(work/member.name):
                    raise ValueError(("Archive readback changed bytes", member.name))
                members[member.name] = dict(archive=relative, member=member.name, sha256=digest)

    pending, size = [], 0
    for path in files:
        pending.append(path)
        size += path.stat().st_size
        if size >= 4000000:
            emit(pending)
            pending, size = [], 0
    if pending:
        emit(pending)
    if len(members) != len(files):
        raise ValueError("Incomplete archive inventory")
    shutil.rmtree(work)
    return archives, members


def verify_training(training, expected):
    if sha(training / "FREEZE.json") != expected:
        raise ValueError("Training FREEZE file SHA does not match the supplied immutable identity")
    freeze = json.loads((training / "FREEZE.json").read_text())
    protocol = json.loads((training / "PROTOCOL.json").read_text())
    if source_identity() != freeze["source"] or sha(training / "PROTOCOL.json") != freeze["protocol_sha256"]:
        raise ValueError("Training source or protocol differs from the frozen version")
    if protocol != json.loads((HERE / "PROTOCOL.json").read_text()) or freeze["heldout_generated"]:
        raise ValueError("Protocol/heldout chronology mismatch")
    for group in ("policies", "training", "development_archives"):
        for path, entry in freeze[group].items():
            digest = entry["sha256"] if isinstance(entry, dict) else entry
            if sha(training / path) != digest:
                raise ValueError(("Frozen training artifact changed", path))
    return freeze, protocol


def verify_build(binary, report_path):
    report = json.loads(report_path.read_text())
    if not report["success"] or sha(binary) != report["binary_sha256"]:
        raise ValueError("Native binary does not match a successful source build")
    for path, digest in report["source_sha256"].items():
        if path.startswith("cached-dependency/"):
            name = path.split("/", 1)[1]
            directory = binary.parents[2] / "vendor" / name
            inventory = {str(p.relative_to(directory)): sha(p) for p in sorted(directory.rglob("*")) if p.is_file()}
            actual = hashlib.sha256(json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            if inventory != report["dependency_sources"][name]["source_files"]:
                raise ValueError(("Pinned cached dependency bytes changed", name))
        else:
            actual = sha(REPO / path)
        if actual != digest:
            raise ValueError(("Native source changed after build", path))
    return report


def augment_public(folder, protocol):
    public = json.loads((folder / "public.json").read_text())
    public["multiplier"], public["latency_price"] = protocol["multiplier"], protocol["latency_price"]
    public["packet_sha256"] = [[sha(folder / name) for name in row] for row in public["packets"]]
    path = folder / "native_public.json"
    save(path, public)
    return path


def native_process(binary, public, content, policy_path, policy, snapshot):
    """Measure process execution before any labels, oracle or replay are opened."""
    argv = [str(binary), "--public", str(public), "--content-model", str(content),
            "--policy", str(policy_path), "--family", policy["family"],
            "--controller", policy["controller"], "--steps", "32", "--snapshot", str(snapshot)]
    snapshot.parent.mkdir(parents=True, exist_ok=False)
    wall, parent_cpu = time.perf_counter(), time.process_time()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    payload, error = None, None
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        stdout, stderr, returncode = result.stdout, result.stderr, result.returncode
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            error = dict(type=type(exc).__name__, message=str(exc))
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout or ""
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr or ""
        returncode, error = None, dict(type="TimeoutExpired", seconds=30)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    child_cpu = after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime
    parent_cpu = time.process_time()-parent_cpu
    return dict(command=argv, returncode=returncode, stdout=stdout, stderr=stderr, payload=payload, error=error,
                child_cpu_seconds=child_cpu, parent_cpu_seconds=parent_cpu,
                runtime_cpu_seconds=child_cpu+parent_cpu, runtime_wall_seconds=time.perf_counter()-wall)


def independent_evaluation(raw, folder, policy, adapter, oracle, expected):
    """Replay actual completed native effects independently; no rerun selection."""
    native = raw["payload"]
    if raw["returncode"] != 0 or native is None or native.get("schema") != "hcsn.task.native.run.v1":
        raise ValueError("Native process did not return a successful run receipt")
    for name, value in expected.items():
        if native.get(name) != value:
            raise ValueError(("Native identity mismatch", name))
    if not native["end"]["task"]["terminal"]:
        raise ValueError("Native run ended without a terminal task; evaluator labels remain unopened")
    owner = Owner(folder, adapter, policy["confusion"], policy["multiplier"], policy["latency_price"])
    evaluation_policy = dict(policy, controller="fixed") if policy["controller"] == "direct_fixed" else policy
    history, regret, qerr, ferr, content_mismatches, errors = [], 0., 0., 0., 0, []
    details = []
    for receipt in native["receipts"]:
        record = state_record(owner, history)
        prediction = infer(evaluation_policy, record)
        if prediction["action"] != receipt["action"]:
            errors.append(dict(kind="action", sequence=receipt["sequence"], expected=prediction["action"], actual=receipt["action"]))
        if not np.allclose(record["features"], receipt["public_features"], rtol=0., atol=5e-10):
            errors.append(dict(kind="public_features", sequence=receipt["sequence"]))
        if prediction["q"] is not None:
            qerr = max(qerr, float(np.max(np.abs(np.asarray(prediction["q"])-receipt["q"]))))
            ferr = max(ferr, float(np.max(np.abs(np.asarray(prediction["raw_features"])[62:]-receipt["cell_features"]))))
        elif receipt["q"] is not None or receipt["cell_features"] is not None:
            errors.append(dict(kind="fixed_ran_unused_critic", sequence=receipt["sequence"]))
        target = np.asarray(oracle.q(owner.job, owner.tick, owner.budget, owner.posterior))
        index = ACTIONS.index(receipt["action"])
        if not np.isfinite(target[index]):
            raise ValueError("Native action is illegal under the independent task contract")
        step_regret = float(max(target)-target[index])
        regret += step_regret
        event = owner.act(receipt["action"])
        if event.get("observation") != receipt["event"]["observation"]:
            content_mismatches += 1
        for key in ("job", "tick", "budget", "posterior", "reads_in_job", "charged_cost", "query_cost", "latency_cost", "task_elapsed", "terminal"):
            a, b = getattr(owner, key), receipt["after"][key]
            if (abs(a-b) > 5e-10) if isinstance(a, float) else (a != b):
                errors.append(dict(kind="task_successor", field=key, sequence=receipt["sequence"], expected=a, actual=b))
        details.append(dict(sequence=receipt["sequence"], fitted_law_q=np.where(record["feasible"], target, 0.).tolist(),
                            fitted_law_regret=step_regret, predicted_action=prediction["action"]))
        history.append(dict(driver=record["driver"], duration=event["duration"], reset=receipt["action"] == "FIRE"))
    if qerr > 1e-7 or ferr > 1e-7 or content_mismatches:
        errors.append(dict(kind="numerical_or_content_parity", q_error=qerr, feature_error=ferr,
                           content_observation_mismatches=content_mismatches))
    if not owner.terminal:
        raise ValueError("Independent replay disagrees with native termination")
    # Score the native answers, rather than substituting the replay's answers if
    # a parity check has failed. Both terminal flags precede the first label read.
    final = native["end"]["task"]
    labels = json.loads((folder / "evaluator_labels.json").read_text())["labels"]
    correct = sum(answer["prediction"] == labels[answer["job"]] for answer in final["answers"])
    reward = 2*correct-len(final["answers"])
    score = dict(utility=reward-final["charged_cost"], reward=reward,
                 charged_cost=final["charged_cost"], query_cost=final["query_cost"],
                 latency_cost=final["latency_cost"], completed_jobs=len(final["answers"]),
                 correct_jobs=correct, label_access_after_terminal=True)
    outcome_rows, remaining = [], 0.
    for receipt, detail in reversed(list(zip(native["receipts"], details))):
        before, after, event = receipt["before"], receipt["after"], receipt["event"]
        realized_reward = (1. if int(before["posterior"] >= .5) == labels[before["job"]] else -1.) if receipt["action"] == "FIRE" else 0.
        immediate = realized_reward-event["query_charge"]-event["latency_charge"]
        remaining += immediate
        next_value = 0. if after["terminal"] else oracle.value(after["job"], after["tick"], after["budget"], after["posterior"])
        index = ACTIONS.index(receipt["action"])
        teacher_q = detail["fitted_law_q"][index]
        critic_q = receipt["q"][index] if receipt["q"] is not None else None
        outcome_rows.append(dict(sequence=receipt["sequence"], action=receipt["action"],
            realized_reward=realized_reward, query_charge=event["query_charge"], latency_charge=event["latency_charge"],
            immediate_utility=immediate, realized_policy_return=remaining, fitted_law_q=teacher_q,
            realized_oracle_bootstrap_target=immediate+next_value,
            fitted_law_td_residual=immediate+next_value-teacher_q, critic_q=critic_q,
            critic_oracle_bootstrap_td_residual=None if critic_q is None else immediate+next_value-critic_q,
            critic_policy_return_residual=None if critic_q is None else remaining-critic_q,
            labels_revealed_after_terminal=True))
    outcome_rows.reverse()
    if abs(remaining-score["utility"]) > 5e-10:
        errors.append(dict(kind="realized_return_accounting", recomputed=remaining, terminal_utility=score["utility"]))
    if owner.answers != native["end"]["task"]["answers"]:
        # Posterior arithmetic may differ by roundoff; all discrete answers still
        # must match, with a separately bounded probability discrepancy.
        a, b = owner.answers, native["end"]["task"]["answers"]
        if len(a) != len(b) or any(any(x[k] != y[k] for k in ("job", "prediction", "tick", "reads"))
                                 or abs(x["posterior"]-y["posterior"]) > 5e-10 for x, y in zip(a, b)):
            errors.append(dict(kind="terminal_answers"))
    stage = {name: sum(r["stage_costs"][name] for r in native["receipts"])
             for name in ("query_nanos", "critic_nanos", "decision_nanos", "propagation_nanos", "content_nanos", "persist_nanos")}
    return dict(score=score, fitted_law_regret=regret, counts=native["end"]["task"]["counts"],
                stage_costs_nanos=stage, load_nanos=native["load_nanos"],
                task_elapsed=native["end"]["task"]["task_elapsed"],
                parity=dict(passed=not errors, errors=errors, max_q_absolute_error=qerr,
                            max_cell_feature_absolute_error=ferr, content_observation_mismatches=content_mismatches),
                oracle_details=details, outcome_learning_records=outcome_rows,
                outcome_scope="Realized rewards/costs are assigned after termination. Oracle-bootstrap TD compares to the fitted-law optimal value. Realized suffix returns follow the deployed policy and therefore are not unbiased labels for optimal Q. These heldout records never update a model.")


def run(args):
    training, out = args.training.resolve(), args.out.resolve()
    freeze, protocol = verify_training(training, args.training_freeze_sha)
    build = verify_build(args.binary.resolve(), args.build_report.resolve())
    binary, content = args.binary.resolve(), args.content_model.resolve()
    out.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter(), time.process_time()
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    runner_sources = {name: sha(HERE / name) for name in ("experiment.py", "statistics.py")}
    policy_paths, direct = {}, {}
    for seed in protocol["seeds"]:
        for arm in protocol["arms"]:
            policy_paths[(seed, arm)] = training / "models" / f"seed{seed}_{arm}.json"
        original = training / "models" / f"seed{seed}_ordinary_fixed.json"
        derived = dict(json.loads(original.read_text()), controller="direct_fixed")
        path = out / "derived_policies" / f"seed{seed}_direct_fixed.json"
        save(path, derived)
        policy_paths[(seed, "direct_fixed")] = path
        direct[str(seed)] = dict(path=str(path.relative_to(out)), sha256=sha(path),
            original_sha256=sha(original), change={"controller": ["fixed", "direct_fixed"]})
    save(out / "EXECUTION_FREEZE.json", dict(schema="hcsn.task.native.execution.freeze.v1",
        created_at=datetime.now(timezone.utc).isoformat(), training_freeze_sha256=args.training_freeze_sha,
        training_source=freeze["source"], runner_source=runner_sources, direct_fixed=direct,
        binary_sha256=sha(binary), native_source_digest=build["source_digest"],
        build_report_sha256=sha(args.build_report), content_model_sha256=sha(content), heldout_generated=False,
        confirmation_plan="5 fits x 2 splits x 24 sessions x five fresh-process native controls; independent Python fitted-DP on the same sessions. No retuning or failed-run replacement."))
    rows, archives, result_files, orders, setups = [], {}, {}, [], []
    partial = out / "partial_results.jsonl.gz"
    partial.touch(exist_ok=False)
    for seed_index, seed in enumerate(protocol["seeds"]):
        adapter = ContentAdapter()
        setups.append(dict(seed=seed, **adapter.setup))
        models = {arm: json.loads(path.read_text()) for (s, arm), path in policy_paths.items() if s == seed}
        for split_index, split in enumerate(("test", "ood")):
            announce("native_confirmation_cohort", seed=seed, split=split)
            first_row, first_order = len(rows), len(orders)
            spec = dict(protocol, **protocol["ood"]) if split == "ood" else protocol
            work = out / "_work" / f"cohort_seed{seed}_{split}"
            raw_work = out / "_work" / f"receipts_seed{seed}_{split}"
            cohort = build_cohort(work, split, seed, protocol[f"{split}_sessions"], spec)
            names = list(protocol["arms"])+["direct_fixed"]
            base = np.random.default_rng(seed+protocol["policy_seed_base"]+split_index*100000).permutation(len(names))
            for index, session in enumerate(cohort["records"]):
                folder = Path(session["folder"])
                public = augment_public(folder, protocol)
                cohort["files"][str(public.relative_to(work))] = sha(public)
                meta = json.loads((folder / "public.json").read_text())
                oracle = Bellman(meta, models["ordinary_value"]["confusion"], protocol["multiplier"], protocol["latency_price"])
                order = [names[i] for i in np.roll(base, (index+seed_index) % len(names))]
                orders.append(dict(seed=seed, split=split, session_id=session["id"], policies=order))
                for arm in order:
                    policy_path, model = policy_paths[(seed, arm)], models[arm]
                    snapshot = work / "snapshots" / session["id"] / arm / "owner.json"
                    raw = native_process(binary, public, content, policy_path, model, snapshot)
                    row = dict(seed=seed, split=split, session_id=session["id"], policy=arm,
                        implementation="native", status="failed", error=raw["error"], score=None,
                        child_cpu_seconds=raw["child_cpu_seconds"], parent_cpu_seconds=raw["parent_cpu_seconds"],
                        runtime_cpu_seconds=raw["runtime_cpu_seconds"], runtime_wall_seconds=raw["runtime_wall_seconds"])
                    evaluation_cpu, evaluation_wall = time.process_time(), time.perf_counter()
                    try:
                        check = independent_evaluation(raw, folder, model, adapter, oracle,
                            dict(source_digest=build["source_digest"], public_sha256=sha(public), policy_sha256=sha(policy_path),
                                 content_model_sha256=sha(content), native_neuron_runtime=True, production_activation=False, authority="DENY_ALL"))
                        row.update(check)
                        row["status"] = ("complete" if check["parity"]["passed"] and not check["counts"]["failed_read_attempts"]
                                         else "parity_or_read_failure")
                    except Exception as exc:
                        row["error"] = dict(type=type(exc).__name__, message=str(exc))
                    row["evaluator_cpu_seconds"] = time.process_time()-evaluation_cpu
                    row["evaluator_wall_seconds"] = time.perf_counter()-evaluation_wall
                    path = raw_work / f"{session['id']}_{arm}.json.gz"
                    row["receipt_sha256"] = packed(path, dict(row=row, subprocess=raw))
                    row["receipt"] = path.name
                    rows.append(row)
                    with partial.open("ab") as stream:
                        stream.write(gzip.compress((json.dumps(row, allow_nan=False)+"\n").encode(), mtime=0))
                reference_cpu, reference_wall = time.process_time(), time.perf_counter()
                row = dict(seed=seed, split=split, session_id=session["id"], policy="fitted_dp",
                    implementation="independent_numpy", status="failed", error=None, score=None, counts={},
                    cost_scope="Python DP, actual content inference, terminal scoring and trace creation; not matched native CPU")
                reference = None
                try:
                    reference = play_episode(folder, models["ordinary_value"], adapter, fitted_dp=True)
                    row.update(status="complete", score=reference["score"], counts=reference["counts"],
                               fitted_law_regret=reference["fitted_law_regret"])
                except Exception as exc:
                    row["error"] = dict(type=type(exc).__name__, message=str(exc))
                row["runtime_cpu_seconds"], row["runtime_wall_seconds"] = time.process_time()-reference_cpu, time.perf_counter()-reference_wall
                path = raw_work / f"{session['id']}_fitted_dp.json.gz"
                row["receipt_sha256"] = packed(path, dict(row=row, reference=reference))
                row["receipt"] = path.name
                rows.append(row)
                with partial.open("ab") as stream:
                    stream.write(gzip.compress((json.dumps(row, allow_nan=False)+"\n").encode(), mtime=0))
                if (index+1) % 8 == 0:
                    announce("native_confirmation_progress", seed=seed, split=split, sessions=index+1)
            raw_archives, raw_members = archive_chunks(out, raw_work, f"receipts/seed{seed}_{split}")
            data_archives, data_members = archive_chunks(out, work, f"data/seed{seed}_{split}")
            archives.update(raw_archives)
            archives.update(data_archives)
            for row in rows[first_row:]:
                member = raw_members[row["receipt"]]
                if member["sha256"] != row["receipt_sha256"]:
                    raise ValueError("Receipt changed while archiving")
                row["receipt"] = member
            value = dict(rows=rows[first_row:], orders=orders[first_order:], cohort=cohort, data_members=data_members)
            path = out / "results" / f"seed{seed}_{split}.json.gz"
            result_files[str(path.relative_to(out))] = packed(path, value)
            if path.stat().st_size > MAX_BLOB_BYTES:
                raise ValueError("Cohort result exceeds frozen blob budget; keep the attempt and split evidence")
            if json.loads(gzip.decompress(path.read_bytes())) != value:
                raise ValueError("Cohort result readback failed")
            # Every completed raw receipt and data byte is now verified in small
            # archives and an indexed result file. Retire only its partial log.
            partial.unlink()
            partial.touch(exist_ok=False)
    verify_training(training, args.training_freeze_sha)
    verify_build(binary, args.build_report.resolve())
    if {name: sha(HERE / name) for name in runner_sources} != runner_sources:
        raise ValueError("Confirmation runner source changed while heldout data was being evaluated")
    report = analyze(rows, freeze, protocol)
    packed(out / "STATISTICS.json.gz", report)
    partial.unlink()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    save(out / "COMPLETE.json", dict(schema="hcsn.task.native.confirmation.complete.v1",
        result_files=result_files, statistics_sha256=sha(out / "STATISTICS.json.gz"), archives=archives,
        training_freeze_sha256=args.training_freeze_sha, execution_freeze_sha256=sha(out / "EXECUTION_FREEZE.json"),
        adapter_setups=setups, wall_seconds=time.perf_counter()-wall, parent_cpu_seconds=time.process_time()-cpu,
        child_cpu_seconds=after.ru_utime+after.ru_stime-children.ru_utime-children.ru_stime,
        native_runs=sum(r["implementation"] == "native" for r in rows), reference_runs=sum(r["implementation"] != "native" for r in rows),
        failed_runs=sum(r["status"] != "complete" for r in rows),
        cost_scope="Outer parent plus child CPU is complete campaign cost. It includes native startup/runtime, independent replay, label scoring, DP, data generation, archive and receipt writes. Per-run and evaluator costs are nested attributions and must not be added again.",
        energy_joules=None, production_activation=False))
    announce("native_confirmation_complete", output=str(out), failed_runs=len(report["failed_runs"]),
             statistical_gates_passed=report["statistical_gates_passed"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training", type=Path, required=True)
    parser.add_argument("--training-freeze-sha", required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--build-report", type=Path, required=True)
    parser.add_argument("--content-model", type=Path, default=HERE.parent / "round9_20261031/native/fixtures/fullhx.json")
    parser.add_argument("--out", type=Path, required=True)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
