"""Independent closing audit of actual timing media against quality outputs.

This module was added after protocol freeze for an identified measurement audit.
It never changes the frozen primary evaluation or its policy/observer/thresholds.
Changed timing media are measured separately with the already frozen observer.
"""

import argparse
import json
import os
from pathlib import Path
import time

import numpy as np

from .audit import sha256, write_json
from .facts import action_cost, observed_metrics
from .registration import verify_final_freeze
from .speech import read_pcm
from .stream import verify_output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("timing-run", "evaluation-run", "freeze", "final-protocol", "policies", "qualification",
                 "external-assets", "raw-output", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    verify_final_freeze(args.final_protocol, args.freeze, args.policies, args.qualification)
    timing_path = args.timing_run / "timing_report.json"
    timing = json.loads(timing_path.read_text())
    sources = json.loads((args.freeze / "sources.json").read_text())["roles"]["evaluation"][:16]
    targets = {row["source_id"]: row["fact"] for row in sources}
    expected_keys = {(source["source_id"], scenario, repeat, policy) for source in sources
                     for scenario in range(4) for repeat in range(2)
                     for policy in ("fixed/best_fit", "feedback/17")}
    matrix = {}
    for line in (args.evaluation_run / "cases.jsonl").read_text().splitlines():
        entry = json.loads(line)
        if sha256(entry["case_path"]) != entry["case_sha256"]:
            raise ValueError("Main quality evidence changed")
        case = json.loads(Path(entry["case_path"]).read_text())
        matrix[(case["source_id"], case["scenario"])] = case
    changed, seen, flags_false, wave_false, text_false = [], set(), 0, 0, 0
    for index, row in enumerate(timing["rows"]):
        key = row["source_id"], row["scenario"], row["round"], row["policy"]
        if key not in expected_keys or key in seen:
            raise ValueError("Unexpected or repeated timing census identity")
        seen.add(key)
        output_dir = Path(row["prefix_tts"]["path"]).parent / "committed-output"
        if not output_dir.resolve().is_relative_to(args.timing_run.resolve()):
            raise ValueError("Timing output escapes its actual run")
        actual = verify_output(output_dir)
        if actual != row["output"]:
            raise ValueError("Actual timing media differ from their recorded receipts")
        case = matrix[(row["source_id"], row["scenario"])]
        if row["action"] != case["choices"][row["policy"]]:
            raise ValueError("Timing action differs from the frozen quality action")
        expected = case["outcomes"][row["action"]]["output"]
        wave_equal = actual["wave_sha256"] == expected["wave_sha256"]
        text_equal = actual["text_sha256"] == expected["text_sha256"]
        if wave_equal != row["identical_wave_to_quality_matrix"]:
            raise ValueError("Stored timing identity flag does not describe actual bytes")
        flags_false += not row["identical_wave_to_quality_matrix"]
        wave_false += not wave_equal
        text_false += not text_equal
        if not (wave_equal and text_equal):
            changed.append((index, row, output_dir))
    if seen != expected_keys:
        raise ValueError("Timing audit is missing registered executions")
    rescored, observer = [], None
    if changed:
        from .external import ExternalObserver
        qual = json.loads((args.freeze / "qualification_protocol.json").read_text())
        if sha256(args.external_assets / "manifest.json") != qual["external_assets_sha256"]:
            raise ValueError("Post-audit observer differs from frozen qualification")
        os.sched_setaffinity(0, {sorted(os.sched_getaffinity(0))[-1]})
        args.raw_output.mkdir(parents=True, exist_ok=False)
        observer = ExternalObserver(args.external_assets)
        for index, row, output_dir in changed:
            wav = output_dir / "output.wav"
            observation = observer.observe(wav)
            _, pcm = read_pcm(wav)
            commits = [json.loads(line) for line in (output_dir / "commits.jsonl").read_text().splitlines()]
            physical = len(commits) == 3 and all(np.any(pcm[commit["sample_start"]:commit["sample_stop"]]) for commit in commits)
            metrics = observed_metrics(targets[row["source_id"]], (output_dir / "output.txt").read_text(),
                                       observation["transcript"], physical)
            metrics["net_utility"] = metrics["utility"] - action_cost(row["action"])
            evidence = {"source_id": row["source_id"], "scenario": row["scenario"], "round": row["round"],
                        "policy": row["policy"], "action": row["action"], "observation": observation, "metrics": metrics}
            path = args.raw_output / f"timing-{index:03d}-independent-rescore.json"
            write_json(path, evidence)
            rescored.append({"source_id": row["source_id"], "scenario": row["scenario"], "round": row["round"],
                             "policy": row["policy"], "evidence_sha256": sha256(path), "metrics": metrics})
    result = {"schema": "hepta.abc3.temporal-timing-post-audit.v1", "executions": len(seen),
              "fact_groups": 16, "scenarios": 4, "rounds": 2, "policies": 2, "added_independent_quality_n": 0,
              "stored_wave_flag_false_count": flags_false, "actual_wave_identity_false_count": wave_false,
              "actual_text_identity_false_count": text_false, "all_committed_spans_verified": True,
              "all_actions_match_frozen_matrix": True, "main_quality_transfer_by_exact_identity_valid_for_all": not changed,
              "changed_media_independently_rescored": len(rescored), "rescored": rescored,
              "scope": "Closing media-identity audit; changed outputs are separate timing outcomes, not replacements for primary quality results",
              "frozen_primary_analysis_unchanged": True, "timing_report_sha256": sha256(timing_path),
              "main_case_index_sha256": sha256(args.evaluation_run / "cases.jsonl"),
              "final_protocol_sha256": sha256(args.final_protocol), "audit_source_sha256": sha256(__file__),
              "external_model_load_if_needed": observer.load_receipt if observer else None,
              "wall_ns_before_report": time.perf_counter_ns() - started,
              "cpu_ns_before_report": time.process_time_ns() - cpu}
    write_json(args.output, result)
    print(json.dumps({key: result[key] for key in ("executions", "stored_wave_flag_false_count",
                     "actual_text_identity_false_count", "changed_media_independently_rescored",
                     "main_quality_transfer_by_exact_identity_valid_for_all")}))


if __name__ == "__main__":
    main()
