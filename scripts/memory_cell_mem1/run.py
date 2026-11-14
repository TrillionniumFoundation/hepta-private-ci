"""Run the preregistered synthetic MEM-1 reference, with no production adoption.

python scripts/memory_cell_mem1/run.py --native PATH --output NEW_DIRECTORY
"""

import argparse
from dataclasses import asdict, replace
import hashlib
import json
import math
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
import time

try:
    import resource
except ImportError:
    resource = None

from environment import (
    Experience,
    OUTPUTS,
    Owner,
    ReplayPool,
    WIDTH,
    commitment,
    panels,
    schedule,
)
from native import NativeMemory, argmax

ARMS = (
    "rag",
    "rag_replay",
    "recurrent",
    "fast",
    "fast_uniform",
    "fast_structured",
    "fast_stabilized",
)
SLEEP_ARMS = {"rag_replay", "fast_uniform", "fast_structured", "fast_stabilized"}
CAPS = {
    "kernel_multiplications": 5_000_000,
    "state_payload_bytes": 65_536,
    "pool_payload_bytes": 16_384,
    "owner_checks": 100_000,
}


def dump(path, value):
    Path(path).write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )


def child_cpu_ns():
    if resource is None:
        return None
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return int((usage.ru_utime + usage.ru_stime) * 1_000_000_000)


