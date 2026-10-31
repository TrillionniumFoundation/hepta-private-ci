"""Real acoustic cue acquisition and two irreversible output decisions."""

import json
from pathlib import Path
import time

from experiments.multimodal_output_portfolio.abc_next.temporal.audit import sha256, write_json
from experiments.multimodal_output_portfolio.abc_next.temporal.stream import AppendOnlyOutput
from .state import CueOwner, Frame, PREFIX, chunk_text, incorporate, initial_frame, metrics
from .tasks import parse, sentence


def clocks(wall, cpu):
    return {"wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu}


def execute(backend, source, scenario, template, directory, mode, route=None, policy=None,
            external=None):
    """Controller never receives the owner, source, target, or future cue."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    owner = CueOwner(source, scenario)
    frame = initial_frame(owner.initial(), template)
    if mode == "initial":
        route = policy.initial_route(frame)
    if mode not in ("fixed", "initial", "feedback", "matrix"):
        raise ValueError("Unsupported execution mode")
    if mode in ("fixed", "initial", "matrix") and route not in ((0, 0), (0, 1), (1, 0), (1, 1)):
        raise ValueError("A bounded initial route is required")
    write_json(directory / "initial-route.json", {"mode": mode, "route": route,
               "initial": frame.initial, "before_acoustic_cue": True})
    prefix = backend.synthesize(PREFIX, directory / "prefix.wav")
    output = AppendOnlyOutput(directory / "output", prefix["sample_rate"])
    output.append(PREFIX, directory / "prefix.wav", "neutral_prefix_before_cue")
    first_commit_ns = time.perf_counter_ns()
    acquisitions, frames, choices, prefix_probes, decisions = [], [], [], [], []

    def acquire(index, current):
        path = directory / f"cue-{index}.wav"
        if path.exists():
            raise ValueError("Acoustic observation existed before acquisition")
        released_ns = time.perf_counter_ns()
        cue = owner.release(index)
        # Cue synthesis is an environment observation operation, not output TTS.
        acoustic = backend.synthesize(sentence(cue, "compact", template), path)
        observation = backend.observe(path)
        acquisitions.append({"cue_index": index, "released_ns": released_ns,
                             "tts": acoustic, "observation": observation})
        return incorporate(current, observation, index)

    frame = acquire(1, frame)
    for stage in range(2):
        state = frame.detached()
        state.update(stage=stage, elapsed_seconds=(time.perf_counter_ns() - wall) / 1e9)
        frame = Frame(**state)
        frames.append(frame.detached())
        decide_wall, decide_cpu = time.perf_counter_ns(), time.process_time_ns()
        action = policy.feedback_action(frame) if mode == "feedback" else route[stage]
        decision = {"stage": stage, "action": "acquire" if action else "commit",
                    "public_frame": frame.detached(), "decision_ns": time.perf_counter_ns(),
                    "optional_cue_exists": (directory / f"cue-{stage + 2}.wav").exists(),
                    "policy_cost": clocks(decide_wall, decide_cpu)}
        if decision["optional_cue_exists"]:
            raise ValueError("Future cue leaked before action")
        write_json(directory / f"decision-{stage}.json", decision)
        decisions.append(decision)
        choices.append(action)
        if action:
            frame = acquire(stage + 2, frame)
        text = chunk_text(frame)
        chunk = directory / f"chunk-{stage}.wav"
        backend.synthesize(text, chunk)
        output.append(text, chunk, f"semantic_chunk_{stage}")
        if stage == 0:
            state = frame.detached()
            state["first_action"] = action
            if mode == "matrix" or (mode == "feedback" and policy.needs_prefix_probe()):
                # Actual committed speech is observed before the second gate.
                observation = backend.observe(chunk)
                prefix_probes.append(observation)
                state["previous_audio_fact"] = parse(observation["transcript"])
            frame = Frame(**state)
    verification = output.finish()
    actual_text = (directory / "output" / "output.txt").read_text()
    generation_cost = clocks(wall, cpu)
    output_path = directory / "output" / "output.wav"
    # Neither terminal observer is available until both decisions/output close.
    online = backend.observe(output_path)
    offline = external.observe(output_path) if external is not None else None
    physical = verification["commit_count"] == 3 and verification["exact_committed_span_readback"]
    record = {"source_id": source["source_id"], "scenario": scenario, "template": template,
              "feedback_variant": policy.variant if mode == "feedback" else None,
              "mode": mode, "route": choices, "frames": frames, "decisions": decisions,
              "first_commit_ns": first_commit_ns, "generation_cost": generation_cost,
              "initial_route_sha256": sha256(directory / "initial-route.json"),
              "decision_sha256": [sha256(directory / f"decision-{stage}.json") for stage in range(2)],
              "acquisitions": acquisitions, "prefix_probes": prefix_probes,
              "verification": verification, "actual_text": actual_text,
              "online_observation": online, "offline_observation": offline,
              "online_metrics": metrics(source["fact"], actual_text, online["transcript"], physical),
              "offline_metrics": metrics(source["fact"], actual_text, offline["transcript"], physical) if offline else None,
              "total_case_cost": clocks(wall, cpu)}
    write_json(directory / "case.json", record)
    # Remove duplicate synthesis intermediates only after exact committed spans
    # and complete observer-input hashes have been checked and recorded.
    for name in ("prefix.wav", "chunk-0.wav", "chunk-1.wav"):
        (directory / name).unlink()
    return record
