"""Three correlated synthetic streams, registered before any model observation."""

import argparse
from copy import deepcopy
from pathlib import Path
import random

from evolution_common import digest, read_json, require, retain
from longitudinal_protocol import protocol

SEEDS = [24019, 24023, 24029]


def campaign():
    recipe = protocol()
    streams = {}
    for seed in SEEDS:
        stream = deepcopy(recipe)
        stream["seed"] = seed
        stream["scope"] += f"-s{seed}"
        initial = stream["rounds"][0]["events"]
        values = [e["value"] for e in initial]
        random.Random(seed).shuffle(values)
        for event, value in zip(initial, values):
            event["value"] = value
        conflict = stream["rounds"][4]["events"][0]
        conflict["value"] = "red" if initial[4]["value"] != "red" else "blue"
        streams[str(seed)] = stream
    return dict(
        schema="hepta.longitudinal.campaign.v1",
        recipe_sha256=digest(recipe),
        seeds=SEEDS,
        streams=streams,
        launch_order=SEEDS,
        total_decoder_updates=5184,
        total_parameter_query_rows=558,
        seed_policy="run all three in order regardless of earlier quality; execution failure retained and remaining seed starts require intact environment",
        dependency_groups="three correlated synthetic streams using common policy/templates; not independent natural-task samples",
        final_tuning_allowed=False,
        confirmation=False,
        prospective=False,
        production_accepted=False,
    )


def load_stream(path, expected_sha256, seed):
    frozen = read_json(path)
    require(digest(frozen) == expected_sha256, "campaign digest changed")
    require(
        frozen == campaign() and seed in frozen["seeds"],
        "unregistered seed or campaign recipe",
    )
    return frozen["streams"][str(seed)]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = campaign()
    retain(args.output, value)
    print(digest(value))
