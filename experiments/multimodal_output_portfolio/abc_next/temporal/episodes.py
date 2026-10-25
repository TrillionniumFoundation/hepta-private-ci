"""Actually execute forked text/speech paths after an irreversible prefix.

Potential paths share the already committed prefix and internal generated draft.
Each future candidate is freshly synthesized. No prior-source speech is copied.
Candidate matrix timings are component costs, not fictitious end-to-end latency.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

from .facts import (ACTIONS, GENERATOR_ACTIONS, PREFIX, action_cost, action_fact,
                    canonical, observed_metrics, owner_public_frame, sentences, update_probe)
from .audit import write_json
from .speech import SpeechBackend, sha256
from .stream import AppendOnlyOutput, verify_output


def clocks(started, cpu):
    return {"wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu}


def execute_case(backend, source, scenario, directory, policies=None, actions=GENERATOR_ACTIONS,
                 external=None):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    directory.mkdir(parents=True, exist_ok=False)
    # Private owner alone uses the hidden target to construct noisy sensor values.
    frame = owner_public_frame(source["fact"], source["source_id"], scenario)
    one_shot = policies.initial_decisions(frame) if policies else {}
    write_json(directory / "initial_decision.json", {"policies": one_shot,
               "initial": frame.initial, "quality": frame.initial_quality,
               "happened_before_probe_and_fresh_release": True})
    prefix_tts = backend.synthesize(PREFIX, directory / "prefix.wav")
    prefix = AppendOnlyOutput(directory / "committed-prefix", prefix_tts["sample_rate"])
    prefix.append(PREFIX, directory / "prefix.wav", "irreversible_neutral_prefix")
    prefix_receipt = prefix.finish()
    prefix_committed_ns = time.perf_counter_ns()
    draft_text = " ".join(sentences(frame.initial))
    draft_tts = backend.synthesize(draft_text, directory / "internal-draft.wav")
    probe = backend.observe(directory / "internal-draft.wav")
    frame = update_probe(frame, probe)
    fresh_released_ns = time.perf_counter_ns()
    decision_start, decision_cpu = time.perf_counter_ns(), time.process_time_ns()
    choices = policies.feedback_decisions(frame, one_shot) if policies else {}
    choice_cost = clocks(decision_start, decision_cpu)
    decision = {"public_frame": frame.serialized(), "choices": choices,
                "initial_decision_sha256": sha256(directory / "initial_decision.json"),
                "prefix_receipt": prefix_receipt, "prefix_committed_ns": prefix_committed_ns,
                "fresh_released_ns": fresh_released_ns, "decision_done_ns": time.perf_counter_ns(),
                "probe": probe, "policy_cost": choice_cost,
                "future_candidate_audio_exists": False, "target_in_public_frame": False}
    write_json(directory / "decision.json", decision)
    # The detached decision is durable before any final candidate is generated.
    common_cost = clocks(started, cpu)
    outcomes = {}
    for action in actions:
        branch_start, branch_cpu = time.perf_counter_ns(), time.process_time_ns()
        branch = directory / action
        branch.mkdir()
        text_chunks = sentences(action_fact(frame, action))
        output = AppendOnlyOutput(branch / "committed-output", prefix_tts["sample_rate"])
        output.append(PREFIX, directory / "committed-prefix" / "output.wav", "fork_of_committed_prefix")
        tts_calls = []
        for index, text in enumerate(text_chunks):
            wav = branch / f"future-{index}.wav"
            tts_calls.append(backend.synthesize(text, wav, 1.2 if action.endswith("slow") else 1.0))
            output.append(text, wav, f"future_semantic_chunk_{index}")
        verification = output.finish()
        generation_cost = clocks(branch_start, branch_cpu)
        final_path = branch / "committed-output" / "output.wav"
        actual_text = (branch / "committed-output" / "output.txt").read_text()
        online = backend.observe(final_path)
        independent = external.observe(final_path) if external else None
        physical = verification["commit_count"] == 3 and all(row["peak_absolute_pcm"] > 0 for row in tts_calls)
        # Immutable prefix identity is tested against original PCM/text commits.
        prefix_row = json.loads((directory / "committed-prefix" / "commits.jsonl").read_text().splitlines()[0])
        branch_row = json.loads((branch / "committed-output" / "commits.jsonl").read_text().splitlines()[0])
        if any(prefix_row[key] != branch_row[key] for key in ("pcm_sha256", "text_sha256")):
            raise ValueError("Candidate rewrote already committed text/audio")
        online_metrics = observed_metrics(source["fact"], actual_text, online["transcript"], physical)
        online_metrics["net_utility"] = online_metrics["utility"] - action_cost(action)
        independent_metrics = None
        if independent:
            independent_metrics = observed_metrics(source["fact"], actual_text, independent["transcript"], physical)
            independent_metrics["net_utility"] = independent_metrics["utility"] - action_cost(action)
        row = {"action": action, "proxy_action_cost": action_cost(action), "actual_text": actual_text,
               "output": verification, "tts_calls": tts_calls, "branch_generation_cost": generation_cost,
               "online_terminal_observation": online, "online_metrics": online_metrics,
               "external_terminal_observation": independent, "external_metrics": independent_metrics,
               "physical_complete": physical, "original_prefix_preserved": True,
               "online_component_cost": {key: common_cost[key] + generation_cost[key]
                                         for key in ("wall_ns", "cpu_ns")},
               "terminal_scoring_cost_excluded_from_online": True,
               "decision_sha256": sha256(directory / "decision.json")}
        write_json(branch / "outcome.json", row)
        outcomes[action] = row
    record = {"source_id": source["source_id"], "scenario": scenario, "public_frame": frame.serialized(),
              "choices": choices, "common_cost": common_cost, "prefix_tts": prefix_tts,
              "draft_tts": draft_tts, "online_probe": probe, "policy_cost": choice_cost,
              "outcomes": outcomes, "entire_candidate_matrix_cost": clocks(started, cpu),
              "terminal_whisper_never_used_for_decision": True,
              "decision_sha256": sha256(directory / "decision.json")}
    write_json(directory / "case.json", record)
    return record


def run_matrix(args):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    args.output.mkdir(parents=True, exist_ok=False)
    freeze = json.loads((args.freeze / "qualification_protocol.json").read_text())
    if sha256(args.freeze / "sources.json") != freeze["source_manifest_sha256"]:
        raise ValueError("Frozen source partition changed")
    if sha256(args.assets / "manifest.json") != freeze["tts_online_assets_sha256"]:
        raise ValueError("Qualified generator/online observer identity changed")
    qualification = json.loads(args.qualification.read_text())
    if not qualification["passed"] or qualification["protocol_sha256"] != sha256(args.freeze / "qualification_protocol.json"):
        raise ValueError("Observer qualification has not passed frozen gates")
    if args.role == "evaluation":
        from .policy import PolicyBundle
        from .registration import verify_final_freeze
        from .external import ExternalObserver
        final = verify_final_freeze(args.final_protocol, args.freeze, args.policies, args.qualification)
        if sha256(args.external_assets / "manifest.json") != freeze["external_assets_sha256"]:
            raise ValueError("Qualified offline observer identity changed")
        policies = PolicyBundle.load(args.policies)
        external = ExternalObserver(args.external_assets)
        actions = ACTIONS
    else:
        final, policies, external, actions = None, None, None, GENERATOR_ACTIONS
    backend = SpeechBackend(args.assets)
    sources = json.loads((args.freeze / "sources.json").read_text())["roles"][args.role]
    write_json(args.output / "run_start.json", {"role": args.role, "sources": len(sources),
               "scenarios": 4, "actions": actions, "backend": backend.load_receipt,
               "external": external.load_receipt if external else None,
               "final_protocol_sha256": sha256(args.final_protocol) if final else None,
               "qualification_sha256": sha256(args.qualification), "source_manifest_sha256": sha256(args.freeze / "sources.json")})
    with (args.output / "cases.jsonl").open("x") as index_file:
        for index, source in enumerate(sources):
            for scenario in range(4):
                directory = args.output / f"source-{index:03d}" / f"scenario-{scenario}"
                record = execute_case(backend, source, scenario, directory, policies, actions, external)
                index_file.write(json.dumps({"source_id": source["source_id"], "scenario": scenario,
                                            "case_path": str(directory / "case.json"),
                                            "case_sha256": sha256(directory / "case.json")}) + "\n")
                index_file.flush()
            print(json.dumps({"role": args.role, "source_group": index + 1, "of": len(sources)}), flush=True)
    write_json(args.output / "run_complete.json", {"role": args.role, "source_groups": len(sources),
               "cases": len(sources) * 4, "paths": len(sources) * 4 * len(actions),
               "whole_process_before_report": clocks(started, cpu),
               "case_index_sha256": sha256(args.output / "cases.jsonl")})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=("fit", "evaluation"), required=True)
    for name in ("assets", "freeze", "qualification", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("external-assets", "final-protocol", "policies"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    run_matrix(args)


if __name__ == "__main__":
    main()
