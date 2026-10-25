"""Label-separated V4 input identities, complete censuses and local hash seals."""

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np

from cell_field_action_io import project, split_arrays, write_json
from cell_field_features import file_hash, load_features


TRAIN_ROLES = {"old_train", "old_probe", "current_train", "current_probe"}


def load_task(data, features, protocol, task):
    data, features, protocol = Path(data), Path(features), Path(protocol)
    plan = json.loads(protocol.read_bytes())
    digest = file_hash(protocol)
    if task not in plan["tasks"]:
        raise ValueError("undeclared task")
    receipt = json.loads((data / "data_receipt.json").read_bytes())
    if receipt["protocol_sha256"] != digest:
        raise ValueError("data protocol mismatch")
    for name in ("sources.json", "predictors.json", "train_labels.json"):
        path = data / name
        expected = receipt["files"][name]
        if path.is_symlink() or file_hash(path) != expected["sha256"] or path.stat().st_size != expected["bytes"]:
            raise ValueError("data receipt mismatch: " + name)
    sources = json.loads((data / "sources.json").read_bytes())["rows"]
    labels = json.loads((data / "train_labels.json").read_bytes())
    counts = plan["source_counts"][task]
    n = sum(counts.values())
    if (len(sources) != n or [row["index"] for row in sources] != list(range(n))
            or Counter(row["role"] for row in sources) != counts
            or len({row["source_id"] for row in sources}) != n
            or len({row["component_id"] for row in sources}) != n
            or set(labels["roles"]) != TRAIN_ROLES):
        raise ValueError("complete unique component census and train-only labels required")
    for role, values in labels["roles"].items():
        expected = [row["index"] for row in sources if row["role"] == role]
        if (values["indices"] != expected
                or Counter(values["labels"]) != {c: counts[role] // 4 for c in range(4)}
                or values["source_ids"] != [sources[i]["source_id"] for i in expected]):
            raise ValueError("training labels do not match frozen identities")
    matrix, feature_report = load_features(features, digest)
    fixed = feature_report["plan"]
    if (matrix.shape != (n, 384) or fixed["data_receipt_sha256"] != file_hash(data / "data_receipt.json")
            or fixed["predictors_sha256"] != file_hash(data / "predictors.json")
            or fixed["source_ids"] != [row["source_id"] for row in sources]
            or fixed["labels_enter_encoder"] is not False or feature_report["encoder_updates"] != 0
            or feature_report["encoder_load"]["model"]["trainable_parameter_count"] != 0):
        raise ValueError("frozen encoder or source order mismatch")
    projected, projection = project(matrix, plan)
    return {"plan": plan, "protocol_sha256": digest, "receipt": receipt,
            "sources": sources, "projected": projected, "projection": projection,
            "split": split_arrays(projected, labels), "feature_report": feature_report,
            "input_hashes": {name: file_hash(data / name) for name in
                ("sources.json", "predictors.json", "train_labels.json", "data_receipt.json")}}


def seal_run(output, protocol):
    output, protocol = Path(output), Path(protocol)
    if (output / "pre_evaluation_seal.json").exists():
        raise ValueError("never overwrite a sealed run")
    files = {}
    for path in sorted(output.rglob("*")):
        if path.is_symlink():
            raise ValueError("sealed evidence cannot contain symlinks")
        if path.is_file():
            files[path.relative_to(output).as_posix()] = {"sha256": file_hash(path), "bytes": path.stat().st_size}
    seal = {"schema": "hepta.cell-field-pre-evaluation-seal.v4", "files": files,
            "protocol_sha256": file_hash(protocol), "final_labels_opened": False,
            "validation_labels_opened": False, "sealed_at": datetime.now(timezone.utc).isoformat(),
            "scope": "local integrity and recorded execution order; no signature or independent attestation"}
    write_json(output / "pre_evaluation_seal.json", seal)
    return seal
