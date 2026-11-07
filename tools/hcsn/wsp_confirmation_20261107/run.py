"""One frozen candidate construction and single-use confirmation; no adaptive retry."""
import argparse
import gc
import os
from pathlib import Path
import resource
import secrets
import signal
import sys
import time
import traceback

import numpy as np
from scipy.stats import t as student_t

ROOT = Path(__file__).resolve().parent
UPSTREAM = ROOT.parent / "wsp_native_value_20261105/value_edit"
sys.path.insert(0, str(UPSTREAM))

from artifact_io import EventChain, read, save
from vendor import planning as p
from guard import ARMS, FITS, Ledger, digest, file_identity, quality_gate, verify_files
from candidates import construct
from evaluate import generate, history, score_world


def summarize(protocol, records):
    summary, contrasts = {}, []
    for domain in protocol["confirmation"]["domains"]:
        summary[domain] = {}
        for arm in protocol["arms"]:
            per_fit, per_fit_baseline, cpu, latency, calibrations, tails = [], [], [], [], [], []
            for fit in protocol["fits"]:
                rows = [r["arms"] for r in records if r["sample"]["fit"] == fit and r["sample"]["domain"] == domain]
                if len(rows) != protocol["confirmation"]["worlds_per_fit_domain"]:
                    raise ValueError("full planned denominator is required")
                per_fit.append(float(np.mean([r[arm]["utility"] for r in rows])))
                per_fit_baseline.append(float(np.mean([r["C"]["utility"] for r in rows])))
                for row in rows:
                    cpu.append(row[arm]["full_arm_cpu_seconds"])
                    planning = row[arm]["planning"]
                    latency.append(row[arm]["policy_cpu_seconds"] + (planning["full_cold_preparation_cpu_seconds"] if planning else 0.))
                    calibrations.append(row[arm]["posterior_probability_mse"])
                    tails.append(row[arm]["utility"])
            delta = np.asarray(per_fit) - per_fit_baseline
            half = student_t.ppf(.975, 4) * delta.std(ddof=1) / np.sqrt(5)
            summary[domain][arm] = {"mean": float(np.mean(per_fit)), "delta_C": float(delta.mean()),
                "per_fit": per_fit, "descriptive_interval": [float(delta.mean()-half), float(delta.mean()+half)],
                "mean_posterior_probability_mse": float(np.mean(calibrations)),
                "world_utility_p05_descriptive": float(np.quantile(tails, .05)),
                "cold_policy_cpu_mean": float(np.mean(latency)), "cold_policy_cpu_p95": float(np.quantile(latency, .95)),
                "full_evaluator_and_preservation_cpu": float(np.sum(cpu))}
            if arm == "E":
                half = student_t.ppf(1 - .05 / 4, 4) * delta.std(ddof=1) / np.sqrt(5)
                contrasts.append({"contrast": "E-C " + domain, "n_fits": 5, "delta": float(delta.mean()),
                    "familywise_interval": [float(delta.mean()-half), float(delta.mean()+half)]})
    return summary, contrasts


