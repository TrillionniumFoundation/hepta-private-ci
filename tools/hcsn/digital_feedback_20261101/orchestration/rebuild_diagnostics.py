"""Rebuild deterministic diagnostic tables from preserved raw decisions.

Raw training/confirmation records are never omitted. Only duplicate derived
tables may be deferred, and their original byte hashes must be reproduced.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

from ..diagnostics import audit_episodes, build_support


def read(path):
    path = Path(path)
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw)


def rebuild(fitted, training, output):
    fitted, training, output = Path(fitted), Path(training), Path(output)
    manifest = read(fitted / "DERIVED_DIAGNOSTICS.json")
    restored = []
    for record in manifest["derived_files"]:
        split = record["split"]
        episodes = read(fitted / (split + "_episodes.json.gz"))
        cohorts = read(fitted / (split + "_cohort.json"))
        publics = {item["id"]: read(fitted / "worlds" / item["id"] / "public.json")
                   for item in cohorts["records"]}
        grouped = {}
        for episode in episodes:
            grouped.setdefault(episode["candidate"], []).append(episode)
        audits = {}
        for candidate, raw in grouped.items():
            receipt_path = training / "training" / (candidate + ".json.gz")
            if candidate != "bayes" and not receipt_path.exists():
                raise FileNotFoundError(receipt_path)
            receipt = read(receipt_path) if receipt_path.exists() else {}
            rounds = {str(r["round_id"]): r.get("supervised_rows", [])
                      for r in receipt.get("visit_rounds", [])}
            support = build_support(receipt.get("behavior_rows_with_support", []), rounds)
            audits[candidate] = audit_episodes(raw, publics, support)
        raw = (json.dumps(audits, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
        encoded = gzip.compress(raw, compresslevel=6, mtime=0)
        digest = hashlib.sha256(encoded).hexdigest()
        if len(encoded) != record["bytes"] or digest != record["sha256"]:
            raise ValueError("derived diagnostic bytes differ from their recorded identity")
        destination = output / record["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as stream:
            stream.write(encoded)
        restored.append(dict(path=record["path"], sha256=digest, bytes=len(encoded)))
    return dict(schema="digital-feedback-derived-restore-v1", files=restored,
                all_original_hashes_reproduced=True,
                scope="same frozen diagnostic source/runtime; raw decision/model bytes remain archived")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fit", type=Path, required=True)
    parser.add_argument("--training-fit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(rebuild(args.fit, args.training_fit, args.output), sort_keys=True))
