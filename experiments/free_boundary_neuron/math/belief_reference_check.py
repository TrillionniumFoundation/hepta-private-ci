"""Exact finite-tree check of the deployed finite-grid belief reference.

No seeds, training, or efficacy outcomes are used. The exact optimal recursion
uses reachable evidence counts. The actual threshold policy is integrated over
every complete observation stream, preserving deployed cumulative-sum rounding
and action/tie semantics rather than assuming canonical log-odds arithmetic.
"""

import argparse
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import itertools
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
from scipy.special import expit, logit

from ..learning.task import ABSTAIN_REWARD, BellmanReference, action_arrays
from ..provenance import verify


DIRECTORY = Path(__file__).resolve().parent
LEARNING = DIRECTORY.parent / "learning"
REGRET_TOLERANCE = 1e-3  # Approved numerical baseline tolerance, not an efficacy gate.


def compare_context(reliability, cost, deadline, oracle):
    """Integrate expected utility, including the compulsory first observation."""
    r, c, h = float(reliability), float(cost), int(deadline)
    increment = float(logit(r))

    @lru_cache(None)
    def optimal(evidence, observed):
        belief = float(expit(evidence * increment))
        immediate = max(abs(2 * belief - 1), ABSTAIN_REWARD)
        if observed == h:
            return immediate
        chance = r * belief + (1 - r) * (1 - belief)
        continuation = -c + chance * optimal(evidence + 1, observed + 1)
        continuation += (1 - chance) * optimal(evidence - 1, observed + 1)
        return max(immediate, continuation)

    exact = 0.5 * (optimal(1, 1) + optimal(-1, 1)) - c
    profile = oracle.profile(r, c, h)
    # All streams are summed, not sampled. Runtime actions see only each prefix.
    bits = (
        (np.arange(1 << h, dtype=np.uint32)[:, None] >> np.arange(h, dtype=np.uint32))
        & 1
    ).astype(float)
    voltage = np.cumsum((2 * bits - 1) * increment, axis=1)
    positive, negative, neutral, _ = action_arrays(
        voltage,
        profile["choice"][None, :],
        profile["abstain"][None, :],
        np.full(len(bits), h, dtype=int),
    )
    terminal = positive + negative + neutral
    if not np.all((terminal == 0) | (terminal == 1)) or not np.all(
        terminal.any(axis=1)
    ):
        raise ValueError(
            "deployed reference has overlapping or missing terminal actions"
        )
    first = np.argmax(terminal, axis=1)
    decision = (
        positive[np.arange(len(bits)), first] - negative[np.arange(len(bits)), first]
    )
    n_plus = bits.sum(axis=1)
    joint_positive = 0.5 * r**n_plus * (1 - r) ** (h - n_plus)
    joint_negative = 0.5 * (1 - r) ** n_plus * r ** (h - n_plus)
    mass = joint_positive + joint_negative
    expected_reward = decision * (joint_positive - joint_negative)
    expected_reward += (decision == 0) * ABSTAIN_REWARD * mass
    actual = float(np.sum(expected_reward - (first + 1) * c * mass))
    table_bytes = b"".join(
        np.ascontiguousarray(profile[key]).tobytes() for key in ("choice", "abstain")
    )
    return {
        "reliability": r,
        "cost": c,
        "deadline": h,
        "exact_reachable_lattice_utility": exact,
        "deployed_threshold_policy_utility": actual,
        "regret": exact - actual,
        "probability_mass_error": abs(float(mass.sum()) - 1),
        "reachable_recursion_states": optimal.cache_info().currsize,
        "complete_streams_integrated": len(bits),
        "threshold_table_sha256": hashlib.sha256(table_bytes).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-seal", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    started, cpu = time.perf_counter(), time.process_time()
    rows = []
    payload = {
        "schema": "hepta.free-boundary.belief-reference-check.v1",
        "evidence_scope": "baseline_approximation_verification_not_efficacy",
        "phase": "sealed" if args.source_seal else "unsealed_preflight",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": [sys.executable, *sys.argv],
        "random_seeds_used": [],
        "training_performed": False,
        "numerical_regret_tolerance": REGRET_TOLERANCE,
        "contexts": rows,
    }
    # Reserve exclusively before doing work; failed attempts retain completed rows.
    with args.output.open("x") as handle:
        try:
            if args.source_seal:
                payload["source_verification"] = verify(args.source_seal)
            paths = [
                Path(__file__),
                DIRECTORY / "PROTOCOL.json",
                LEARNING / "PROTOCOL.json",
                LEARNING / "task.py",
                LEARNING / "runner.py",
            ]
            payload["source_sha256"] = {
                str(p.relative_to(DIRECTORY.parent)): hashlib.sha256(
                    p.read_bytes()
                ).hexdigest()
                for p in paths
            }
            payload["source_commit"] = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=DIRECTORY, text=True
            ).strip()
            protocol = json.loads((LEARNING / "PROTOCOL.json").read_text())
            payload["learning_protocol_schema"] = protocol["schema"]
            payload["primary_practical_effect"] = protocol["minimum_practical_effect"]
            if not REGRET_TOLERANCE < protocol["minimum_practical_effect"]:
                raise ValueError(
                    "numerical tolerance must stay below the primary practical effect"
                )
            if (
                protocol["reward"]["correct"] != 1
                or protocol["reward"]["incorrect"] != -1
                or protocol["reward"]["abstain"] != ABSTAIN_REWARD
                or not protocol["reward"]["first_observation_charged"]
            ):
                raise ValueError(
                    "reference recursion does not match registered reward contract"
                )
            data = protocol["datasets"]
            oracle = BellmanReference(
                protocol["bellman_reference"]["belief_grid_points"]
            )
            for split in ("id", "ood"):
                for r, c, h in itertools.product(
                    data[split + "_reliability"],
                    data[split + "_cost"],
                    data[split + "_deadline"],
                ):
                    rows.append({"split": split, **compare_context(r, c, h, oracle)})
            if len(rows) != 16:
                raise ValueError("expected the sixteen registered contexts")
            payload["max_regret"] = max(row["regret"] for row in rows)
            payload["streams_integrated"] = sum(
                row["complete_streams_integrated"] for row in rows
            )
            passed = all(
                -1e-10 <= row["regret"] <= REGRET_TOLERANCE
                and row["probability_mass_error"] <= 1e-12
                for row in rows
            )
            if args.source_seal:
                verify(args.source_seal)
            payload["status"] = "passed" if passed else "failed"
        except Exception as error:
            payload.update(status="invalid_execution", error=repr(error))
        payload["wall_seconds"] = time.perf_counter() - started
        payload["process_cpu_seconds"] = time.process_time() - cpu
        json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "status": payload["status"],
                "contexts": len(rows),
                "max_regret": payload.get("max_regret"),
            }
        )
    )
    return 0 if payload["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
