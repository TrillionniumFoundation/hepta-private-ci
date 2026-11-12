"""Adapt pinned factorial journals into the unchanged retained-law P1 audit.

The sidecar is derived after training; it is not a TrainingDomainRecorder
capture. Original artifacts, numerical limits and the 4096-record cap stay fixed.
"""

import time
STARTED, CPU_STARTED = time.perf_counter(), time.process_time()

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import re

import torch

from qualification.hcsn_boundary_factorial.run import ARMS, ROOT, FactorialModel
from qualification.hcsn_boundary_audit.audit_trained_gradients import admit, checked_bytes
from qualification.hcsn_differentiable.training_domain import (
    _bytes, _strict_trace_row, source_hashes,
)
from qualification.hcsn_differentiable.training_domain_audit import audit_trace

RECORD_LIMIT, BYTE_LIMIT = 4096, 32 * 1024**2
MODEL_DIGEST = "factorial.run.tensor_digest(FactorialModel.state_dict); not recorder.model_digest(network)"


def trace_rows(path, digest, identities):
    raw = checked_bytes(path, digest, identities)
    lines = raw.splitlines(keepends=True)
    return [(_strict_trace_row(line), hashlib.sha256(line).hexdigest()) for line in lines]


def derive_visits(rows, run, data_by_id, operator):
    schedule = run["training_schedule"]
    if len(rows) != len(schedule) or len(rows) != run["training_forward_calls"]:
        raise ValueError("complete original update schedule required")
    visits, ranges = [], {}
    for step, (row, line_hash) in enumerate(rows):
        if (type(row.get("step")) is not int or row["step"] != step
                or row["episode_id"] != schedule[step]):
            raise ValueError("step or episode differs from ordered schedule")
        episode = data_by_id[row["episode_id"]]
        length = len(episode["y"])
        if (row["dt"] != [episode["dt"]]
                or row["valid_mask"] != [[True] * length]
                or len(row["states"]) != length
                or not re.fullmatch(r"[0-9a-f]{64}", row["model_sha256"])):
            raise ValueError("single complete episode geometry or model digest differs")
        parameters = row["physical_parameters"]
        if set(parameters) != {"log_boundary", "mu", "sigma", "absolute_reset", "discount"}:
            raise ValueError("all five recorded physical parameters required")
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in parameters.values()):
            raise ValueError("finite recorded physical scalars required")
        # FactorialModel.forward always calls network.initial_state without an
        # override; that exact source declares absolute_initial=exp(.55).
        prior = operator.initial_probability(
            torch.tensor([math.exp(.55)], dtype=torch.float64),
            torch.tensor(parameters["log_boundary"], dtype=torch.float64),
        ).tolist()
        for position, state in enumerate(row["states"]):
            posterior, expected = state["probability"], state["expected_events"]
            p, events = torch.tensor(posterior, dtype=torch.float64), torch.tensor(expected)
            if (p.shape != (1, operator.grid.state_count) or events.shape != (1,)
                    or not bool(torch.isfinite(p).all()) or bool((p < 0).any())):
                raise ValueError("one full probability state and event count required")
            duration = row["dt"][0][position]
            if not 0 <= duration <= operator.grid.refractory:
                raise ValueError("recorded gap outside unchanged physical step domain")
            visit = dict(kind="visit", index=len(visits), capture=step,
                episode_id=row["episode_id"], update_index=step, position=position,
                layer=0, model_sha256=row["model_sha256"], model_digest_algorithm=MODEL_DIGEST,
                grid=run["model_configuration"]["grid"], parameters=parameters,
                operator=operator.configuration(), dt=[duration], batch_indices=[0],
                prior=prior, posterior=posterior, expected_events=expected,
                origin_line=step + 1, origin_line_sha256=line_hash,
                prior_derivation="source-declared initial lognormal" if position == 0
                                 else "previous recorded posterior in this episode")
            visits.append(visit)
            prior = posterior
            values = dict(parameters, dt=duration,
                          reset_margin=math.log(parameters["absolute_reset"]) - parameters["log_boundary"])
            for name, value in values.items():
                low, high = ranges.get(name, [value, value])
                ranges[name] = [min(low, value), max(high, value)]
    if not visits or len(visits) > RECORD_LIMIT:
        raise ValueError("arm does not fit unchanged 4096-record audit cap; no truncation")
    return visits, ranges


