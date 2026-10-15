#!/usr/bin/env python3
"""Physical per-arm Linux wait4 CPU/RSS trial; NEVER a product or NDU gate.

Each arm is trained in a distinct *real* process. The parent records kernel
wait4 CPU and peak RSS, and accepts a child only after its independently
recomputed original FP32 weights, routes and predictions match the registered
five-arm predecessor (excluding explicitly volatile time measurements).

This is single-host retrospective *research*, not equal lifecycle compute,
energy, a genuine future window, hardware custody, or production authority.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
from pathlib import Path
import platform
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any

from qualification.cell_meta_execution_af import physical_router_audit as audit
from qualification.cell_meta_execution_af import physical_router_cost_frontier as cost
from qualification.cell_meta_execution_af import physical_router_paired_screen as paired

SCHEMA = "hepta.cell-meta-isolated-kernel-resource.v1"
NAMED = cost.NAMED
TIMEOUT_SECONDS = 45
MIN_WALL = 0.0
MAX_OUTPUT = 32 * 1024
MAX_RSS = 1 << 44


class ResourceDenied(ValueError):
    """No complete reproducible, source-bound OS resource observation."""


def require(value: bool, reason: str) -> None:
    if not value:
        raise ResourceDenied(reason)


def _as_scalar(value: Any, name: str) -> float:
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
            "nonfinite or negative " + name)
    return float(value)


def strip_time(value: dict[str, Any], arm: str) -> dict[str, Any]:
    """Only remove the precisely volatile, untrusted timing field."""
    require(type(value) is dict, "wrong observed result")
    obj = copy.deepcopy(value)
    if arm == NAMED[0]:
        require(type(obj.get("meters")) is dict and
                "actual_inference_cpu_seconds" in obj["meters"],
                "missing frozen CPU time")
        obj["meters"].pop("actual_inference_cpu_seconds")
    else:
        require(type(obj.get("meters")) is dict and
                "train_cpu_seconds" in obj["meters"],
                "missing training CPU time")
        obj["meters"].pop("train_cpu_seconds")
    return obj


def _worker(bundle: dict[str, Any], arm: str) -> dict[str, Any]:
    # Training and inference only; no old weights are selected/promoted.
    from qualification.cell_meta_execution_af import physical_router_trial as trial
    from qualification.cell_meta_execution_af import physical_router_hard_train as hardtrain
    from qualification.cell_meta_execution_af import physical_router_frozen_baseline as frozenprod
    from qualification.cell_meta_execution_af import physical_router_frozen_review as frozenrev

    require(arm in NAMED, "unknown cell route arm")
    panel, soft, post, hard, frozen = (bundle[k] for k in
                                       ("panel", "soft", "posthoc", "hard", "frozen"))
    # Original outcomes/weights and all stage1 bindings are replayed with an
    # independent stdlib implementation before any new Torch cost is reported.
    frozenrev.replay(panel, soft, post, hard, frozen)
    if arm == NAMED[0]:
        actual = frozenprod.produce(panel, soft, post, hard)
        reference = frozen
        version = "frozen_stage1_reinference"
    else:
        import torch
        torch.set_num_threads(1)
        index = NAMED.index(arm)-1
        original = ("no_change", "fixed_router", "learned_router", "adaptive_split")[index]
        actual = hardtrain.train_one(panel, original, steps=hard["steps_each_stage"])
        actual["retrospective_evaluation"] = hardtrain.score_after_seal(panel, actual)
        reference = hard["results"][index]
        version = "actual_fresh_sparse_top1_training"
    # Compare ALL other fields: scores, every FP32 tensor, Head/router counts,
    # train-only trigger, deterministic route bitsets and stage1 lineage.
    require(audit.canonical(strip_time(actual, arm)) ==
            audit.canonical(strip_time(reference, arm)),
            "isolated execution differs from original peer-verified research output")
    return {"arm": arm, "operation": version,
            "original_bundle_sha256": audit.digest(bundle),
            "replayed_immutable_result_sha256": audit.digest(strip_time(actual, arm)),
            "original_result_sha256": audit.digest(strip_time(reference, arm)),
            "result_identity_and_full_fp32_replay_match": True,
            "authority_posture": "DENY_ALL", "production_admission": "BLOCKED",
            "future_window_prospective": False, "full_lifecycle_cost_matched": False,
            "new_pretrained_encoder_forward": False,
            "external_host_signatures_verified": False}


def child_entry(bundle_dir: Path, seed: int, arm: str) -> int:
    try:
        require(seed in paired.SEEDS and arm in NAMED, "seed or arm outside original plan")
        require(bundle_dir.is_dir() and not bundle_dir.is_symlink(),
                "invalid source folder")
        b = paired.read_bundles(bundle_dir)[seed]
        payload = _worker(b, arm)
        print(audit.canonical(payload).decode("utf8"))
        return 0
    except Exception as exc:
        # The worker cannot recover or retry a possibly incomplete operation.
        print("ISOLATED RESOURCE WORKER DENIED: "+repr(exc),file=sys.stderr)
        return 2


def _launch(bundle_dir: Path, seed: int, arm: str, *, timeout: float = TIMEOUT_SECONDS,
            python: str = sys.executable) -> dict[str, Any]:
    """Parent OS wait4, not a child-declared RSS/CPU number."""
    require(os.name == "posix" and sys.platform.startswith("linux") and
            hasattr(os, "wait4"), "Linux wait4 runner required")
    require(seed in paired.SEEDS and arm in NAMED, "unsupported seed/arm")
    require(_as_scalar(timeout, "timeout") > 0 and timeout <= TIMEOUT_SECONDS,
            "bounded positive timeout required")
    root = Path(__file__).resolve().parents[2]
    # Subprocess environment explicitly drops GitHub/Cloud credentials. The
    # original tasks are local-only and never require access to network/secrets.
    env = {k: os.environ[k] for k in ("PATH", "LANG", "LD_LIBRARY_PATH") if k in os.environ}
    env.update({"PYTHONPATH":str(root),"OMP_NUM_THREADS":"1", "MKL_NUM_THREADS":"1",
                "OPENBLAS_NUM_THREADS":"1", "PYTHONDONTWRITEBYTECODE":"1",
                "HF_HUB_OFFLINE":"1", "TRANSFORMERS_OFFLINE":"1", "CUDA_VISIBLE_DEVICES":""})
    command = [python, "-m", "qualification.cell_meta_execution_af.physical_router_os_meter",
               "--worker", "--bundle-dir", str(bundle_dir.resolve()),
               "--seed", str(seed), "--arm", arm]
    with tempfile.TemporaryDirectory(prefix="hepta-meta-wait4-") as folder:
        stdout_path=Path(folder)/"stdout.txt"
        stderr_path=Path(folder)/"stderr.txt"
        started = time.perf_counter()
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(command, cwd=root, env=env, stdin=subprocess.DEVNULL,
                                       stdout=stdout, stderr=stderr, close_fds=True)
            deadline = started + timeout
            killed = False
            while True:
                pid,status,usage = os.wait4(process.pid, os.WNOHANG)
                if pid:
                    break
                if time.perf_counter() >= deadline:
                    process.kill()
                    killed=True
                    pid,status,usage = os.wait4(process.pid, 0)
                    break
                time.sleep(.015)
            process.returncode = os.waitstatus_to_exitcode(status)
        elapsed = time.perf_counter()-started
        if killed or process.returncode != 0:
            error = stderr_path.read_bytes()[:2048].decode("utf8", errors="replace")
            raise ResourceDenied(
                f"isolated physical run failed (status={process.returncode}, "
                f"timeout={killed}; no retry): {error}"
            )
        require(stdout_path.stat().st_size <= MAX_OUTPUT and
                stderr_path.stat().st_size <= MAX_OUTPUT,
                "unbounded child stdout/stderr")
        require(stderr_path.stat().st_size == 0, "unexpected child diagnostic output")
        raw = stdout_path.read_bytes()
        require(raw.endswith(b"\n") and raw.count(b"\n") == 1,
                "single bounded child receipt required")
        try:
            child = json.loads(raw, object_pairs_hook=_reject_duplicate_json,
                               parse_constant=lambda x: (_ for _ in ()).throw(
                                   ResourceDenied("nonfinite JSON child constant " + x)))
        except (ValueError, UnicodeError) as exc:
            raise ResourceDenied("malformed child receipt") from exc
        accept_child(child, arm)
        mb = usage.ru_maxrss * 1024  # Linux wait4 ru_maxrss is KiB, not bytes.
        cpu_s = usage.ru_utime + usage.ru_stime
        require(_as_scalar(mb,"peak RSS") < MAX_RSS and
                _as_scalar(cpu_s,"CPU time") >= 0 and elapsed > MIN_WALL,
                "nonsensical OS resource sample")
        return {"seed":seed,"arm":arm,"child_exit_status":0,
                "full_result_sha256":child["original_result_sha256"],
                "source_bundle_sha256":child["original_bundle_sha256"],
                "os_wait4_user_cpu_seconds":round(usage.ru_utime,6),
                "os_wait4_system_cpu_seconds":round(usage.ru_stime,6),
                "os_wait4_total_cpu_seconds":round(cpu_s,6),
                "os_wait4_peak_rss_bytes":int(mb),
                "parent_monotonic_elapsed_seconds":round(elapsed,6),
                "physical_os_process_executed":True,
                "complete_result_recomputed_and_equal":True,
                "measurement_scope":"fresh_python_process_full_import_audit_and_arm_operation",
                "cpu_energy_joules":None,"gpu_peak_bytes":None,
                "full_lifecycle_cost_matched":False,
                "external_host_signatures_verified":False,
                "actual_future_outcomes_verified":False,
                "independent_ndu_selection_authorized":False,
                "production_admission":"BLOCKED","authority_posture":"DENY_ALL"}


def _reject_duplicate_json(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in obj, "duplicate child receipt field")
        obj[key] = value
    return obj


def accept_child(child: Any, arm: str) -> None:
    """Fail-closed shape/posture validation; not a signature authenticator."""
    require(type(child) is dict and set(child) == {
            "arm", "operation", "original_bundle_sha256", "replayed_immutable_result_sha256",
            "original_result_sha256", "result_identity_and_full_fp32_replay_match",
            "authority_posture", "production_admission", "future_window_prospective",
            "full_lifecycle_cost_matched", "new_pretrained_encoder_forward",
            "external_host_signatures_verified"}, "child evidence field drift")
    expected_operation = ("frozen_stage1_reinference" if arm == NAMED[0]
                          else "actual_fresh_sparse_top1_training")
    require(child["arm"] == arm and child["operation"] == expected_operation and
            child["result_identity_and_full_fp32_replay_match"] is True and
            child["replayed_immutable_result_sha256"] == child["original_result_sha256"] and
            child["authority_posture"] == "DENY_ALL" and
            child["production_admission"] == "BLOCKED" and
            all(child[k] is False for k in ("future_window_prospective",
                "full_lifecycle_cost_matched", "new_pretrained_encoder_forward",
                "external_host_signatures_verified")), "untrusted or unauthorized child report")
    for name in ("original_bundle_sha256", "replayed_immutable_result_sha256",
                 "original_result_sha256"):
        h=child[name]
        require(type(h) is str and len(h)==64 and
                all(c in "0123456789abcdef" for c in h) and any(c != "0" for c in h),
                "untrusted child digest " + name)


def measure(bundle_dir: Path, *, timeout: float = TIMEOUT_SECONDS,
            seeds: tuple[int, ...] = paired.SEEDS) -> dict[str, Any]:
    require(type(seeds) is tuple and seeds and
            all(s in paired.SEEDS for s in seeds) and len(set(seeds)) == len(seeds),
            "original registered seed subset required")
    bundles = paired.read_bundles(bundle_dir)
    # Validate the *entire* registered panel before sending source paths to OS
    # children. This does not replace independent model/host attestations.
    true_pair = paired.screen(bundles)
    cost_report = cost.evaluate(bundles,true_pair)
    results=[]
    for seed in seeds:
        for arm in NAMED:
            obs=_launch(bundle_dir,seed,arm,timeout=timeout)
            b = bundles[seed]
            require(obs["source_bundle_sha256"] == audit.digest(b),
                    "unpaired original evidence bundle")
            if arm == NAMED[0]:
                expected = strip_time(b["frozen"], arm)
            else:
                expected = strip_time(b["hard"]["results"][NAMED.index(arm)-1],arm)
            require(obs["full_result_sha256"]==audit.digest(expected),
                    "wrong source-bound physical Head output")
            results.append(obs)
            print(f"measured seed={seed} arm={arm} using original FP32/replay, "
                  f"cpu={obs['os_wait4_total_cpu_seconds']:.3f}s, "
                  f"rss={obs['os_wait4_peak_rss_bytes']}", file=sys.stderr, flush=True)
    return {"schema":SCHEMA,"source_paired_report_sha256":audit.digest(true_pair),
            "source_cost_report_sha256":audit.digest(cost_report),
            "host_kernel":platform.system(),"host_machine":platform.machine(),
            "paired_seed_count":len(seeds),"paired_original_source_count":true_pair["reused_original_source_rows"],
            "measurements":results,
            "processes_are_separate_and_serial":True,
            "process_cpu_rss_not_full_lifecycle_comparable":True,
            "cpu_measurements_have_model_import_and_replay_cost":True,
            "real_pretrained_encoder_executed_in_this_trial":False,
            "external_host_attestation":False,"statistical_winner_certified":False,
            "actual_future_outcomes_verified":False,"ndu_selection_authorized":False,
            "production_admission":"BLOCKED","authority_posture":"DENY_ALL"}


def join_shards(bundle_dir: Path, receipts_dir: Path) -> dict[str, Any]:
    """Join ALL registered seeds, original-source-bound, with NO retry/imputation."""
    import statistics

    # Reconstruct source case/weights/route validations before trusting even
    # the limited per-process diagnostic resource claims.
    bundles=paired.read_bundles(bundle_dir)
    source=paired.screen(bundles)
    frontier=cost.evaluate(bundles,source)
    expected_pair=audit.digest(source)
    expected_cost=audit.digest(frontier)
    all_rows=[]
    runs={}
    common_machine = None
    for seed in paired.SEEDS:
        item=audit.load(receipts_dir/f"{seed}-os-meter.json")
        require(type(item) is dict and set(item)=={
            "schema","source_paired_report_sha256","source_cost_report_sha256",
            "host_kernel","host_machine","paired_seed_count",
            "paired_original_source_count","measurements",
            "processes_are_separate_and_serial",
            "process_cpu_rss_not_full_lifecycle_comparable",
            "cpu_measurements_have_model_import_and_replay_cost",
            "real_pretrained_encoder_executed_in_this_trial",
            "external_host_attestation","statistical_winner_certified",
            "actual_future_outcomes_verified","ndu_selection_authorized",
            "production_admission","authority_posture"},
            "unregistered OS shard fields")
        require(item["schema"]==SCHEMA and
                item["source_paired_report_sha256"]==expected_pair and
                item["source_cost_report_sha256"]==expected_cost and
                item["paired_seed_count"]==1 and
                item["paired_original_source_count"]==source["reused_original_source_rows"] and
                item["host_kernel"]=="Linux" and
                type(item["host_machine"]) is str and item["host_machine"] and
                all(item[k] is True for k in (
                    "processes_are_separate_and_serial",
                    "process_cpu_rss_not_full_lifecycle_comparable",
                    "cpu_measurements_have_model_import_and_replay_cost")) and
                all(item[k] is False for k in (
                    "real_pretrained_encoder_executed_in_this_trial",
                    "external_host_attestation","statistical_winner_certified",
                    "actual_future_outcomes_verified","ndu_selection_authorized")) and
                item["authority_posture"]=="DENY_ALL" and
                item["production_admission"]=="BLOCKED",
                "OS shard does not preserve exact source/non-authority")
        # Keep a cross-architecture shard out of the same CPU/RSS panel.
        # This is only an untrusted machine-class equality check, NOT host
        # attestation or proof of one physical device across all three seeds.
        if common_machine is None:
            common_machine = item["host_machine"]
        else:
            require(item["host_machine"] == common_machine,
                    "mixed host architectures cannot form one CPU/RSS panel")
        rows=item["measurements"]
        require(type(rows) is list and len(rows)==len(NAMED) and
                [r.get("arm") for r in rows]==list(NAMED),
                "missing/duplicate/reordered OS arm in shard")
        for arm,row in zip(NAMED,rows,strict=True):
            require(type(row) is dict and set(row)=={
                "seed","arm","child_exit_status","full_result_sha256",
                "source_bundle_sha256","os_wait4_user_cpu_seconds",
                "os_wait4_system_cpu_seconds","os_wait4_total_cpu_seconds",
                "os_wait4_peak_rss_bytes","parent_monotonic_elapsed_seconds",
                "physical_os_process_executed","complete_result_recomputed_and_equal",
                "measurement_scope","cpu_energy_joules","gpu_peak_bytes",
                "full_lifecycle_cost_matched","external_host_signatures_verified",
                "actual_future_outcomes_verified","independent_ndu_selection_authorized",
                "production_admission","authority_posture"}, "OS original runtime row drift")
            b=bundles[seed]
            expected=(b["frozen"] if arm==NAMED[0]
                      else b["hard"]["results"][NAMED.index(arm)-1])
            require(row["seed"]==seed and row["arm"]==arm and
                    row["child_exit_status"]==0 and
                    row["full_result_sha256"]==audit.digest(strip_time(expected,arm)) and
                    row["source_bundle_sha256"]==audit.digest(b) and
                    row["physical_os_process_executed"] is True and
                    row["complete_result_recomputed_and_equal"] is True and
                    row["measurement_scope"]==
                        "fresh_python_process_full_import_audit_and_arm_operation" and
                    row["cpu_energy_joules"] is None and row["gpu_peak_bytes"] is None and
                    all(row[k] is False for k in (
                        "full_lifecycle_cost_matched","external_host_signatures_verified",
                        "actual_future_outcomes_verified","independent_ndu_selection_authorized")) and
                    row["production_admission"]=="BLOCKED" and
                    row["authority_posture"]=="DENY_ALL",
                    "OS row not bound to original checked model or postures")
            c=_as_scalar(row["os_wait4_total_cpu_seconds"],"CPU seconds")
            u=_as_scalar(row["os_wait4_user_cpu_seconds"],"user CPU seconds")
            sy=_as_scalar(row["os_wait4_system_cpu_seconds"],"system CPU seconds")
            w=_as_scalar(row["parent_monotonic_elapsed_seconds"],"wall seconds")
            rss=row["os_wait4_peak_rss_bytes"]
            require(type(rss) is int and 0 < rss < MAX_RSS and
                    c>0 and w>0 and abs(c-u-sy)<=3e-6,
                    "invalid OS measured resource arithmetic")
            all_rows.append(row)
        runs[str(seed)]={"source_sha256":audit.digest(item),
                         "measured_real_os_children":len(rows)}
    return {"schema":"hepta.cell-meta-isolated-kernel-resource-joined.v1",
            "paired_original_source_sha256":expected_pair,
            "observed_work_frontier_sha256":expected_cost,
            "original_source_row_count_not_tripled":source["reused_original_source_rows"],
            "same_source_three_correlated_training_seeds":list(paired.SEEDS),
            "exact_15_isolated_processes":len(all_rows),
            "source_bound_shards":runs,
            "median_kernel_cpu_seconds_by_arm":{
                arm:round(statistics.median(r["os_wait4_total_cpu_seconds"] for r in all_rows
                                             if r["arm"]==arm),6) for arm in NAMED},
            "median_peak_rss_bytes_by_arm":{
                arm:int(statistics.median(r["os_wait4_peak_rss_bytes"] for r in all_rows
                                           if r["arm"]==arm)) for arm in NAMED},
            "resource_samples_are_three_correlated_seeds":True,
            "includes_python_import_and_replay_cost":True,
            "causal_reuse_or_total_compute_parity_proved":False,
            "real_target_device_qualified":False,"energy_or_gpu_observed":False,
            "original_host_or_model_signatures_authenticated":False,
            "independent_future_ndu_outcomes_observed":False,
            "resource_or_model_winner_certified":False,
            "production_admission":"BLOCKED","authority_posture":"DENY_ALL"}


def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir",required=True,type=Path)
    parser.add_argument("--out",type=Path)
    parser.add_argument("--seed",type=int)
    parser.add_argument("--arm",choices=NAMED)
    parser.add_argument("--worker",action="store_true")
    parser.add_argument("--join-shards",type=Path)
    parser.add_argument("--timeout-seconds",type=float,default=TIMEOUT_SECONDS)
    parser.add_argument("--seeds",nargs="+",type=int,default=list(paired.SEEDS))
    args=parser.parse_args(argv)
    try:
        if args.worker:
            require(args.seed is not None and args.arm is not None and args.out is None and
                    args.join_shards is None and args.seeds == list(paired.SEEDS),
                    "worker cannot write top-level evidence")
            return child_entry(args.bundle_dir,args.seed,args.arm)
        require(args.seed is None and args.arm is None and args.out is not None,
                "parent must provide output and no child identity")
        if args.join_shards is not None:
            require(args.seeds == list(paired.SEEDS), "join cannot omit any source seed")
            receipt=join_shards(args.bundle_dir,args.join_shards)
        else:
            receipt=measure(args.bundle_dir,timeout=args.timeout_seconds,
                            seeds=tuple(args.seeds))
        raw=audit.canonical(receipt)+b"\n"
        require(len(raw) < 128*1024, "bounded resource output required")
        with args.out.open("xb") as handle:
            handle.write(raw)
            handle.flush();os.fsync(handle.fileno())
        print(json.dumps({"output":str(args.out),
                          "observed_processes":receipt.get("exact_15_isolated_processes",
                                                           len(receipt.get("measurements",[]))),
                          "authority_posture":"DENY_ALL"},sort_keys=True))
        return 0
    except (ResourceDenied, cost.CostFrontierDenied, paired.PairedScreenDenied,
            ValueError, TypeError, KeyError, OSError, OverflowError, RecursionError) as exc:
        print("OS METER DENIED: "+str(exc), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
