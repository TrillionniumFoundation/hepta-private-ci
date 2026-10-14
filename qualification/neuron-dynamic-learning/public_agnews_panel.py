"""Pinned AG News cross-sectional capability control, never a future window.

Only immutable, preregistered SHA256-matched public parquet inputs may form the
joint question/options/state task panel. No production or learning authority.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

REPOSITORY = "szhuggingface/ag_news"
REVISION_PREFIX = "98c5322"
FILES = {
    "train": (
        "data/train_1_1.5k-00000-of-00001.parquet",
        "cc35afe9d5e7ff01878c9aeba08bb0bdfa16947702789530b216a580a1bc09d5",
    ),
    "calibration_test": (
        "data/val1-00000-of-00001.parquet",
        "3171d3aeee227372165bb0f9e84ebf2bfaf5fc870d034f33a5fc568e7995c672",
    ),
}
OPTIONS = ("world", "sports")
QUESTION = "Which category does the news report describe?"
QUOTAS = {"train": 64, "calibration": 16, "test": 32}
MAX_TEXT_BYTES = 8192


class PanelError(ValueError):
    """Data integrity, comparable-input or leakage failure."""


def canonical(obj: object) -> bytes:
    return json.dumps(
        obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_file(path: Path, role: str) -> str:
    if role not in FILES or not path.is_file() or path.is_symlink():
        raise PanelError("missing or unsafe public dataset asset")
    hasher = hashlib.sha256()
    total = 0
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            total += len(block)
            if total > 4 * 1024 * 1024:
                raise PanelError("unbounded public dataset asset")
            hasher.update(block)
    observed = hasher.hexdigest()
    if observed != FILES[role][1]:
        raise PanelError("dataset asset digest does not equal preregistered source")
    return observed


def select_rows(train: list[dict], holdout: list[dict]) -> dict:
    """Balanced deterministic train/calibration/test; no temporal future."""
    if not isinstance(train, list) or not isinstance(holdout, list):
        raise PanelError("labelled sources not provided")
    seen = set()
    cases = []

    def source_rows(rows: list[dict], split: str, count_each: int):
        eligible = []
        for row in rows:
            if not isinstance(row, dict) or not {"text", "label"} <= set(row):
                raise PanelError("incomplete public dataset schema")
            label, sentence = row["label"], row["text"]
            if type(label) is not int or not isinstance(sentence, str):
                raise PanelError("invalid public label/text type")
            if label not in (0, 1):
                continue
            if not 1 <= len(sentence.encode("utf-8")) <= MAX_TEXT_BYTES:
                continue
            source_digest = sha(sentence.encode("utf-8"))
            eligible.append((source_digest, sentence, label))
        selected = Counter()
        for source_digest, sentence, label in sorted(eligible):
            if source_digest in seen or selected[label] >= count_each:
                continue
            seen.add(source_digest)
            selected[label] += 1
            joint = {
                "question": QUESTION,
                "options": list(OPTIONS),
                "state": sentence,
            }
            cases.append({
                "case_id": source_digest[:24],
                "split": split,
                "label": label,
                "label_name": OPTIONS[label],
                "source_digest": source_digest,
                "joint_input": joint,
                "joint_input_digest": sha(canonical(joint)),
                "group_id": source_digest,
            })
        if selected != Counter({0: count_each, 1: count_each}):
            raise PanelError("independent balanced rows unavailable after de-duplication")

    source_rows(train, "train", QUOTAS["train"])
    source_rows(holdout, "calibration", QUOTAS["calibration"])
    source_rows(holdout, "test", QUOTAS["test"])
    return {
        "schema": "hepta.stem.agnews-binary-capability-panel.v1",
        "dataset": REPOSITORY,
        "dataset_commit_prefix": REVISION_PREFIX,
        "dataset_file_sha256": {kind: value[1] for kind, value in FILES.items()},
        "label_mapping": {"world": 0, "sports": 1},
        "task_prompt": QUESTION,
        "cases": cases,
        "case_count": len(cases),
        "cross_sectional_not_future": True,
        "pretrained_model_execution": False,
        "independent_outcome_observer": False,
        "fair_cpu_model_budget_verified": False,
        "production_promotion": "DENY_ALL",
    }


def load_parquet(path: Path) -> list[dict]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise PanelError("reviewed pinned pyarrow required for parquet") from exc
    table = pq.read_table(path, columns=["text", "label"])
    if not {"text", "label"} <= set(table.column_names):
        raise PanelError("wrong source table")
    return table.select(["text", "label"]).to_pylist()


def prepare(train: Path, holdout: Path) -> tuple[dict, dict]:
    check_file(train, "train")
    check_file(holdout, "calibration_test")
    panel = select_rows(load_parquet(train), load_parquet(holdout))
    receipt = {
        "schema": "hepta.stem.agnews-input-receipt.v1",
        "panel_digest": sha(canonical(panel)),
        "source_sha256": panel["dataset_file_sha256"],
        "counts_by_split_label": {
            f"{split}/{label}": sum(
                row["split"] == split and row["label"] == label
                for row in panel["cases"]
            )
            for split in QUOTAS for label in (0, 1)
        },
        "future_longitudinal_evidence": False,
        "physical_model_weights_executed": False,
        "external_source_signer_authenticated": False,
        "production_promotion": "DENY_ALL",
    }
    return panel, receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Offline exact-hash public task panel")
    parser.add_argument("--train-parquet", type=Path, required=True)
    parser.add_argument("--holdout-parquet", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    panel, receipt = prepare(args.train_parquet, args.holdout_parquet)
    args.output.write_bytes(canonical(panel))
    args.receipt.write_bytes(canonical(receipt))
    print(json.dumps(receipt, sort_keys=True))
