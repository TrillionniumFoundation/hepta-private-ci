"""Source-bound symbolic memory probes; generation/validation is not training."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import random


TASKS = ("overwrite_retrieval", "delayed_copy", "pair_composition")
KINDS = ("write", "query", "distractor", "copy_read")
KEYS, VALUES = 8, 8


def encode(event):
    """Only observed symbols and elapsed time enter the 21-dimensional input."""
    return (
        [float(event["kind"] == kind) for kind in KINDS]
        + [float(key in event["keys"]) for key in range(KEYS)]
        + [float(event["value"] == value) for value in range(VALUES)]
        + [math.log1p(event["dt"])]
    )


def oracle(events, task):
    """A separate exact symbolic interpreter used to validate generated targets."""
    if task not in TASKS:
        raise ValueError("unknown memory task")
    memory, payload, position, targets = {}, [], 0, []
    for event in events:
        kind, keys, value = event["kind"], event["keys"], event["value"]
        target = -1
        if kind == "write":
            if value not in range(VALUES):
                raise ValueError("write requires an observed value")
            if task == "delayed_copy":
                payload.append(value)
            else:
                if len(keys) != 1:
                    raise ValueError("associative writes require exactly one key")
                memory[keys[0]] = value
        elif kind == "query":
            count = 2 if task == "pair_composition" else 1
            if task == "delayed_copy" or len(keys) != count or value is not None:
                raise ValueError("query must carry keys without its answer")
            target = sum(memory[key] for key in keys) % VALUES
        elif kind == "copy_read":
            if (
                task != "delayed_copy"
                or keys
                or value is not None
                or position >= len(payload)
            ):
                raise ValueError("copy read must be an unlabelled ordered request")
            target, position = payload[position], position + 1
        elif kind != "distractor":
            raise ValueError("unknown event kind")
        targets.append(target)
    return targets


def make_episode(task, seed, clock_seed, *, delay_events=16, copy_length=8):
    if task not in TASKS or min(delay_events, copy_length) < 1:
        raise ValueError("known task and positive delay/copy length required")
    symbols, clock = random.Random(seed), random.Random(clock_seed)
    events, targets, memory, payload = [], [], {}, []

    def append(kind, keys=(), value=None, target=-1):
        # Burst/timing randomness has an independent stream from symbols.
        dt = clock.choice((0.001, 0.003, 0.02, 0.04, 0.08, 0.16))
        events.append(dict(kind=kind, keys=list(keys), value=value, dt=dt))
        targets.append(target)

    if task == "delayed_copy":
        payload = [symbols.randrange(VALUES) for _ in range(copy_length)]
        for value in payload:
            append("write", value=value)
    else:
        keys = list(range(KEYS))
        symbols.shuffle(keys)
        for key in keys + [symbols.randrange(KEYS) for _ in range(KEYS)]:
            memory[key] = symbols.randrange(VALUES)
            append("write", (key,), memory[key])
    for _ in range(delay_events):
        value = None if symbols.random() < 0.2 else symbols.randrange(VALUES)
        append("distractor", (symbols.randrange(KEYS),), value)
    if task == "delayed_copy":
        for value in payload:
            append("copy_read", target=value)
    else:
        for _ in range(KEYS):
            keys = symbols.sample(range(KEYS), 2 if task == "pair_composition" else 1)
            append("query", keys, target=sum(memory[key] for key in keys) % VALUES)
    if targets != oracle(events, task):
        raise AssertionError(
            "generator disagrees with the independent symbolic interpreter"
        )
    return dict(
        schema="hcsn-symbolic-memory-episode-v1",
        task=task,
        seed=seed,
        clock_seed=clock_seed,
        events=events,
        x=[encode(event) for event in events],
        dt=[event["dt"] for event in events],
        y=targets,
        query_positions=[i for i, value in enumerate(targets) if value >= 0],
    )


def build_suite(output, *, train=128, development=32, probe=64):
    if any(
        type(n) is not int or not 1 <= n <= 100000 for n in (train, development, probe)
    ):
        raise ValueError(
            "episode counts must be integers in [1,100000] to keep seed ranges disjoint"
        )
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    entries = {}
    for task_number, task in enumerate(TASKS):
        for split_number, (split, count, delay) in enumerate(
            (
                ("train", train, 16),
                ("development", development, 32),
                ("probe", probe, 128),
            )
        ):
            lines, events, targets = [], 0, 0
            for index in range(count):
                seed = 20261110 + task_number * 1000000 + split_number * 100000 + index
                episode = make_episode(
                    task, seed, seed + 1000000000, delay_events=delay
                )
                episode["id"] = f"{task}/{split}/{index:05d}"
                lines.append(
                    json.dumps(
                        episode, sort_keys=True, separators=(",", ":"), allow_nan=False
                    )
                    + "\n"
                )
                events += len(episode["events"])
                targets += len(episode["query_positions"])
            payload = "".join(lines).encode()
            name = f"{task}-{split}.jsonl"
            (output / name).write_bytes(payload)
            entries[name] = dict(
                bytes=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
                episodes=count,
                events=events,
                scored_positions=targets,
                delay_events=delay,
            )
    source_root = Path(__file__).parent
    source_hashes = {
        str(p.relative_to(source_root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(source_root.rglob("*"))
        if p.is_file() and p.suffix in (".py", ".md")
    }
    manifest = dict(
        schema="hcsn-nondiffusive-memory-suite-v1",
        files=entries,
        source_sha256=source_hashes,
        python=platform.python_version(),
        input_dimension=21,
        output_classes=VALUES,
        label_mask="only y>=0 is scored; write/distractor labels are -1",
        temporal_law="independent discrete irregular intervals; no diffusion or first-passage generator",
        max_dt=0.16,
        new_episode_state_required=True,
        probe_scope="fresh seeds and longer delay; generated/validated labels are visible, not blinded confirmation",
        baseline_chance=1 / VALUES,
        training_runs=0,
        model_benefit_established=False,
        physical_energy_joules=None,
    )
    (output / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_suite(args.output)
    print(
        json.dumps(
            dict(
                files=len(manifest["files"]),
                episodes=sum(v["episodes"] for v in manifest["files"].values()),
                training_runs=0,
                output=str(args.output),
            )
        )
    )


if __name__ == "__main__":
    main()