def main(args):
    start, wall = time.process_time(), time.perf_counter()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    protocol, protocol_sha = read(args.protocol), file_identity(args.protocol)["sha256"]
    if (protocol["status"] != "FROZEN_BEFORE_CANDIDATES_AND_CONFIRMATION"
            or tuple(protocol["fits"]) != FITS or tuple(protocol["arms"]) != ARMS):
        raise ValueError("the complete frozen experiment is required")
    caps = protocol["resources"]
    def timeout(*_args):
        raise TimeoutError("fixed resource cap reached; keep all failures and denominators")
    signal.signal(signal.SIGALRM, timeout)
    signal.signal(signal.SIGXCPU, timeout)
    signal.alarm(caps["wall_seconds"])
    resource.setrlimit(resource.RLIMIT_CPU, (caps["cpu_seconds"], caps["cpu_seconds"] + 5))
    def budget():
        if time.process_time()-start > caps["cpu_seconds"] or time.perf_counter()-wall > caps["wall_seconds"]:
            timeout()
        if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024) > caps["rss_limit_bytes"]:
            raise MemoryError("declared measured RSS limit exceeded")
    ledger, events, stage = Ledger(args.ledger), EventChain(out), "source_identity"
    save(out / "STARTED.json", {"protocol_sha256": protocol_sha, "source_commit": protocol["source_commit"],
        "logical_cpus": os.cpu_count(), "numeric_threads": {k: os.getenv(k) for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS")},
        "scope": protocol["scope"]})
    try:
        if any(os.getenv(key) != "1" for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")):
            raise ValueError("all declared numerical thread controls must equal one")
        verify_files(ROOT.parents[2], protocol["source_files"])
        full_ctx = p.load_context(UPSTREAM / "vendor/frozen_joint")
        known, schedule_hash, history_report = history(UPSTREAM)
        save(out / "HISTORY_EXCLUSION.json", history_report)
        fits = {}
        stage = "candidate_construction"
        for fit in protocol["fits"]:
            fits[fit] = construct(UPSTREAM, out, fit, protocol, protocol_sha, full_ctx, budget)
            print(__import__("json").dumps({"stage": stage, "fit": fit,
                "alphas": {name: path["selected_alpha"] for name, path in fits[fit]["record"]["paths"].items()},
                "cpu": time.process_time()-start}), flush=True)
            gc.collect()
        candidate_index = {str(fit): file_identity(out / f"fit_{fit}_CANDIDATES.json.gz") for fit in fits}
        cohort_sha = save(out / "ALL_CANDIDATES_FROZEN.json", candidate_index)
        events.add("all_candidates_frozen", {"sha256": cohort_sha, "path": "ALL_CANDIDATES_FROZEN.json"})
        ledger.freeze(protocol_sha, cohort_sha, known)
        stage = "fresh_confirmation_reservation"
        seed = secrets.token_hex(32)
        seed_sha = save(out / "EVALUATOR_SEED.json", {"seed": seed, "candidate_cohort_sha256": cohort_sha,
            "generated_after_candidate_freeze": True, "independent_authority_verified": False})
        events.add("evaluator_seed_generated", {"path": "EVALUATOR_SEED.json", "sha256": seed_sha})
        samples = generate(full_ctx, protocol, seed, schedule_hash)
        sample_sha = save(out / "CONFIRMATION_SAMPLES.json.gz", samples)
        ledger.reserve(protocol_sha, cohort_sha, samples)
        events.add("cohort_consumed_before_scoring", {"path": "CONFIRMATION_SAMPLES.json.gz", "sha256": sample_sha,
            "worlds": len(samples), "planned_arm_evaluations": len(samples)*len(ARMS)})
        stage, records = "confirmation", []
        for sample in samples:
            def claim(arm):
                ledger.claim(protocol_sha, sample["sha256"], sample["fit"], arm)
            def record(arm, result, cpu, elapsed, failed):
                ledger.record(protocol_sha, sample["sha256"], sample["fit"], arm, result, cpu, elapsed, failed)
            results = score_world(full_ctx, sample, fits[sample["fit"]], protocol, budget, claim, record)
            record_row = {"sample": {k: v for k, v in sample.items() if k != "public"}, "arms": results}
            save(out / f"scores/{sample['fit']}_{sample['domain']}_{sample['index']:03}.json.gz", record_row)
            records.append(record_row)
            if (sample["index"]+1) % 32 == 0:
                print(__import__("json").dumps({"stage": stage, "fit": sample["fit"], "domain": sample["domain"],
                                               "cpu": time.process_time()-start}), flush=True)
        summary, contrasts = summarize(protocol, records)
        counts = ledger.counts(protocol_sha)
        if counts != {"COMPLETE": len(samples)*len(ARMS)}:
            raise ValueError("incomplete cohort, no quality qualification")
        verify_files(ROOT.parents[2], protocol["source_files"])
        result = {"protocol_sha256": protocol_sha, "cohort_sha256": cohort_sha, "summary": summary,
            "primary_contrasts": contrasts, "ledger_counts": counts,
            "new_worlds": len(samples), "reused_fits": len(FITS), "new_training_fits": 0,
            "quality_gate": quality_gate(contrasts, {"main_task": True, "preservation": False,
                "ood": True, "calibration": True, "latency": True, "failures": True,
                "data_freshness": True, "source_coverage": True, "independent_confirmation": False,
                "owner_recovery": False}, protocol["unmeasured_costs"]),
            "costs": {"worker_internal_cpu_before_final_writes": time.process_time()-start,
                "worker_internal_wall_before_final_writes": time.perf_counter()-wall,
                "agent_input_tokens": None, "agent_output_tokens": None, "energy_joules": None,
                "physical_total_source": "outer PROCESS_RECEIPT.json; nested component times must not be added again"},
            "historical_TEST_used_for_search": False, "source_unchanged": True,
            "production_eligible": False, "live_market_gain_qualified": False,
            "verification_pending": True, "scope": protocol["scope"]}
        result_sha = save(out / "RESULTS.json", result)
        events.add("results_frozen", {"path": "RESULTS.json", "sha256": result_sha})
        print(__import__("json").dumps({"stage": "complete", "contrasts": contrasts, "production_eligible": False}), flush=True)
        return 0
    except BaseException as error:
        save(out / "FAILED.json", {"stage": stage, "type": type(error).__name__, "error": str(error),
            "traceback": traceback.format_exc(), "cpu": time.process_time()-start, "wall": time.perf_counter()-wall,
            "ledger_counts": ledger.counts(protocol_sha), "rerun_with_same_confirmation_allowed": False})
        traceback.print_exc()
        return 1
    finally:
        ledger.close()
        signal.alarm(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    sys.exit(main(parser.parse_args()))
