"""Freeze a post-training panel and cold-score all arms with the same action runner."""

import argparse
import json
import os
from pathlib import Path
import random
import secrets
import subprocess
import sys
import time

from cell_experiments import coding_sft, data
from episode import outputs, panel, passes, retrieved_prompt, stage_prompt

ROOT = Path(__file__).resolve().parent
ARMS = json.loads((ROOT / "PLAN.json").read_text())["arms"]


def read(p):
    return json.loads(p.read_bytes())


def freeze_at(root, expected):
    obj = read(root / "freeze.json")
    if data.digest(obj) != expected:
        raise ValueError("Wrong independent freeze")
    for n, digest in obj["program"].items():
        if coding_sft.file_hash(ROOT / n) != digest:
            raise ValueError("Changed program")
    if coding_sft.file_hash(ROOT / "PLAN.json") != obj["plan"]:
        raise ValueError("Changed plan")
    for n, digest in obj["inputs"].items():
        if coding_sft.file_hash(root / n) != digest:
            raise ValueError("Changed data")
    if set(obj["manifests"]) != set(ARMS):
        raise ValueError("Changed arm roster")
    for arm, digest in obj["manifests"].items():
        m = read(root / (arm + ".json"))
        if data.digest(m) != digest:
            raise ValueError("Different model")
        coding_sft.verify_model(m, root)
    return obj


def prepare(root, out, expected):
    freeze_at(root, expected)
    out.mkdir(parents=True, exist_ok=False)
    memory = read(root / "memory.json")
    query = memory[0]["prompt"].rsplit("\nState: ", 1)[0]
    seed = secrets.randbits(63)
    cases = panel(seed, query)
    order = list(ARMS)
    random.Random(seed).shuffle(order)
    coding_sft.write_new(
        out / "panel.json",
        dict(
            seed=seed,
            freeze=expected,
            cases=cases,
            old="Return the digit zero.",
            arm_order=order,
        ),
    )
    print(coding_sft.file_hash(out / "panel.json"))


def cold(root, out, expected, panel_sha, arm):
    import torch

    torch.set_num_threads(1)
    freeze = freeze_at(root, expected)
    obj = read(out / "panel.json")
    if (
        coding_sft.file_hash(out / "panel.json") != panel_sha
        or obj["freeze"] != expected
    ):
        raise ValueError("Wrong panel or freeze")
    memory = read(root / "memory.json")
    start, cpu = time.perf_counter(), time.process_time()
    manifest = read(root / (arm + ".json"))
    predictor = coding_sft.load_predictor(manifest, root)
    loaded = time.perf_counter()
    all_calls = []

    def generate(query, state):
        given = query
        if arm == "retrieval":
            given = retrieved_prompt(
                query, state, memory, predictor.tokenizer, coding_sft.prompt_text, 170
            )
        r = predictor.predict({"task": {"input": given}})
        if (
            r["loaded_model_digest"] != freeze["manifests"][arm]
            or r["input_tokens"] > 170
            or r["output_tokens"] > 80
        ):
            raise ValueError("Model or budget mismatch")
        all_calls.append(r)
        return len(all_calls) - 1

    rows = []
    try:
        for c in obj["cases"]:
            acts = []
            for state in range(4):
                ix = generate(stage_prompt(c["query"], state), state)
                acts.append(ix)
                answer = all_calls[ix]["answer"].strip()
                if state == 1:
                    if outputs(answer) is None:
                        break
                elif not passes(state, answer, c):
                    break
            # Separate diagnostic with exactly one call at each reference state.
            probes = [generate(stage_prompt(c["query"], s), s) for s in range(4)]
            rows.append(dict(id=c["id"], rollout=acts, probes=probes))
        old = generate(obj["old"], 4)
    finally:
        predictor.close()
    coding_sft.write_new(
        out / (arm + "-cold.json"),
        dict(
            arm=arm,
            model=freeze["manifests"][arm],
            freeze=expected,
            panel_sha256=panel_sha,
            pid=os.getpid(),
            rows=rows,
            old=old,
            calls=all_calls,
            cold_total_wall_seconds=time.perf_counter() - start,
            cold_total_cpu_seconds=time.process_time() - cpu,
            load_wall_seconds=loaded - start,
        ),
    )


