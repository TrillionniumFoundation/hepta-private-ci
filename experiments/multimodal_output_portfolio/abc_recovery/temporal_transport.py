"""Causal finite-buffer packet restoration with hidden network futures.

The source clock in an arrived packet header is public. This model does not infer
unknown physiological AV synchronization or generate new speech/video content.
"""

from dataclasses import dataclass
import hashlib
import math
import random
import time

import numpy as np


RATE, FRAME_TICKS, QUANTUM = 44100, 1764, 882
FRAMES, AUDIO_SAMPLES = 75, 131328
CHANNELS = ("video", "audio")
FIXED = ("fixed_timeout_80ms", "fixed_timeout_240ms")
FEEDBACK = "learned_causal_timeout"


def episode_seed(source_id, scenario):
    raw = f"hepta-causal-av-stream-v1|{source_id}|{scenario}".encode()
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") % (2 ** 63)


def release_ticks(channel, index, samples=AUDIO_SAMPLES):
    end = (index + 1) * FRAME_TICKS
    return min(end, samples) if channel == "audio" else end


def network_events(seed, scenario, frame_count=FRAMES, audio_samples=AUDIO_SAMPLES):
    """Offline environment event table; never passed to a policy."""
    if scenario not in range(4):
        raise ValueError("Unknown registered network family")
    rng = random.Random(seed)
    affected = rng.choice(CHANNELS)
    burst_start = rng.randrange(8, 58)
    events = []
    for index in range(frame_count):
        for channel in CHANNELS:
            jitter, drop_draw, late_draw = rng.choice((0, 20, 40)), rng.random(), rng.random()
            delay, dropped = 20 + jitter, False
            inside_burst = channel == affected and burst_start <= index < burst_start + 6
            if scenario == 1 and channel == affected:
                delay += 120 + 40 * inside_burst
            elif scenario == 2:
                dropped = drop_draw < .08 or (inside_burst and index < burst_start + 3)
            elif scenario == 3:
                dropped = drop_draw < .02
                delay += 160 * (late_draw < .20 or inside_burst)
            released = release_ticks(channel, index, audio_samples)
            events.append({"channel": channel, "index": index, "source_pts_ticks": index * FRAME_TICKS,
                           "release_ticks": released, "arrival_ticks": None if dropped else released + delay * RATE // 1000,
                           "environment_dropped": dropped})
    return events


@dataclass(frozen=True)
class PublicState:
    now_ticks: int
    index: int
    source_release_ticks: int
    video_present: bool
    audio_present: bool
    observed_video_delays: tuple
    observed_audio_delays: tuple
    arrived_headers: tuple


def decide(state, policy, parameters=None):
    """Only the current public prefix is accepted; no environment/seed argument."""
    if state.video_present and state.audio_present:
        return "commit_current_pair"
    if policy in FIXED:
        limit_ms = 80 if policy == FIXED[0] else 240
    elif policy == FEEDBACK:
        if parameters is None:
            raise ValueError("Feedback requires frozen fit parameters")
        observed = state.observed_video_delays + state.observed_audio_delays
        maximum_ms = max(observed, default=0) * 1000 / RATE
        limit_ms = min(240, max(parameters["base_ms"], maximum_ms + parameters["margin_ms"]))
    else:
        raise ValueError("Policy outside the prospectively registered set")
    deadline = state.source_release_ticks + round(limit_ms * RATE / 1000)
    return "wait_20ms" if state.now_ticks < deadline else "commit_current_pair"


