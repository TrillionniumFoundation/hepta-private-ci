"""Exploratory coverage and cost diagnostics; never alters registered gates."""

import gzip
import json
from pathlib import Path

import numpy as np
from scipy.stats import beta


def main():
    root = Path(__file__).parent
    summary = json.loads((root / "run_confirm_01/SUMMARY.json").read_text())
    frozen = json.loads((root / "run_train_01/FROZEN_MODELS.json").read_text())
    selected = {fit["seed"]: fit["selected_ordinary"] for fit in frozen["fits"]}
    rows, measured = [], {}
    for path in sorted((root / "run_confirm_01").glob("raw_*.json.gz")):
        with gzip.open(path, "rt") as stream:
            raw = json.load(stream)
        kind = selected[raw["seed"]]
        perfect = sum(row["outcomes"][kind]["answers"] == row["owner"]["targets"] for row in raw["rows"])
        count = len(raw["rows"])
        lower = 0. if perfect == 0 else float(beta.ppf(.05 / 24, perfect, count - perfect + 1))
        rows.append(dict(seed=raw["seed"], domain=raw["domain"], episodes=count,
                         completely_correct_episodes=perfect,
                         simultaneous_one_sided_exact_binomial_lower=lower))
        for row in raw["rows"]:
            for name, outcome in row["outcomes"].items():
                item = measured.setdefault(name, dict(online_cpu_seconds=0., episodes=0,
                                                      explicit_state_bytes=set(), encoder_bytes=set()))
                item["online_cpu_seconds"] += outcome["cpu_seconds"]
                item["episodes"] += 1
                if name != "oracle":
                    item["explicit_state_bytes"].add(outcome["state_array_bytes"])
                    item["encoder_bytes"].add(outcome["encoder_array_bytes"])
    for item in measured.values():
        for key in ("explicit_state_bytes", "encoder_bytes"):
            item[key] = sorted(item[key])
        item["mean_online_cpu_per_episode"] = item["online_cpu_seconds"] / item["episodes"]
    receipts = [json.loads((root / name).read_text()) for name in
                ("TRAIN_PROCESS_RECEIPT.json", "CONFIRM_PROCESS_RECEIPT.json")]
    result = dict(schema="hcsn-r16-content-exploratory-diagnostics-v1",
                  registered_acceptance_unchanged=summary["acceptance"],
                  exact_episode_diagnostic=rows,
                  minimum_simultaneous_exact_episode_bound=min(row["simultaneous_one_sided_exact_binomial_lower"] for row in rows),
                  exact_bound_scope="Exploratory, conditional on the eight frozen fitted encoders/policies and iid episode generator within each domain. It bounds probability that all 24 queries in an episode are correct, not unseen fits or open-domain content. Bonferroni over 24 fit-domain profiles. Not a registered gate or rescue.",
                  perfect_t_interval_caveat="When every fit accuracy is 1, the registered t standard error is zero. This is not a proof that unknown population error is zero.",
                  measured_online=measured,
                  nonoverlapping_training_and_confirmation_child_cpu_seconds=sum(
                      r["child_user_cpu_seconds"] + r["child_system_cpu_seconds"] for r in receipts),
                  cost_scope="Alternative arm timings are not summed into one deployment bill. Outer child totals already include inner timers and raw I/O; development, independent audits, upload and human/agent effort are excluded.")
    (root / "EXPLORATORY_DIAGNOSTICS.json").write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps(dict(exact_episode_bound=result["minimum_simultaneous_exact_episode_bound"],
                          child_cpu=result["nonoverlapping_training_and_confirmation_child_cpu_seconds"],
                          measured_online=measured), indent=2))


if __name__ == "__main__":
    main()