def score(root, out, expected, panel_sha):
    freeze = freeze_at(root, expected)
    pp = out / "panel.json"
    obj = read(pp)
    if coding_sft.file_hash(pp) != panel_sha or obj["freeze"] != expected:
        raise ValueError("Panel substitution")
    costs = read(root / "training-costs.json")
    results = {}
    for arm in ARMS:
        saved = read(out / (arm + "-cold.json"))
        if (saved["arm"], saved["model"], saved["freeze"], saved["panel_sha256"]) != (
            arm,
            freeze["manifests"][arm],
            expected,
            panel_sha,
        ):
            raise ValueError("Invalid cold block identity")
        calls = saved["calls"]
        groups = {}
        references = []
        for row, c in zip(saved["rows"], obj["cases"], strict=True):
            if (
                row["id"] != c["id"]
                or len(row["probes"]) != 4
                or not 1 <= len(row["rollout"]) <= 4
            ):
                raise ValueError("Invalid trajectory")
            g = groups.setdefault(
                c["group"],
                dict(
                    n=0,
                    success=0,
                    probe_success=[0] * 4,
                    rollout_calls=0,
                    rollout_input_tokens=0,
                    rollout_output_tokens=0,
                ),
            )
            g["n"] += 1
            ids = row["rollout"]
            g["rollout_calls"] += len(ids)
            g["rollout_input_tokens"] += sum(calls[i]["input_tokens"] for i in ids)
            g["rollout_output_tokens"] += sum(calls[i]["output_tokens"] for i in ids)
            g["success"] += int(
                len(ids) == 4
                and all(passes(s, calls[i]["answer"], c) for s, i in enumerate(ids))
            )
            for state, ix in enumerate(row["probes"]):
                g["probe_success"][state] += int(passes(state, calls[ix]["answer"], c))
            references.extend(ids + row["probes"])
        references.append(saved["old"])
        if references != list(range(len(calls))):
            raise ValueError("Unassigned or duplicated generations")
        if any(r["loaded_model_digest"] != saved["model"] for r in calls):
            raise ValueError("Inconsistent serving weights")
        results[arm] = dict(
            groups=groups,
            old_correct=calls[saved["old"]]["answer"].strip() == "0",
            all_calls=len(calls),
            input_tokens=sum(r["input_tokens"] for r in calls),
            output_tokens=sum(r["output_tokens"] for r in calls),
            training=costs[arm],
            cold_total_wall_seconds=saved["cold_total_wall_seconds"],
            cold_total_cpu_seconds=saved["cold_total_cpu_seconds"],
        )
    return dict(
        freeze=expected,
        panel_sha256=panel_sha,
        users_enrolled=0,
        independent_user_pairs=0,
        native_payments=0,
        arms=results,
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mode", choices=("prepare", "run", "cold", "score"))
    ap.add_argument("root", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("freeze")
    ap.add_argument("--panel")
    ap.add_argument("--arm", choices=ARMS)
    a = ap.parse_args()
    if a.mode == "prepare":
        prepare(a.root, a.out, a.freeze)
    elif a.mode == "cold":
        cold(a.root, a.out, a.freeze, a.panel, a.arm)
    elif a.mode == "score":
        print(json.dumps(score(a.root, a.out, a.freeze, a.panel), sort_keys=True))
    else:
        for arm in read(a.out / "panel.json")["arm_order"]:
            subprocess.run(
                [
                    sys.executable,
                    __file__,
                    "cold",
                    str(a.root),
                    str(a.out),
                    a.freeze,
                    "--panel",
                    a.panel,
                    "--arm",
                    arm,
                ],
                check=True,
            )
        coding_sft.write_new(
            a.out / "results.json", score(a.root, a.out, a.freeze, a.panel)
        )


if __name__ == "__main__":
    main()
