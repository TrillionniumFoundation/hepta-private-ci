"""Reconcile every compact raw record and replay stratified actual episodes."""

from collections import defaultdict
import gzip
import json
from pathlib import Path
import time

import numpy as np

from tools.hcsn.round8_20261031.value_calibration import finite
from tools.hcsn.round8_20261031.value_calibration.frozen import FrozenR7
from tools.hcsn.round8_20261031.value_calibration.head import CalibratedHead
from tools.hcsn.round8_20261031.value_calibration.run import checkpoint, digest, episode_run, write
from ..head import CostFactoredHead, PreservedNominalHead
from ..protocol import contracts
from ..run import EVIDENCE, OLD, interval, verify_registration


HERE = Path(__file__).resolve().parent
CONFIRMATION = EVIDENCE / "confirmation02"


def run():
    design = verify_registration(); cpu = time.process_time()
    results = json.loads((CONFIRMATION / "RESULTS.json").read_text())
    frozen = json.loads((EVIDENCE / "HEADS_FROZEN.json").read_text())
    for name, sha in frozen["heads"].items():
        assert digest(EVIDENCE / "heads" / name) == sha
    # Audit selection is a fixed stratification, not selected from observed errors.
    replay_offsets = (0, 63, 127)
    write(HERE / "PROTOCOL.json", {"source_sha256": digest(__file__),
        "results_sha256": digest(CONFIRMATION / "RESULTS.json"),
        "replay_episode_offsets": replay_offsets, "reaggregate_all_rows": True})
    sums, counts, r9_cpu = defaultdict(lambda: defaultdict(float)), defaultdict(int), defaultdict(float)
    support = finite.build_graph(finite.configurations())["x"]
    cache, seen = {}, set()
    replayed, ledger_error, replay_error = 0, 0., 0.
    with gzip.open(CONFIRMATION / "PAIRED.jsonl.gz", "rt") as stream:
        for line in stream:
            row = json.loads(line); mode, seed, regime = row["mode"], row["seed"], row["regime"]
            group = mode, seed, regime
            identity = (*group, row["contract"], row["episode_seed"])
            assert identity not in seen; seen.add(identity)
            offset = row["episode_seed"] - (design["episode_seed_start"] + (seed - 11) * 100000 +
                design["regimes"].index(regime) * 10000 + row["contract"] * 1000)
            assert 0 <= offset < 128
            counts[group] += 1; r9_cpu[group] += row["runs"]["r9"]["cpu_seconds"]
            for name, actual in row["runs"].items():
                ledger_error = max(ledger_error, abs(actual["utility"] - actual["task_return"] +
                    finite.COMPUTE * actual["decisions"] + finite.EVENT * actual["events"]))
                assert actual["correct"] in (0, 1) and 0 <= actual["events"] <= actual["decisions"]
            for field in row["runs"]["r8"]:
                sums[group][field] += row["runs"]["r9"][field] - row["runs"]["r8"][field]
            if offset in replay_offsets:
                if (mode, seed) not in cache:
                    model = FrozenR7(checkpoint(mode, seed))
                    old = CalibratedHead.load(OLD / f"{mode}_{seed}.json")
                    new = CostFactoredHead.load(EVIDENCE / "heads" / f"{mode}_{seed}.json")
                    cache[mode, seed] = model, old, PreservedNominalHead(old, new, support)
                model, old, new = cache[mode, seed]
                episode = finite.task.generate_episode(row["episode_seed"], contracts(regime)[row["contract"]])
                for label, head in (("r8", old), ("r9", new)):
                    replay = episode_run(model, head, episode, row["episode_seed"] + design["latent_seed_offset"])
                    assert all(not step["guard_fallback"] for step in replay["steps"])
                    for field in ("task_return", "utility", "correct", "decisions", "events"):
                        replay_error = max(replay_error, abs(replay[field] - row["runs"][label][field]))
                    replayed += 1
    aggregate_error = 0.
    for row in results["records"]:
        group = row["mode"], row["seed"], row["regime"]
        assert counts[group] == row["paired_episodes"] == 1024
        for field, value in sums[group].items():
            aggregate_error = max(aggregate_error, abs(value / counts[group] - row["paired_delta"][field]))
    assert ledger_error < 1e-12 and replay_error < 1e-12 and aggregate_error < 1e-12
    control = []
    lookup = {(r["mode"], r["seed"], r["regime"]): r for r in results["records"]}
    for regime in design["regimes"]:
        differences = defaultdict(list)
        for seed in design["core_seeds"]:
            a, b = lookup["first_passage", seed, regime], lookup["direct", seed, regime]
            for field in ("utility", "correct", "mean_action_regret_all_states", "events", "decisions"):
                differences[field].append(a["exact"]["r9"][field] - b["exact"]["r9"][field])
            ca = r9_cpu["first_passage", seed, regime] / 1024
            cb = r9_cpu["direct", seed, regime] / 1024
            differences["inference_cpu_seconds"].append(ca - cb)
            differences["cpu_priced_utility"].append(a["exact"]["r9"]["utility"] - b["exact"]["r9"]["utility"] -
                (ca - cb) - (a["training_charge_per_session"] - b["training_charge_per_session"]))
        control.append({"regime": regime, "first_passage_minus_direct": {k: interval(v) for k, v in differences.items()},
                        "scope": "Descriptive matched frozen-family contrasts; no new equivalence gate or ensemble."})
    write(HERE / "RESULTS.json", {"protocol_sha256": digest(HERE / "PROTOCOL.json"), "raw_pairs": len(seen),
        "fully_replayed_runs": replayed, "ledger_max_error": ledger_error, "replay_max_error": replay_error,
        "aggregate_max_error": aggregate_error, "cpu_seconds": time.process_time() - cpu, "ordinary_control": control})
    print(json.dumps({"raw_pairs": len(seen), "fully_replayed_runs": replayed,
        "ledger_max_error": ledger_error, "replay_max_error": replay_error, "aggregate_max_error": aggregate_error}), flush=True)


if __name__ == "__main__":
    run()
