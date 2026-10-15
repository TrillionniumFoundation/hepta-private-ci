"""Prepare one measured, frozen nonfinal feature bank from official local data."""
import argparse
from pathlib import Path
import time

import torch

from group_encoder import FrozenTokenEncoder, file_digest
from multirc_data import load_jsonl, partition_cases
from reader_campaign_utils import PARAGRAPH_CAPS, select_paragraphs, write_json
from reader_features import SentenceBank


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "snapshot", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    import torch._dynamo
    torch.set_num_threads(1)
    started_wall, started_cpu = time.perf_counter_ns(), time.process_time_ns()
    data = load_jsonl(args.source / "train.jsonl", "train")
    if data.sha256 != "bb73d0838618f8269190a2533fead3140607558975ea0df6511fa534e8d3535c":
        raise ValueError("official train bytes changed")
    parts = partition_cases(data.cases, seed=41)
    selected = {name: select_paragraphs(cases, PARAGRAPH_CAPS[name])
                for name, cases in parts.items() if name != "final"}
    load_start = time.perf_counter_ns(), time.process_time_ns()
    encoder = FrozenTokenEncoder(args.snapshot, max_tokens=256)
    loading = dict(wall_ns=time.perf_counter_ns() - load_start[0], cpu_ns=time.process_time_ns() - load_start[1])
    bank = SentenceBank(encoder, batch_size=16)
    for name, cases in selected.items():
        bank.register(cases)
        print(name, len(cases), "candidates;", bank.forward_batches, "actual forward batches", flush=True)
    bank.save_local(args.output)
    receipt = dict(**bank.report(), loading=loading, source_train_sha256=data.sha256,
        source_sha256={name: file_digest(Path(__file__).parent / name) for name in
            ("reader_prepare.py", "reader_features.py", "multirc_data.py", "reader_campaign_utils.py", "group_encoder.py")},
        candidate_counts={name: len(cases) for name, cases in selected.items()},
        source_groups={name: sorted({case.source_hash for case in cases}) for name, cases in selected.items()},
        total_wall_ns=time.perf_counter_ns() - started_wall, total_cpu_ns=time.process_time_ns() - started_cpu,
        official_validation_accessed=False, formula_coverage_qualification=False)
    write_json(args.output, "encoder.json", receipt)


if __name__ == "__main__":
    main()
