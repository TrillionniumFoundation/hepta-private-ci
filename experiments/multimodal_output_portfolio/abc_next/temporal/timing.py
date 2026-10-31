"""Sequential, actual selected-policy generation latency with all online costs."""

import argparse
import json
import os
from pathlib import Path
import resource
import time

import numpy as np

from .facts import (GENERATOR_ACTIONS, PREFIX, action_fact, owner_public_frame,
                    sentences, update_probe)
from .policy import PolicyBundle, predict
from .audit import write_json
from .registration import verify_final_freeze
from .speech import SpeechBackend, sha256
from .stream import AppendOnlyOutput


def selected_episode(backend, policies, source, scenario, policy_name, directory):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    directory.mkdir(parents=True, exist_ok=False)
    frame = owner_public_frame(source["fact"], source["source_id"], scenario)
    prefix = backend.synthesize(PREFIX, directory / "prefix.wav")
    output = AppendOnlyOutput(directory / "committed-output", prefix["sample_rate"])
    output.append(PREFIX, directory / "prefix.wav", "irreversible_neutral_prefix")
    prefix_commit_done_ns = time.perf_counter_ns()
    draft = backend.synthesize(" ".join(sentences(frame.initial)), directory / "draft.wav")
    probe = backend.observe(directory / "draft.wav")
    frame = update_probe(frame, probe)
    decision_start, decision_cpu = time.perf_counter_ns(), time.process_time_ns()
    if policy_name == "fixed/best_fit":
        action = policies.payload["best_fixed_action"]
    elif policy_name == "feedback/17":
        model = next(row for row in policies.payload["models"]["feedback"] if row["seed"] == 17)
        action = GENERATOR_ACTIONS[int(np.argmin(predict(model, frame, "feedback")))]
    else:
        raise ValueError("Unregistered timing policy")
    decision_cost = {"wall_ns": time.perf_counter_ns() - decision_start,
                     "cpu_ns": time.process_time_ns() - decision_cpu}
    write_json(directory / "decision.json", {"policy": policy_name, "action": action,
               "public_frame": frame.serialized(), "prefix_committed_ns": prefix_commit_done_ns,
               "no_future_output_yet": True})
    calls = []
    for index, text in enumerate(sentences(action_fact(frame, action))):
        path = directory / f"future-{index}.wav"
        calls.append(backend.synthesize(text, path, 1.2 if action.endswith("slow") else 1.0))
        output.append(text, path, f"future_semantic_chunk_{index}")
    verified = output.finish()
    # Stop only after real durable text/WAV and exact committed-span verification.
    wall_ns, cpu_ns = time.perf_counter_ns() - started, time.process_time_ns() - cpu
    row = {"source_id": source["source_id"], "scenario": scenario, "policy": policy_name,
           "action": action, "end_to_end_wall_ns": wall_ns, "end_to_end_cpu_ns": cpu_ns,
           "time_to_first_committed_output_ns": prefix_commit_done_ns - started,
           "rendered_audio_duration_seconds": verified["duration_seconds"],
           "prefix_tts": prefix, "draft_tts": draft, "online_probe": probe,
           "decision_cost": decision_cost, "future_tts": calls, "output": verified,
           "offline_final_asr_included": False, "all_online_costs_included": True,
           "fixed_also_pays_common_probe": True,
           "counterfactual_optimized_fixed_without_probe_measured": False}
    write_json(directory / "timing.json", row)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("assets", "freeze", "final-protocol", "policies", "qualification", "evaluation-run", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    protocol = verify_final_freeze(args.final_protocol, args.freeze, args.policies, args.qualification)
    qualification_protocol = json.loads((args.freeze / "qualification_protocol.json").read_text())
    if sha256(args.assets / "manifest.json") != qualification_protocol["tts_online_assets_sha256"]:
        raise ValueError("Timing backend differs from the qualified generator")
    os.sched_setaffinity(0, {sorted(os.sched_getaffinity(0))[-1]})
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    backend, policies = SpeechBackend(args.assets), PolicyBundle.load(args.policies)
    sources = json.loads((args.freeze / "sources.json").read_text())["roles"]["evaluation"][:16]
    matrix = {}
    for line in (args.evaluation_run / "cases.jsonl").read_text().splitlines():
        entry = json.loads(line)
        case = json.loads(Path(entry["case_path"]).read_text())
        matrix[(case["source_id"], case["scenario"])] = case
    load_start = os.getloadavg()
    rows = []
    for group, source in enumerate(sources):
        for scenario in range(4):
            for repeat in range(2):
                names = ["fixed/best_fit", "feedback/17"]
                if (group + scenario + repeat) % 2:
                    names.reverse()
                for name in names:
                    directory = args.output / f"g{group:02d}-s{scenario}-r{repeat}-{name.replace('/', '_')}"
                    row = selected_episode(backend, policies, source, scenario, name, directory)
                    expected = matrix[(source["source_id"], scenario)]
                    if row["action"] != expected["choices"][name]:
                        raise ValueError("Sequential timing policy differs from registered quality action")
                    expected_wave = expected["outcomes"][row["action"]]["output"]["wave_sha256"]
                    row["identical_wave_to_quality_matrix"] = row["output"]["wave_sha256"] == expected_wave
                    row["round"] = repeat
                    rows.append(row)
        print(json.dumps({"timing_group": group + 1, "of": len(sources)}), flush=True)
    summary = {}
    for name in ("fixed/best_fit", "feedback/17"):
        summary[name] = {}
        for clock in ("wall", "cpu"):
            values = [row[f"end_to_end_{clock}_ns"] / 1e6 for row in rows if row["policy"] == name]
            summary[name][clock + "_ms"] = {"mean": float(np.mean(values)),
                                            "p50": float(np.quantile(values, .5)),
                                            "p95": float(np.quantile(values, .95))}
        for metric, label, divisor in (("time_to_first_committed_output_ns", "first_durable_output_ms", 1e6),
                                        ("rendered_audio_duration_seconds", "audio_duration_seconds", 1)):
            values = [row[metric] / divisor for row in rows if row["policy"] == name]
            summary[name][label] = {"mean": float(np.mean(values)), "p50": float(np.quantile(values, .5)),
                                    "p95": float(np.quantile(values, .95))}
    report = {"rows": rows, "summary": summary, "backend_load": backend.load_receipt,
              "run_wall_ns_before_report": time.perf_counter_ns() - started,
              "run_cpu_ns_before_report": time.process_time_ns() - cpu,
              "load_average_start": load_start, "load_average_end": os.getloadavg(),
              "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              "model_threads": 1, "cpu_affinity_count": len(os.sched_getaffinity(0)),
              "cpu_affinity": sorted(os.sched_getaffinity(0)),
              "scope": "shared container; load average recorded, no isolated-hardware or deployment latency guarantee",
              "latency_endpoint": "durable complete WAV and text, not actual speaker playback or network delivery",
              "independent_quality_n_added": 0, "all_repeats_retained": True,
              "final_protocol_sha256": sha256(args.final_protocol)}
    write_json(args.output / "timing_report.json", report)
    print(json.dumps({"summary": summary, "report_sha256": sha256(args.output / "timing_report.json")}))


if __name__ == "__main__":
    main()
