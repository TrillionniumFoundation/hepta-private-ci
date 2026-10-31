"""Freeze authored tasks, source identities and actual pretrained features.

Feature extraction sees text, never task labels or expected payload outputs.
The exported train NPZ is the only dataset needed by the migration workers.
"""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import time

import numpy as np

from backend import FrozenEncoder
import tasks


ROOT = Path(__file__).resolve().parent


def digest(value):
    return hashlib.sha256(tasks.canonical(value)).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False,
                               allow_nan=False) + "\n", encoding="utf-8")


def freeze(output):
    names = sorted(list(ROOT.glob("*.py")) + list(ROOT.glob("*.json"))
                   + list(ROOT.glob("*.txt")))
    identities = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in names}
    copied = output / "EXECUTED_SOURCE"
    copied.mkdir()
    for path in names:
        (copied / path.name).write_bytes(path.read_bytes())
    record = {"source_hashes": identities, "created_unix_seconds": time.time(),
              "base_commit": "0209aaa10c2a1c57f7f9e38fbd8c0cf6bb3e0190",
              "head_at_freeze": subprocess.check_output(
                  ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "git_status_at_freeze": subprocess.check_output(
                  ["git", "status", "--short"], cwd=ROOT, text=True),
              "platform": platform.platform(), "python": platform.python_version()}
    write_json(output / "FREEZE.json", record)
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/inputs")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    frozen = freeze(args.output)
    started, cpu = time.perf_counter(), time.process_time()
    encoder = FrozenEncoder(args.model_dir, threads=1)
    datasets = {split: tasks.load_split(split) for split in ("train", "calibration", "test")}
    for frontier in (3, 4, 5, 6):
        for split in ("train", "calibration", "test"):
            datasets[f"profile-{frontier}-{split}"] = tasks.profile_learning_split(split, frontier)
    for name, rows in datasets.items():
        texts = [row["text"] for row in rows]
        X = encoder.encode(texts)
        y = np.array([row["label"] for row in rows], dtype=np.int64)
        np.savez_compressed(args.output / f"{name}_features.npz", X=X, y=y)
        write_json(args.output / f"{name}_rows.json", rows)
    # Compositions expose their step decomposition publicly. The evaluator alone
    # retains expected outputs; every step selection is made from its own text.
    compositions = tasks.composition_cases()
    texts = [text for case in compositions for text in case["steps"]]
    np.savez_compressed(args.output / "composition_features.npz", X=encoder.encode(texts))
    write_json(args.output / "composition_rows.json", compositions)
    hybrid = [{**case, "original_text": case["text"],
               **tasks.profile_input(case, tasks.profile_journal())}
              for case in tasks.profile_cases()]
    np.savez_compressed(args.output / "hybrid_features.npz", X=encoder.encode([row["text"] for row in hybrid]))
    write_json(args.output / "hybrid_rows.json", hybrid)
    source_version = digest(datasets["train"])
    manifest = {"encoder_hash": encoder.manifest_hash, "source_version": source_version,
                "encoder": encoder.manifest, "stats": encoder.stats,
                "split_sizes": {name: len(rows) for name, rows in datasets.items()},
                "source_kind": "authored executable standard-library fixtures",
                "production_traffic": False, "generative_language_model": False,
                "frozen_source_digest": digest(frozen["source_hashes"]),
                "wall_seconds": time.perf_counter() - started,
                "cpu_seconds": time.process_time() - cpu}
    write_json(args.output / "encoder_manifest.json", manifest)
    files = {str(path.relative_to(args.output)): {"bytes": path.stat().st_size,
             "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
             for path in sorted(args.output.rglob("*")) if path.is_file()}
    write_json(args.output / "INVENTORY.json", files)
    print(json.dumps({"output": str(args.output), "manifest": manifest}, ensure_ascii=False))


if __name__ == "__main__":
    main()
