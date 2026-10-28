"""Independent, arm-invariant evidence streams and the exact deployment roster."""

from itertools import product
import json
from pathlib import Path

from .learning.task import make_batch


PROTOCOL_PATH = Path(__file__).with_name("PROTOCOL.json")
CREDIT_KEYS = (
    "eta",
    "pmax",
    "kappa",
    "balance_cap",
    "initial_balance",
    "initial_price",
    "frozen_price",
    "quote",
)


def protocol():
    return json.loads(PROTOCOL_PATH.read_text())


def episode_plan(config, seed, split):
    """All policies consume prefixes of these pre-generated complete streams."""
    deployment = config["deployment"]
    domain = config["datasets"][split]
    contexts = list(product(domain["reliability"], domain["cost"], domain["deadline"]))
    if len(contexts) != deployment["contexts_per_budget_block"]:
        raise ValueError("context count differs from the registered budget block")
    budgets = list(config["credit"]["budget_levels"])
    if config["confirmation_seeds"].index(seed) % 2:
        budgets.reverse()
    episodes = []
    for budget in budgets:
        for context in contexts:
            ordinal = len(episodes)
            task_index = deployment["task_index_start"] + ordinal
            batch = make_batch(seed, task_index, split, context, 1)
            episodes.append(
                {
                    "case": f"case.{ordinal:04d}",
                    "context": list(context),
                    "budget": budget,
                    "observations": batch.observations[0].astype(int).tolist(),
                    "truth": int(batch.truth[0]),
                    "stream_id": {
                        "seed": seed,
                        "split": split,
                        "task_index": task_index,
                        "batch_sha256": batch.digest,
                    },
                }
            )
    if len(episodes) != deployment["episodes_per_organ"]:
        raise ValueError("episode count differs from the frozen protocol")
    return episodes


def expected_roster(config=None):
    config = protocol() if config is None else config
    rows = []
    for seed in config["confirmation_seeds"]:
        for split in config["deployment"]["splits"]:
            episodes = episode_plan(config, seed, split)
            for variant in config["deployment"]["variants"]:
                organ = f"seed{seed}.{split}.{variant['id']}"
                rows.append(
                    {
                        "organ": organ,
                        "seed": seed,
                        "split": split,
                        "variant": variant["id"],
                        "training_arm": variant["training_arm"],
                        "plan": {
                            "organ": organ,
                            "policy": {
                                key: variant[key] for key in ("readout", "credit")
                            },
                            "episodes": episodes,
                        },
                    }
                )
    names = [row["organ"] for row in rows]
    if (
        len(names) != len(set(names))
        or len(rows) != config["deployment"]["expected_organs"]
    ):
        raise ValueError("missing or duplicate registered organs")
    if (
        sum(len(row["plan"]["episodes"]) for row in rows)
        != config["deployment"]["expected_episodes"]
    ):
        raise ValueError("registered total episode count changed")
    return rows


def verify_roster(actual, expected):
    """Order is intentional: it fixes cost and recovery evidence identities."""
    fields = ("organ", "seed", "split", "variant", "training_arm")
    if [{key: row[key] for key in fields} for row in actual] != [
        {key: row[key] for key in fields} for row in expected
    ]:
        raise ValueError(
            "deployment has missing, duplicate, reordered or unregistered organs"
        )


def full_profile(neural, config):
    return {
        "schema": "hepta.adaptive-neuron.readout.v2",
        "neural": neural,
        "credit": {key: config["credit"][key] for key in CREDIT_KEYS},
        "grid_points": config["deployment"]["grid_points"],
    }
