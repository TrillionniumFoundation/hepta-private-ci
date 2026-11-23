"""Metadata-only review of the separately excluded history. Never execute records."""

import argparse
from itertools import islice
import json
from pathlib import Path
import re

import pyarrow.parquet as pq
from cell_experiments import coding_sft

from historical_a import PARQUET, check


def review(path):
    check(coding_sft.file_hash(path) == PARQUET, "source release differs")
    obj = pq.ParquetFile(path)
    row = next(
        islice(obj.iter_batches(batch_size=1, use_threads=False), 227, 228)
    ).to_pylist()[0]
    events = row["trajectory"]
    programs = []
    statuses = []
    for action_pos, outcome_pos in ((56, 57), (58, 59), (60, 61)):
        action, observation = events[action_pos], events[outcome_pos]
        check(
            action["action"] == "run" and observation["observation"] == "run",
            "unexpected event",
        )
        command = json.loads(action["extras"])["command"]
        m = re.fullmatch(r"([a-zA-Z][a-zA-Z0-9_-]{0,48}) --version", command)
        check(m is not None, "different operation")
        programs.append(m.group(1))
        statuses.append(json.loads(observation["extras"])["exit_code"])
    check(
        len(set(programs)) == 3
        and programs[-1] == "node"
        and statuses == [127, 127, 0],
        "different results",
    )
    return dict(
        release_rows=obj.metadata.num_rows,
        row_zero_based=227,
        submitted_at_naive=row["timestamp"].isoformat(),
        feedback=row["feedback"],
        permissions=row["permissions"],
        model_family="Hermes-3-Llama-3.1-405B",
        command_query_positions=[56, 58, 60],
        observation_positions=[57, 59, 61],
        exit_codes=statuses,
        distinct_version_queries=len(set(programs)),
        user_followup_count_after_last_query=sum(
            e["source"] == "user" for e in events[61:]
        ),
        disposition="Excluded. Separate version queries; success did not repair either missing executable.",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    coding_sft.write_new(args.output, review(args.release))
