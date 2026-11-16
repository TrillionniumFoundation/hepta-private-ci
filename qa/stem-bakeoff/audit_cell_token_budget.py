"""Measure information truncated by the fixed token budget without model forwards."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from transformers import AutoTokenizer

from real_encoder import TASK_PREFIXES


def audit(dataset, granite, eg2, output):
    raw = Path(dataset).read_bytes()
    data = json.loads(raw)
    result = {"schema": "hepta.cell-token-budget-audit.v1",
        "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "model_forwards": 0, "head_updates": 0, "token_limit": 192,
        "scope": "post-run input information audit; original experiment unchanged", "candidates": {}}
    for candidate, snapshot, prefix in (("granite97m", granite, ""),
            ("embeddinggemma2_740m", eg2, TASK_PREFIXES["classification"])):
        tokenizer = AutoTokenizer.from_pretrained(snapshot, local_files_only=True, trust_remote_code=False)
        started = time.perf_counter_ns()
        lengths = []
        for offset in range(0, len(data["rows"]), 32):
            texts = [prefix + row["text"] for row in data["rows"][offset:offset + 32]]
            encoded = tokenizer(texts, truncation=False, padding=False, return_length=True,
                                return_attention_mask=False, return_token_type_ids=False)
            lengths.extend(encoded["length"])
        sizes = np.asarray(lengths)
        groups = {}
        for split in ("train", "calibration", "holdout"):
            selected = sizes[[row["split"] == split for row in data["rows"]]]
            groups[split] = {"rows": len(selected), "rows_above_limit": int((selected > 192).sum()),
                "fraction_above_limit": float((selected > 192).mean()),
                "median_untruncated_tokens": float(np.median(selected)),
                "p95_untruncated_tokens": float(np.quantile(selected, .95)),
                "maximum_untruncated_tokens": int(selected.max())}
        result["candidates"][candidate] = {"by_split": groups,
            "rows": len(sizes), "rows_above_limit": int((sizes > 192).sum()),
            "fraction_above_limit": float((sizes > 192).mean()),
            "full_token_count": int(sizes.sum()), "retained_token_count": int(np.minimum(sizes, 192).sum()),
            "token_count_includes_prefix_and_special_tokens": True,
            "tokenization_wall_ns": time.perf_counter_ns() - started,
            "ordered_source_ids": [row["source_id"] for row in data["rows"]],
            "untruncated_lengths": lengths}
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x") as stream:
        json.dump(result, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
        stream.write("\n")
    print(json.dumps({candidate: {k: v for k, v in report.items() if k not in
          ("ordered_source_ids", "untruncated_lengths")} for candidate, report in result["candidates"].items()}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "granite", "eg2", "output"):
        parser.add_argument("--" + name, required=True)
    audit(**vars(parser.parse_args()))