def write_sidecar(path, visits, ranges, run, summary, plan_sha256):
    current = source_hashes()
    original = {name: summary["source_before"]["qualification/hcsn_differentiable/" + name]
                for name in current}
    if original != current:
        raise ValueError("recorded numerical sources differ from existing P1 auditor")
    header = dict(kind="header", schema="hcsn-training-domain-v1",
        data_sha256=summary["data_sha256"], configuration_sha256=plan_sha256,
        sources=original, max_records=RECORD_LIMIT, max_bytes=BYTE_LIMIT,
        claim="Derived factorial journal sidecar; retained posterior continuation only.",
        origin=dict(schema="factorial-training-journal-sidecar-v1",
            training_trace_sha256=run["training_trace_sha256"],
            sources_basis="exact numerical subset of original training SUMMARY",
            model_digest_algorithm=MODEL_DIGEST,
            initial_prior="source-declared absolute_initial=exp(.55), current recorded physical boundary",
            subsequent_prior="immediately preceding recorded posterior; fresh start per episode",
            model_digest_verification="original source-bound digest retained; historical weights unavailable"))
    prefix = b"".join(_bytes(row) for row in [header, *visits])
    footer = dict(kind="end", captures=run["training_forward_calls"],
        seen_records=len(visits), retained_records=len(visits), dropped_records=0,
        truncated=False, visited_ranges=ranges, padded_states_excluded=0,
        drop_reason=None, sources_after=original, source_unchanged=True,
        prefix_sha256=hashlib.sha256(prefix).hexdigest())
    raw = prefix + _bytes(footer)
    if len(raw) > BYTE_LIMIT:
        raise ValueError("sidecar exceeds unchanged 32 MiB budget")
    with path.open("xb") as stream:
        stream.write(raw)
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write(chr(10))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", type=Path, required=True)
    parser.add_argument("--summary-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    identities, arms = {}, []
    report = dict(schema="hcsn-factorial-training-domain-sidecar-audit-v1", status="error",
        scope="All recorded factorial probability positions; derived retained-law continuation only.",
        scientific_admission="HOLD", numerical_qualification=False,
        continuum_filter_qualified=False, whole_training_trajectory_qualified=False,
        rare_tail_relative_precision_qualified=False, formal_confirmation_accessed=False,
        training_replayed=False, historical_weights_reconstructed=False,
        record_cap_per_arm=RECORD_LIMIT, original_thresholds_unchanged=True,
        python=platform.python_version(), torch=torch.__version__, host=platform.node(),
        device="cpu", dtype="float64", arms=arms, completed_all_runs=False)
    try:
        for path in (Path(__file__), Path(__file__).with_name("audit_trained_gradients.py")):
            checked_bytes(path, None, identities)
        summary, _, _ = admit(args.pilot, args.summary_sha256, identities)
        runs = summary["runs"]
        expected = {(seed, arm) for seed in summary["configuration"]["seeds"] for arm in ARMS}
        if (summary["status"] != "completed_pilot" or len(runs) != len(expected)
                or {(r["seed"], r["arm"]) for r in runs} != expected
                or any(r["status"] != "completed" or not r["complete_training_trace"]
                       or r["model_configuration"]["seed"] != r["seed"]
                       or r["model_configuration"]["arm"] != r["arm"] for r in runs)):
            raise ValueError("complete exact declared four-arm seed roster required")
        data = json.loads(checked_bytes(args.pilot / "DATA.json", summary["data_sha256"], identities))
        data_by_id = {row["id"]: row for row in data["train"]}
        if len(data_by_id) != len(data["train"]):
            raise ValueError("duplicate training episode ids")
        plan_sha = identities[str((args.pilot / "PLAN.json").resolve())]
        report.update(summary_sha256=args.summary_sha256, data_sha256=summary["data_sha256"],
                      expected_runs=len(expected), expected_training_rows=sum(r["training_forward_calls"] for r in runs))
        for run in runs:
            start, cpu_start = time.perf_counter(), time.process_time()
            name = f"seed{run['seed']}-{run['arm']}"
            original = args.pilot / name
            if json.loads(checked_bytes(original / "result.json", None, identities)) != run:
                raise ValueError("arm result differs from pinned summary")
            rows = trace_rows(original / "training.jsonl", run["training_trace_sha256"], identities)
            model = FactorialModel(**run["model_configuration"])
            operator = model.network.layers[0].operator
            with torch.no_grad():
                visits, ranges = derive_visits(rows, run, data_by_id, operator)
            sidecar = args.output_dir / (name + ".derived.jsonl")
            sidecar_hash = write_sidecar(sidecar, visits, ranges, run, summary, plan_sha)
            result = audit_trace(sidecar, max_records=RECORD_LIMIT)
            raw_path = args.output_dir / (name + ".audit.json")
            write_json(raw_path, result)
            counts = {status: sum(v["status"] == status for v in result["visits"])
                      for status in ("passed", "failed", "error")}
            arm = dict(seed=run["seed"], arm=run["arm"], status=result["status"],
                training_rows=len(rows), expected_visits=len(visits),
                audited_records=result["audited_records"], counts=counts,
                complete_retained_coverage=result["complete_retained_coverage"],
                source_matches_trace=result["source_matches_trace"], limits=result["limits"],
                original_training_trace_sha256=run["training_trace_sha256"],
                derived_trace_sha256=sidecar_hash, derived_trace_file=sidecar.name,
                raw_audit_file=raw_path.name, raw_audit_sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                wall_seconds=time.perf_counter() - start, cpu_seconds=time.process_time() - cpu_start)
            for key in ("maximum_mass_error", "maximum_event_replay_error",
                        "maximum_scaled_value_error", "scaled_continuum_gradient_error",
                        "maximum_basis_gradient_absolute_error"):
                values = [v[key] for v in result["visits"] if key in v]
                arm[key] = max(values) if values else None
            arms.append(arm)
            print(json.dumps(arm, sort_keys=True), flush=True)
        report["completed_all_runs"] = len(arms) == len(expected)
        report["all_recorded_positions_audited"] = all(
            a["complete_retained_coverage"] and a["audited_records"] == a["expected_visits"] for a in arms)
        report["status"] = ("passed_reconstructed_continuation" if arms
            and report["completed_all_runs"] and report["all_recorded_positions_audited"]
            and all(a["status"] == "passed_recorded_states" for a in arms) else "HOLD")
    except Exception as error:
        report.update(status="error", error_type=type(error).__name__, error_message=str(error))
    finally:
        report["inputs_sha256"] = identities
        report["inputs_unchanged"] = all(Path(p).is_file()
            and hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p, h in identities.items())
        if not report["inputs_unchanged"]:
            report["status"] = "inputs_changed"
        report["cost"] = dict(process_wall_seconds=time.perf_counter() - STARTED,
                              process_cpu_seconds=time.process_time() - CPU_STARTED,
                              scope="imports, verification, conversion and all audits; excludes final JSON write")
        write_json(args.output_dir / "SUMMARY.json", report)
    print(json.dumps({k: report[k] for k in ("status", "completed_all_runs", "cost")}), flush=True)
    return 0 if report["status"] == "passed_reconstructed_continuation" else 1


if __name__ == "__main__":
    raise SystemExit(main())

