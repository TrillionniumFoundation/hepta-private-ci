"""Static typed-address contract baseline, with no latent dynamics or learning."""

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np

from .law import Law
from .planner import BeliefMemory


def run_baseline(episodes=4096, seed=815300):
    """Exercise actual common memory writes and readout on public event tapes.

    A separate dictionary oracle processes WRITE events for scoring. The
    learner receives QUERY events without answer values. Initial values are a
    permutation; physical address labels are independently permuted every
    episode. Six queries cover all four addresses and then revisit two.
    """
    if not isinstance(episodes, int) or episodes < 1:
        raise ValueError("episodes must be a positive integer")
    started_cpu, started_wall = time.process_time(), time.perf_counter()
    rng = np.random.default_rng(seed)
    law = Law()
    correct = all_correct = 0
    ignored_overwrite_correct = accepted_distractor_correct = 0
    writes = distractors = changed_overwrites = 0
    seen_permutations = set()
    failures = []
    digest = hashlib.sha256()
    for episode in range(episodes):
        permutation = rng.permutation(4)
        values = rng.permutation(4)
        seen_permutations.add(tuple(map(int, permutation)))
        logical_queries = np.r_[rng.permutation(4), rng.permutation(4)[:2]]
        events = [dict(kind="WRITE", key=int(permutation[key]), value=int(values[key]))
                  for key in range(4)]
        source = {int(permutation[key]): int(values[key]) for key in range(4)}
        for query, logical_key in enumerate(logical_queries):
            key = int(permutation[logical_key])
            if query in (2, 4):
                value = (source[key] + int(rng.integers(1, 4))) % 4
                source[key] = value
                events.append(dict(kind="WRITE", key=key, value=value))
                changed_overwrites += 1
            wrong_value = (source[key] + int(rng.integers(1, 4))) % 4
            events.append(dict(kind="DISTRACTOR", key=key, value=wrong_value))
            events.append(dict(kind="QUERY", key=key))

        # Initial dummy values are overwritten by the same four public writes
        # the dictionary oracle receives. No propagation occurs in this task.
        memory = BeliefMemory(law, [0, 0, 0, 0])
        oracle, stale, accepts_distractor = {}, {}, {}
        episode_correct = True
        for event in events:
            digest.update(json.dumps(event, sort_keys=True, separators=(",", ":")).encode())
            key = event["key"]
            if event["kind"] == "WRITE":
                memory.write(key, event["value"])
                oracle[key] = event["value"]
                stale.setdefault(key, event["value"])
                accepts_distractor[key] = event["value"]
                writes += 1
            elif event["kind"] == "DISTRACTOR":
                accepts_distractor[key] = event["value"]
                distractors += 1
            elif event["kind"] == "QUERY":
                prediction = int(np.argmax(memory.beliefs[key].reshape(10, 4).sum(0)))
                target = oracle[key]
                hit = prediction == target
                correct += hit
                episode_correct = episode_correct and hit
                ignored_overwrite_correct += stale[key] == target
                accepted_distractor_correct += accepts_distractor[key] == target
                if not hit and len(failures) < 16:
                    failures.append(dict(episode=episode, key=key, prediction=prediction, target=target))
            else:
                raise ValueError("Unknown public event type")
        if memory.clock != 0:
            raise AssertionError("Static baseline must not propagate hidden dynamics")
        all_correct += episode_correct

    queries = 6 * episodes
    return dict(schema="hcsn-r15-static-typed-content-contract-v1", seed=seed,
                episodes=episodes, queries=queries, correct=int(correct),
                accuracy=correct / queries, all_correct_episodes=int(all_correct),
                all_correct_rate=all_correct / episodes,
                public_writes=writes, public_distractors=distractors,
                changed_overwrites=changed_overwrites,
                address_permutations_covered=len(seen_permutations),
                possible_address_permutations=24,
                public_tape_sha256=digest.hexdigest(), first_failures=failures,
                cpu_seconds=time.process_time() - started_cpu,
                wall_seconds=time.perf_counter() - started_wall,
                diagnostic_wrong_implementations=dict(
                    ignores_overwrites_accuracy=ignored_overwrite_correct / queries,
                    accepts_distractors_accuracy=accepted_distractor_correct / queries,
                    scope="Contract-negative checks only; not strong ordinary-model baselines"),
                test_logic=[
                    "An independent per-episode permutation remaps four logical keys to public integer addresses.",
                    "The first four queries visit every address; two further queries revisit addresses.",
                    "Every query has a preceding same-key distractor with a different value.",
                    "Queries two and four have genuine changed-value overwrites, then immediate queries.",
                    "Actual BeliefMemory.write and its content-marginal readout are checked against a separate event oracle.",
                    "QUERY inputs have no answer field. Actor receives no oracle dictionary.",
                    "No time advance, hidden drift, noise, optimization or confirmation-dependent selection occurs."],
                scope="Only the common typed public-address memory contract; no learned semantic addressing, drift retention, analytic-core benefit, or deployment admission.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", type=int, default=4096)
    parser.add_argument("--seed", type=int, default=815300)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_baseline(episodes=args.episodes, seed=args.seed)
    encoded = json.dumps(result, indent=2, allow_nan=False)
    if args.output is None:
        print(encoded)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n")


if __name__ == "__main__":
    main()