class Trial:
    def __init__(self, binary, output, arm, seed, owner_change=True):
        self.output, self.arm, self.seed = output, arm, seed
        self.owner_change = owner_change
        output.mkdir(parents=True)
        self.raw = (output / "events.jsonl").open("w")
        self.owner, self.pool = Owner(seed), ReplayPool()
        self.rng = random.Random(seed + 20_000)
        self.memory = NativeMemory(binary, f"cell:{arm}:{seed}", 1)
        self.anchor = None
        self.h = [0.0] * WIDTH
        self.counts = {
            "online_updates": 0,
            "rebuild_updates": 0,
            "sleep_updates": 0,
            "owner_checks": 0,
            "retired_kernel_multiplications": 0,
            "retired_ipc_wall_ns": 0,
            "encoder_multiplications": 0,
            "retired_native_calls": 0,
            "recovery_checkpoint_bytes": 0,
            "recovery_checkpoint_operations": 0,
        }
        self.summaries, self.recoveries, self.plasticity = {}, [], []
        self.step = 0
        self.peak_pool_bytes = 0
        self.started = time.perf_counter_ns()
        self.cpu_started = time.process_time_ns()
        self.child_cpu_started = child_cpu_ns()

    def log(self, event, **values):
        self.raw.write(
            json.dumps(
                {
                    "event": event,
                    "arm": self.arm,
                    "seed": self.seed,
                    "step": self.step,
                    "generation": self.owner.generation,
                    **values,
                },
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        )

    def check_budget(self):
        self.peak_pool_bytes = max(self.peak_pool_bytes, self.pool.payload_bytes())
        total = (
            self.counts["retired_kernel_multiplications"] + self.memory.multiplications
        )
        if self.anchor is not None:
            total += self.anchor.multiplications
        if (
            total > CAPS["kernel_multiplications"]
            or self.peak_pool_bytes > CAPS["pool_payload_bytes"]
            or self.owner.checks > CAPS["owner_checks"]
        ):
            raise ValueError("common resource cap exceeded during execution")

    def retire(self, memory):
        self.counts["retired_kernel_multiplications"] += memory.multiplications
        self.counts["retired_ipc_wall_ns"] += memory.wall_ns
        self.counts["retired_native_calls"] += memory.calls
        memory.close()

    def features(self, source, advance=False):
        key = self.owner.features[source]
        if self.arm != "recurrent":
            return key
        value = [math.tanh(0.5 * old + new) for old, new in zip(self.h, key)]
        self.counts["encoder_multiplications"] += WIDTH
        if advance:
            self.h = value
        return value

    def answer(self, sources):
        values, predictions, blocked = [], [], []
        for source in sources:
            prediction = (
                self.memory.predict(self.features(source))
                if self.arm != "rag"
                else None
            )
            predictions.append(argmax(prediction) if prediction is not None else None)
            fact = self.owner.resolve(source)
            row = self.pool.rows.get(source)
            eligible = fact is not None and row is not None
            blocked.append(not eligible)
            if not eligible:
                values.append(None)
            elif self.arm == "rag":
                # Strong exact-key retrieval baseline: resolve CURRENT source value.
                values.append(fact.label)
            elif self.arm == "rag_replay":
                # Fixed retrieval prior plus the actually replay-trained readout.
                # Keep direct RAG separately: this mixture is not presumed superior.
                scores = [
                    value + 0.5 * (label == fact.label)
                    for label, value in enumerate(prediction)
                ]
                values.append(argmax(scores))
            else:
                values.append(argmax(prediction))
        output = values if all(value is not None for value in values) else None
        expected = [self.owner.facts[source].label for source in sources]
        valid = all(self.owner.resolve(source) is not None for source in sources)
        correct = output == expected if valid else output is None
        self.check_budget()
        return {
            "sources": sources,
            "prediction": predictions,
            "output": output,
            "expected": expected if valid else None,
            "eligible": valid,
            "correct": correct,
            "blocked": blocked,
            "answered": output is not None,
            "wrong_assertion": output is not None and output != expected,
            "stale_assertion": output is not None
            and any(
                source in self.owner.previous_labels
                and value == self.owner.previous_labels[source]
                for source, value in zip(sources, output)
            ),
            "invalid_assertion": output is not None and not valid,
        }

    def evaluate(self, phase):
        summary = {}
        for panel, queries in panels().items():
            rows = [self.answer(query) for query in queries]
            for row in rows:
                self.log("probe", phase=phase, panel=panel, **row)
            summary[panel] = {
                "n": len(rows),
                "accuracy": sum(row["correct"] for row in rows) / len(rows),
                "coverage": sum(row["answered"] for row in rows) / len(rows),
                "wrong_assertions": sum(row["wrong_assertion"] for row in rows),
                "stale_assertions": sum(row["stale_assertion"] for row in rows),
                "invalid_assertions": sum(row["invalid_assertion"] for row in rows),
            }
        self.summaries[phase] = summary

    def learn(self, row, kind):
        support = self.owner.support(row)
        if support is None:
            raise ValueError("ineligible source reached training")
        target = [float(label == row.label) for label in range(OUTPUTS)]
        if self.arm == "fast_stabilized" and self.anchor is not None:
            teacher = self.anchor.predict(row.key)
            target = [
                0.75 * label + 0.25 * min(1.0, max(-1.0, old))
                for label, old in zip(target, teacher)
            ]
        receipt = self.memory.update(row.key, target, support)
        self.counts[kind + "_updates"] += 1
        self.check_budget()
        self.log(
            "update",
            kind=kind,
            source=row.source,
            source_version=row.version,
            support=support,
            state=self.memory.digest,
            **receipt,
        )

    def sleep(self, phase):
        if self.arm not in SLEEP_ARMS:
            return
        start = time.perf_counter_ns()
        strategy = (
            "structured"
            if self.arm in {"fast_structured", "fast_stabilized"}
            else "uniform"
        )
        consumed = []
        for index in range(64):
            row = self.pool.sample(self.owner, self.rng, strategy, index)
            if row is None:
                raise ValueError("empty eligible replay pool")
            self.learn(row, "sleep")
            consumed.append({"source": row.source, "version": row.version})
        anchor, payload = self.memory.checkpoint()
        (self.output / f"candidate-{phase}.bin").write_bytes(bytes.fromhex(payload))
        candidate = {
            "kind": "private-fast-state-rehearsal-candidate",
            "sha256": anchor,
            "source_lineage": consumed,
            "owner_generation": self.owner.generation,
            "elapsed_ns": time.perf_counter_ns() - start,
            "updates": 64,
            "capacity_expansion": False,
            "selected_shared_model_changed": False,
            "model_adoption": "NoUpdate",
            "reason": "independent live model evaluation and owner adoption are not implemented",
        }
        dump(self.output / f"candidate-{phase}.json", candidate)
        self.log("sleep_candidate", phase=phase, **candidate)

    def change_owner(self):
        stale_checkpoint = self.memory.checkpoint()
        self.owner.change_rules_and_revoke()
        self.memory.reset(self.owner.generation, "owner-cut-2")
        rejected = False
        try:
            self.memory.restore(stale_checkpoint)
        except ValueError:
            rejected = True
        if not rejected:
            raise ValueError("old owner checkpoint restored after revocation")
        self.h = [0.0] * WIDTH
        if self.anchor is not None:
            self.retire(self.anchor)
            self.anchor = None
        fresh = ReplayPool()
        for row in self.pool.rows.values():
            fact = self.owner.resolve(row.source, "Replay", row.version)
            if fact is not None and fact.label == row.label:
                fresh.add(
                    replace(
                        row,
                        key=self.owner.features[row.source],
                        key_generation=self.owner.generation,
                        surprise=0.0,
                    )
                )
        self.pool = fresh
        if self.arm != "rag":
            for row in self.pool.eligible(self.owner):
                self.learn(row, "rebuild")
        self.anchor = self.memory.clone()
        self.log(
            "owner_change",
            stale_checkpoint_rejected=rejected,
            reset=True,
            reused_weights=False,
            eligible_rebuild_sources=len(self.pool.eligible(self.owner)),
        )

    def recover(self, phase):
        key = self.owner.features["A:0"]
        before = self.memory.predict(key)
        working_digest = commitment(self.h)
        dump(
            self.output / f"working-{phase}.json",
            {
                "h": self.h,
                "counts": self.counts,
                "pool": [asdict(row) for row in self.pool.rows.values()],
            },
        )
        old = self.memory
        self.memory = old.restart(self.output / f"restart-{phase}")
        self.counts["retired_kernel_multiplications"] += old.multiplications
        self.counts["retired_ipc_wall_ns"] += old.wall_ns
        self.counts["retired_native_calls"] += old.calls
        state = json.loads((self.output / f"working-{phase}.json").read_text())
        self.h = state["h"]
        self.pool.rows.clear()
        for row in state["pool"]:
            row["key"] = tuple(row["key"])
            self.pool.add(Experience(**row))
        after = self.memory.predict(key)
        matched = before == after and working_digest == commitment(self.h)
        if not matched:
            raise ValueError("native restart changed predictions/working state")
        self.counts["recovery_checkpoint_operations"] += 1
        self.counts["recovery_checkpoint_bytes"] += self.memory.state_bytes
        self.recoveries.append(matched)
        self.log(
            "recovery",
            phase=phase,
            matched=matched,
            state=self.memory.digest,
            boundary="native worker process restarted; Python owner remains alive",
        )

    def run(self):
        try:
            for phase, sources in schedule(self.seed):
                if phase == "B":
                    if self.owner_change:
                        self.change_owner()
                    else:
                        self.anchor = self.memory.clone()
                        self.log("owner_stationary", reset=False, reused_weights=True)
                for index, source in enumerate(sources):
                    self.step += 1
                    answer = self.answer((source,))
                    key = self.features(source, advance=True)
                    prediction = (
                        self.memory.predict(key)
                        if self.arm != "rag"
                        else [0.0] * OUTPUTS
                    )
                    logits = [math.exp(value - max(prediction)) for value in prediction]
                    # Uncertainty uses prediction only, before obtaining current supervision.
                    surprise = 1.0 - max(logits) / sum(logits)
                    fact = self.owner.resolve(source, "Replay")
                    if fact is None:
                        raise ValueError("training stream contains ineligible source")
                    row = Experience(
                        source,
                        fact.version,
                        tuple(key),
                        fact.label,
                        self.step,
                        surprise,
                        source[0],
                        self.owner.generation,
                    )
                    self.pool.add(row)
                    if self.arm != "rag":
                        self.learn(row, "online")
                    if phase == "B" and source.startswith("B:"):
                        self.plasticity.append(answer["correct"])
                    self.log("prequential", phase=phase, before_update=True, **answer)
                    if index == len(sources) // 2:
                        self.recover(phase)
                if phase != "A2":
                    self.sleep(phase)
                self.evaluate(phase)
            final = self.summaries["A2"]
            threshold = next(
                (
                    index + 16
                    for index in range(len(self.plasticity) - 15)
                    if sum(self.plasticity[index : index + 16]) / 16 >= 0.8
                ),
                None,
            )
            total = (
                self.counts["retired_kernel_multiplications"]
                + self.memory.multiplications
            )
            if self.anchor is not None:
                total += self.anchor.multiplications
            native_calls = self.counts["retired_native_calls"] + self.memory.calls
            ipc_wall_ns = self.counts["retired_ipc_wall_ns"] + self.memory.wall_ns
            if self.anchor is not None:
                native_calls += self.anchor.calls
                ipc_wall_ns += self.anchor.wall_ns
            capacity = {
                "state_payload_bytes": 3 * self.memory.state_bytes + WIDTH * 8,
                "pool_payload_bytes": self.peak_pool_bytes,
                "kernel_multiplications": total,
                "owner_checks": self.owner.checks,
            }
            self.counts["owner_checks"] = self.owner.checks
            budget_passed = all(capacity[key] <= limit for key, limit in CAPS.items())
            self.memory.close()
            if self.anchor is not None:
                self.anchor.close()
            child_cpu = child_cpu_ns()
            result = {
                "arm": self.arm,
                "seed": self.seed,
                "status": "completed",
                "panels": self.summaries,
                "owner_change": self.owner_change,
                "retention_delta": self.summaries["B"]["stable"]["accuracy"]
                - self.summaries["A1"]["stable"]["accuracy"],
                "b_prequential_accuracy": statistics.mean(self.plasticity),
                "b_samples_to_80pct_window16": threshold,
                "b_threshold_censored": threshold is None,
                "native_recoveries": self.recoveries,
                "capacity_and_compute": capacity,
                "counts": self.counts,
                "common_budget_cap": CAPS,
                "budget_passed": budget_passed,
                "coverage_floor_passed": final["stable"]["coverage"] >= 0.5,
                "wall_ns": time.perf_counter_ns() - self.started,
                "python_cpu_ns": time.process_time_ns() - self.cpu_started,
                "native_child_cpu_ns": None
                if child_cpu is None
                else child_cpu - self.child_cpu_started,
                "native_calls": native_calls,
                "native_ipc_wall_ns": ipc_wall_ns,
                "final_state_sha256": self.memory.digest,
                "frozen_model_changed": False,
                "scientific_qualification": "HOLD",
                "production_adoption": "NoUpdate",
            }
            dump(self.output / "summary.json", result)
            if not budget_passed:
                raise ValueError("common resource cap exceeded")
            return result
        finally:
            self.memory.close()
            if self.anchor is not None:
                self.anchor.close()
            self.raw.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=list(range(5)))
    parser.add_argument("--arms", nargs="+", choices=ARMS, default=list(ARMS))
    parser.add_argument(
        "--stationary",
        action="store_true",
        help="Paired control without owner change/reset at B",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    if len(set(args.seeds)) != len(args.seeds) or len(set(args.arms)) != len(args.arms):
        raise ValueError("duplicate seed or arm")
    code_root = Path(__file__).resolve().parents[2]
    try:
        head = subprocess.check_output(
            ["git", "-C", str(code_root), "rev-parse", "HEAD"], text=True
        ).strip()
    except subprocess.CalledProcessError:
        head = "unavailable"
    source_paths = list(Path(__file__).parent.glob("*.py")) + list(
        (code_root / "codex-rs/hepta-memory-retrieval/src").glob("*.rs")
    )
    source_paths += list(
        (code_root / "codex-rs/hepta-memory-retrieval/examples").glob("*.rs")
    )
    inputs = {}
    for seed in args.seeds:
        owner = Owner(seed)
        inputs[str(seed)] = {
            "initial_facts": [asdict(fact) for fact in owner.facts.values()],
            "features": owner.features,
            "schedule": schedule(seed),
        }
    dump(args.output / "inputs.json", inputs)
    projection_path = code_root / "projection-manifest.json"
    projection = (
        json.loads(projection_path.read_text()) if projection_path.exists() else {}
    )
    manifest = {
        "schema": "hepta-mem1-reference-v1",
        "source_head": head,
        "repository_base": projection.get("source_commit", head),
        "checkout_kind": projection.get("qualification", "repository"),
        "runtime": {"python": sys.version, "platform": platform.platform()},
        "inputs_sha256": hashlib.sha256(
            (args.output / "inputs.json").read_bytes()
        ).hexdigest(),
        "source_sha256": {
            str(path.relative_to(code_root)): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in sorted(source_paths)
        },
        "native_binary_sha256": hashlib.sha256(
            Path(args.native).read_bytes()
        ).hexdigest(),
        "seeds": args.seeds,
        "arms": args.arms,
        "budget": CAPS,
        "owner_change": not args.stationary,
        "planned_runs": len(args.seeds) * len(args.arms),
        "statistical_unit": "independent synthetic stream seed",
        "environment": "synthetic owner; exact-key RAG; normalized-delta association; no LLM",
        "shared_capacity": "three native states plus recurrent vector reserved in every arm; pool cap 24",
        "sleep_updates": 128,
        "stabilization_lambda": 0.25,
        "limitations": [
            "same resource caps, not equal measured total work",
            "fast-state rehearsal, not slow-model distillation",
            "native worker restart, not full owner-process crash recovery",
            "no schema transform, mismatch/reset only",
            "capacity is serialized payload/reservation, not process RSS",
            "synthetic owner checks, not live owner/evaluator isolation",
            "kernel multiplication cap omits hash/IPC; wall time includes them",
        ],
    }
    dump(args.output / "manifest.json", manifest)
    results = []
    for seed in args.seeds:
        for arm in args.arms:
            path = args.output / f"{arm}-seed-{seed}"
            try:
                result = Trial(
                    args.native, path, arm, seed, owner_change=not args.stationary
                ).run()
            except Exception as error:
                result = {
                    "arm": arm,
                    "seed": seed,
                    "status": "failed",
                    "error": repr(error),
                }
                dump(path / "failure.json", result)
            results.append(result)
            print(
                json.dumps({key: result[key] for key in ("arm", "seed", "status")}),
                flush=True,
            )
            dump(args.output / "results.json", results)
    failed = sum(row["status"] != "completed" for row in results)
    print(
        json.dumps(
            {
                "planned": manifest["planned_runs"],
                "completed": len(results) - failed,
                "failed": failed,
            }
        ),
        flush=True,
    )
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
