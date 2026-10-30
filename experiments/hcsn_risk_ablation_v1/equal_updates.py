"""Frozen equal-updates companion; exactly 128 updates and no model selection.

This module and its protocol are additions. They never modify any of the
55 source identities of the separate risk001 equal-CPU study.
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time
import traceback

import torch
from torch.nn import functional as F

from experiments.hcsn_free_boundary_v1 import training
from experiments.hcsn_distributional_v2.content_study import evaluate
from .model import MODEL_NAMES, build_model
from .study import ROOT, PACKAGE, verify


def register(protocol_path, output):
    protocol_path, output = Path(protocol_path), Path(output)
    if protocol_path.exists() or output.exists():
        raise FileExistsError("Preserve prior registrations")
    main_path = PACKAGE / "PROTOCOL.json"
    main = verify(main_path)
    if training._sha256(main_path) != "a479546a28ab92f4d6bdbfa440c487da968c986b811c3090e74d3b3a09c68c62" or len(main["source_files_sha256"]) != 55:
        raise RuntimeError("The original 55-source risk001 registration must remain unchanged")
    main_study = PACKAGE / "results/risk001"
    if list(main_study.glob("runs/*/test_predictions.npz")) or list(main_study.glob("runs/*/summary.json")):
        raise RuntimeError("Companion must be registered before risk001 heldout evaluation")
    sources = dict(main["source_files_sha256"])
    sources[str(main_path.relative_to(ROOT))] = training._sha256(main_path)
    for name in ("equal_updates.py", "equal_updates_analysis.py", "EQUAL_UPDATES.md"):
        path = PACKAGE / name
        sources[str(path.relative_to(ROOT))] = training._sha256(path)
    preflight = json.loads((PACKAGE / "results/train_preflight002/RESULTS.json").read_bytes())
    estimated_training_cpu = 8 * 128 * sum(sum(row["update_cpu_seconds"])/3 for row in preflight["records"])
    jobs = list(main["jobs"])
    random.Random(202610302).shuffle(jobs)
    protocol = dict(schema="hcsn-risk-equal-updates-study.v1", study_id="risk128",
        registered_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        source_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        status_at_registration="no_risk001_or_risk128_heldout_evaluation",
        source_files_sha256=sources, data=main["data"], jobs=jobs,
        models=main["models"], seeds=main["seeds"], mechanism=main["mechanism"],
        model_identity=dict(equal_cpu_protocol=str(main_path.relative_to(ROOT)),
            equal_cpu_protocol_sha256=training._sha256(main_path), frozen_upstream_source_count=55,
            all_55_source_hashes_identical=True),
        optimization=dict(learning_rate=.001, updates=128, width=32, depth=1, batch_size=32,
            threads=1, optimizer="Adam defaults", gradient_clip_l2=2.0, loss="task_cross_entropy_only",
            selection="exactly update128; no checkpoint/LR/validation selection",
            validation="loaded and reported only after fixed-update weight identity is durably locked",
            minibatch="seed+200003; same randint prefix as risk001; identical 128 draws across arms",
            training_cpu_cap_seconds=900.0,
            cap_semantics="checked after complete updates, all overrun charged; any exceedance fails even at update128; no heldout for failed candidates; no rerun"),
        execution=dict(workers=2, expected_searches=112, expected_lr_candidates=112,
            expected_optimizer_updates=14336, maximum_training_cpu_budget_seconds=100800.0,
            train_only_timing_forecast_cpu_seconds=estimated_training_cpu,
            forecast_is_measurement=False, failure_policy="stop new launches; drain active; retain failures and all costs; no filling failed cells",
            cost="wait4 full worker CPU; training nested; 900-second cap applies to training, not imports/evaluation",
            energy_measured=False),
        joint_inference=dict(equal_cpu_family="risk001: four primary Holm-adjusted seed-level contrasts",
            equal_updates_family="risk128: same four primary contrasts, separately Holm-adjusted",
            unrestricted_advantage_claim="corresponding predeclared gate must pass in BOTH families",
            only_one_family_passes="report only under that explicit resource/data-exposure regime",
            no_cherry_picking="neither choose the better family nor pool tasks or choose new checkpoints",
            family_error_scope="adjustments are within each predeclared family; no claim of global FWER for the union of one-family positives"),
        outcome_scope="post-baseline exploratory; same previously observed datasets; fixed128 checkpoints do not establish convergence")
    output.mkdir(parents=True, exist_ok=False)
    training._write_json(protocol_path, protocol)
    training._write_json(output / "REGISTRATION.json", dict(protocol_sha256=training._sha256(protocol_path),
        registered_utc=protocol["registered_utc"], jobs=len(jobs), status="before_main_training"))
    return protocol


def worker(protocol_path, output, job):
    protocol = verify(protocol_path)
    if job not in protocol["jobs"]:
        raise ValueError("Unregistered job")
    torch.set_num_threads(1)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    access, training_cpu, updates = [], 0.0, 0
    digest = training._sha256(protocol_path)
    training._write_json(output / "request.json", dict(job=job, protocol_sha256=digest,
        optimization=protocol["optimization"], torch_version=torch.__version__))
    try:
        data_path = ROOT / protocol["data"][job["task"]]["path"]
        train = training.load_split(data_path, "train", access)
        model = build_model(job["model"], train["x"].shape[-1], int(train["y"].max())+1,
                            width=32, depth=1, seed=job["seed"])
        initial = {name: value.detach().clone() for name, value in model.named_parameters()}
        initial_hash = training.save_weights(output / "initial.npz", model)
        optimizer = torch.optim.Adam(model.parameters(), lr=.001)
        generator, prefix = torch.Generator().manual_seed(job["seed"]+200003), hashlib.sha256()
        with (output / "updates.jsonl").open("x") as log:
            for step in range(1, 129):
                start_update = time.process_time()
                indices = torch.randint(train["x"].shape[0], (32,), generator=generator)
                raw = indices.numpy().tobytes()
                prefix.update(raw)
                x, dt, y = (train[key][indices] for key in ("x", "dt", "y"))
                model.train()
                optimizer.zero_grad(set_to_none=True)
                logits, aux = model(x, dt, return_sequence=True)
                loss = F.cross_entropy(logits.flatten(0, 1), y.flatten(), ignore_index=-100)
                if not bool(torch.isfinite(loss)):
                    raise FloatingPointError("Nonfinite loss")
                loss.backward()
                gradients = training._gradient_summary(model)
                if not all(g["finite"] and g["missing_elements"] == 0 for g in gradients.values()):
                    raise FloatingPointError("Nonfinite or disconnected gradient")
                norm = float(torch.nn.utils.clip_grad_norm_(model.parameters(), 2.0))
                optimizer.step()
                updates = step
                training_cpu += time.process_time()-start_update
                row = dict(step=step, loss=float(loss.detach()), training_cpu_seconds=training_cpu,
                    batch_sha256=hashlib.sha256(raw).hexdigest(), prefix_sha256=prefix.hexdigest(),
                    gradients=gradients, preclip_gradient_l2=norm,
                    max_projection_l1=float(aux["projection_actual_l1_correction"].max()),
                    max_probability_mass_error=float((aux["flow_mass"].detach()-1).abs().max()))
                if "first_event_probability" in aux:
                    risk = aux["first_event_probability"].detach()
                    row.update(min_first_event_probability=float(risk.min()), max_first_event_probability=float(risk.max()))
                log.write(json.dumps(row, sort_keys=True, allow_nan=False)+"\n")
                log.flush()
                if training_cpu > 900:
                    raise TimeoutError("Training CPU cap exceeded; retain failure, no replacement run")
        weight_hash = training.save_weights(output / "step_000128.npz", model)
        selection = dict(rule="fixed_update_128_no_validation_selection", selected_step=128,
            selected_checkpoint_sha256=weight_hash, selected_learning_rate=.001,
            dataset_sha256=protocol["data"][job["task"]]["sha256"])
        training._write_json(output / "selection.json", selection)
        access.append(dict(event="selection_locked", step=128, validation_seen=False))
        verify(protocol_path)
        if training._sha256(protocol_path) != digest:
            raise RuntimeError("Protocol changed during worker")
        evaluation, evaluation_start = {}, time.process_time()
        for split in ("val", "test", "ood"):
            values = training.load_split(data_path, split, access)
            evaluation[split] = None if values is None else evaluate(model, values,
                output_path=output / (split + "_predictions.npz"))
        verify(protocol_path)
        if training._sha256(protocol_path) != digest:
            raise RuntimeError("Protocol changed after evaluation")
        summary = dict(status="completed", job=job, protocol_sha256=digest,
            config=model.config, counts=model.counts(), initial_sha256=initial_hash,
            selection=selection, updates=updates, training_cpu_seconds=training_cpu,
            stopping_reason="fixed_128_updates", batch_prefix_sha256=prefix.hexdigest(),
            selected_parameter_changes=training._parameter_changes(model, initial),
            evaluation=evaluation, access_log=access, evaluation_cpu_seconds=time.process_time()-evaluation_start,
            total_cpu_seconds=time.process_time()-start_cpu, total_wall_seconds=time.perf_counter()-start_wall,
            process_peak_rss_bytes=training._peak_rss_bytes(), energy_measured=False)
        training._write_json(output / "summary.json", summary)
        training._write_json(output / "IDENTITY.json", dict(job=job, status="completed",
            protocol_sha256=digest, source_files_sha256=protocol["source_files_sha256"],
            dataset_sha256=protocol["data"][job["task"]]["sha256"]))
        return summary
    except Exception as error:
        training._write_json(output / "failure.json", dict(error_type=type(error).__name__,
            error=str(error), traceback=traceback.format_exc(), updates=updates,
            training_cpu_seconds=training_cpu, total_cpu_seconds=time.process_time()-start_cpu,
            access_log=access, rerun_allowed=False))
        raise


def run(protocol_path, output):
    protocol_path, output = Path(protocol_path).resolve(), Path(output).resolve()
    protocol = verify(protocol_path)
    digest = training._sha256(protocol_path)
    if json.loads((output / "REGISTRATION.json").read_bytes())["protocol_sha256"] != digest:
        raise ValueError("Registration mismatch")
    (output / "runs").mkdir()
    (output / "process_logs").mkdir()
    environment = os.environ.copy()
    environment.update({key: "1" for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")})
    pending, active, records, stopped = list(protocol["jobs"]), {}, [], False
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    while pending or active:
        stopped = stopped or (output / "STOP_REQUESTED.json").exists()
        while pending and not stopped and len(active) < protocol["execution"]["workers"]:
            job = pending.pop(0)
            identifier = f"{job['task']}__{job['model']}__{job['seed']}"
            folder, log = output / "runs" / identifier, output / "process_logs" / (identifier + ".log")
            stream = log.open("x")
            command = [sys.executable, "-m", "experiments.hcsn_risk_ablation_v1.equal_updates", "worker",
                "--protocol", str(protocol_path), "--output", str(folder),
                "--task", job["task"], "--model", job["model"], "--seed", str(job["seed"])]
            process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=stream, stderr=subprocess.STDOUT)
            active[process.pid] = (process, stream, job, folder, log, command, time.perf_counter())
        for pid, item in list(active.items()):
            got, status, usage = os.wait4(pid, os.WNOHANG)
            if not got:
                continue
            process, stream, job, folder, log, command, launched = item
            code = os.waitstatus_to_exitcode(status)
            process.returncode = code
            stream.close()
            folder.mkdir(exist_ok=True)
            receipt = dict(job=job, command=command, returncode=code, protocol_sha256=digest,
                stdout_sha256=training._sha256(log), child_user_cpu_seconds=usage.ru_utime,
                child_system_cpu_seconds=usage.ru_stime, child_total_cpu_seconds=usage.ru_utime+usage.ru_stime,
                child_peak_rss_kib_linux=usage.ru_maxrss, wall_seconds=time.perf_counter()-launched)
            training._write_json(folder / "EXECUTION.json", receipt)
            records.append(receipt)
            del active[pid]
            stopped = stopped or code != 0
            training._write_json(output / "PROGRESS.json", dict(records=records, expected=len(protocol["jobs"])))
            print(json.dumps(dict(completed=len(records), expected=len(protocol["jobs"]), job=job, returncode=code)), flush=True)
        if stopped and not active:
            break
        if active:
            time.sleep(.05)
    verify(protocol_path)
    complete = not stopped and len(records) == len(protocol["jobs"])
    final = dict(status="completed" if complete else "aborted", protocol_sha256=digest,
        records=records, expected=len(protocol["jobs"]), completed=len(records), unstarted=pending,
        failures=sum(row["returncode"] != 0 for row in records),
        complete_child_cpu_seconds=sum(row["child_total_cpu_seconds"] for row in records),
        coordinator_cpu_seconds=time.process_time()-start_cpu, wall_seconds=time.perf_counter()-start_wall)
    training._write_json(output / ("COMPLETE.json" if complete else "ABORTED.json"), final)
    return final


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("register", "worker", "run"))
    parser.add_argument("--protocol", type=Path, default=PACKAGE / "EQUAL_UPDATES_PROTOCOL.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task")
    parser.add_argument("--model", choices=MODEL_NAMES)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()
    if args.action == "register":
        register(args.protocol, args.output)
    elif args.action == "worker":
        worker(args.protocol, args.output, dict(task=args.task, model=args.model, seed=args.seed))
    else:
        run(args.protocol, args.output)
