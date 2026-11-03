"""Preserve V1 and make one pre-fit overlap repair, without loading a model."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()


def main():
    old_lock = json.loads((ROOT / "INPUT_LOCK.json").read_bytes())
    target = ROOT / "inputs-02"
    target.mkdir(exist_ok=False)
    manifest = dict(old_lock)
    manifest.update({"revision": 2, "previous_lock_sha256": hashlib.sha256((ROOT / "INPUT_LOCK.json").read_bytes()).hexdigest(),
                     "repair_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                     "models_loaded_before_repair": 0, "head_fits_before_repair": 0, "model_predictions_before_repair": 0,
                     "reason": "Model-free preflight found one normalized calibration wording shared with public fitting data.",
                     "label_or_record_changes": False, "changes": [], "files": {}})
    original = "What reading had been recorded for {entity} by {date}?"
    replacement = "At the reporting cutoff of {date}, retrieve the final observation already filed under {entity}."
    for split in ("calibration", "held"):
        raw = (ROOT / "inputs" / f"{split}.json").read_bytes()
        if hashlib.sha256(raw).hexdigest() != old_lock["files"][f"{split}.json"]["sha256"]:
            raise ValueError("previous frozen input changed")
        value = json.loads(raw)
        if split == "calibration":
            for row in value["rows"]:
                if row["family"] not in ("calibration.known.history.en.0", "calibration.time-conflict.en.0"):
                    continue
                owner = next(item for item in value["entities"] if item["entity"] == row["entity"])
                args = {"entity": owner["aliases"][0], "date": "2025-02-01"}
                old = original.format(**args)
                if old not in row["text"]:
                    raise ValueError("repair target differs from the frozen wording")
                new = row["text"].replace(old, replacement.format(**args))
                manifest["changes"].append({"id": row["id"], "old_text": row["text"], "new_text": new})
                row["text"] = new
            raw = encoded(value)
        with (target / f"{split}.json").open("xb") as stream:
            stream.write(raw)
        manifest["files"][f"{split}.json"] = {**old_lock["files"][f"{split}.json"], "bytes": len(raw),
                                                 "sha256": hashlib.sha256(raw).hexdigest()}
    if len(manifest["changes"]) != 3:
        raise ValueError("unexpected repair cardinality")
    with (ROOT / "INPUT_LOCK-02.json").open("xb") as stream:
        stream.write(encoded(manifest))
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