def simulate(events, policy, parameters=None, frame_count=FRAMES, audio_samples=AUDIO_SAMPLES, commit=None):
    """Execute ordered commits; later arrivals can never repair the committed prefix."""
    wall_start, cpu_start = time.perf_counter(), time.process_time()
    arrival_order = sorted((event for event in events if event["arrival_ticks"] is not None),
                           key=lambda event: (event["arrival_ticks"], event["index"], event["channel"]))
    cursor, now, observed, available = 0, 0, {channel: [] for channel in CHANNELS}, {}
    masks = {channel: [] for channel in CHANNELS}
    commits, trace, policy_wall, policy_cpu = [], [], 0.0, 0.0
    for index in range(frame_count):
        released = release_ticks("video", index, audio_samples)
        now = max(now, released)
        for step in range(13):
            while cursor < len(arrival_order) and arrival_order[cursor]["arrival_ticks"] <= now:
                arrived = arrival_order[cursor]
                cursor += 1
                channel = arrived["channel"]
                observed[channel].append(arrived["arrival_ticks"] - arrived["release_ticks"])
                observed[channel] = observed[channel][-8:]
                if arrived["index"] >= index:
                    available[(channel, arrived["index"])] = {
                        name: arrived[name] for name in ("channel", "index", "source_pts_ticks", "release_ticks", "arrival_ticks")}
            headers = tuple(tuple(value[key] for key in ("channel", "index", "source_pts_ticks", "release_ticks", "arrival_ticks"))
                            for _, value in sorted(available.items()))
            state = PublicState(now, index, released, ("video", index) in available,
                                ("audio", index) in available, tuple(observed["video"]),
                                tuple(observed["audio"]), headers)
            wall, cpu = time.perf_counter(), time.process_time()
            action = decide(state, policy, parameters)
            policy_wall += time.perf_counter() - wall
            policy_cpu += time.process_time() - cpu
            trace.append({"index": index, "now_ticks": now, "action": action,
                          "public_state": dict(state.__dict__)})
            if action == "commit_current_pair":
                for channel in CHANNELS:
                    masks[channel].append((channel, index) in available)
                    available.pop((channel, index), None)
                commits.append(now)
                if commit is not None:
                    commit(index, {channel: masks[channel][-1] for channel in CHANNELS}, now)
                break
            now = min(now + QUANTUM, released + 12 * QUANTUM)
        else:
            raise RuntimeError("Causal action budget exceeded")
    video_q = sum(masks["video"]) / frame_count
    audio_lengths = [max(0, min(FRAME_TICKS, audio_samples - index * FRAME_TICKS)) for index in range(frame_count)]
    audio_q = sum(length for length, present in zip(audio_lengths, masks["audio"]) if present) / audio_samples
    delivery = [(commit - (index + 1) * FRAME_TICKS) / RATE for index, commit in enumerate(commits)]
    return {"policy": policy, "parameters": parameters, "delivered": masks, "commit_ticks": commits,
            "q_video": video_q, "q_audio": audio_q, "joint_completion": video_q * audio_q,
            "valid_alignment_coverage": sum(a and v for a, v in zip(masks["audio"], masks["video"])) / frame_count,
            "simulated_delivery_latency_seconds": delivery, "mean_simulated_delivery_latency_seconds": float(np.mean(delivery)),
            "public_trace": trace, "committed_slots": frame_count,
            "actual_cost": {"simulator_wall_seconds": time.perf_counter() - wall_start,
                            "simulator_cpu_seconds": time.process_time() - cpu_start,
                            "policy_wall_seconds": policy_wall, "policy_cpu_seconds": policy_cpu}}


def loss(q_video, q_audio, clock_error_seconds, mean_delivery_seconds, alignment_coverage=1.0):
    clock_penalty = 1 - alignment_coverage + alignment_coverage * min((clock_error_seconds or 0) / .040, 1)
    return (.55 * (1 - q_video * q_audio) + .25 * clock_penalty
            + .20 * mean_delivery_seconds / .240)


def risk_loss(values, eta=4.0):
    values = np.asarray(values, dtype=np.float64)
    scaled = eta * values
    maximum = float(scaled.max())
    return (maximum + math.log(float(np.exp(scaled - maximum).mean()))) / eta


def fit_policy(sources):
    """Fit finite timeouts on a role-checked source census; no media claims here."""
    if not sources or any(source["role"] != "fit" for source in sources):
        raise ValueError("Temporal policy fitting only accepts the registered fit role")
    candidates = [(name, None) for name in FIXED]
    candidates += [(FEEDBACK, {"base_ms": base, "margin_ms": margin})
                   for base in (80, 120, 160) for margin in (0, 40, 80)]
    records = []
    for policy, parameters in candidates:
        cells = []
        for source in sources:
            for scenario, seed in enumerate(source["scenario_seeds"]):
                if seed != episode_seed(source["source_id"], scenario):
                    raise ValueError("Episode seed differs from prospective source registration")
                result = simulate(network_events(seed, scenario), policy, parameters)
                value = loss(result["q_video"], result["q_audio"], 0, result["mean_simulated_delivery_latency_seconds"],
                             result["valid_alignment_coverage"])
                cells.append({"source_id": source["source_id"], "speaker": source["speaker"],
                              "scenario": scenario, "seed": seed, "loss": value, "result": result})
        records.append({"policy": policy, "parameters": parameters, "risk_loss": risk_loss([cell["loss"] for cell in cells]),
                        "cells": cells})
    fixed = min(records[:2], key=lambda row: (row["risk_loss"], row["policy"]))
    feedback = min(records[2:], key=lambda row: (row["risk_loss"], row["parameters"]["base_ms"], row["parameters"]["margin_ms"]))
    return {"feedback_parameters": feedback["parameters"], "fixed_comparison": fixed["policy"],
            "feedback_fit_risk_loss": feedback["risk_loss"], "fixed_fit_risk_loss": fixed["risk_loss"],
            "source_groups": [source["speaker"] for source in sources], "full_candidate_records": records,
            "fit_uses_transport_clock_zero_pending_codec_qualification": True}
