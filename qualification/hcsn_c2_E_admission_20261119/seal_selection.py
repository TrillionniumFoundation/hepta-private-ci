"""Bind the fixed 21 selected models and completed D temperatures; no E reads."""

import hashlib
import json
import math
from pathlib import Path
import sys
import zipfile

HERE = Path(__file__).resolve().parent
QUALIFICATION = HERE.parent


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def compose():
    ledger_path = QUALIFICATION / "hcsn_c2_d_selection_20261119/evidence/LEDGER.json"
    ledger_raw = ledger_path.read_bytes()
    if digest(ledger_raw) != "5e3e64f332d9a03389c8ac0e4f3de478e9f7c612124e9bec2b4d82c21d3f263b":
        raise ValueError("selection ledger identity changed")
    ledger = json.loads(ledger_raw)
    archive_path = QUALIFICATION / "hcsn_c2_d_temperature_20261119/evidence/native/calibration-originals.zip"
    if digest(archive_path.read_bytes()) != "c0bd19d9ff00dcafb7da8700d54c3febf8d48af3fe5d1ccc34c96446028560ca":
        raise ValueError("temperature originals changed")
    models = []
    with zipfile.ZipFile(archive_path) as archive:
        manifest_raw = archive.read("RESULTS/TEMPERATURE_MANIFEST.json")
        manifest = json.loads(manifest_raw)
        if manifest["status"] != "COMPLETE_E_BLOCKED" or manifest["complete_temperatures"] != 21:
            raise ValueError("incomplete temperature manifest")
        receipts = {r["name"]: r for r in manifest["receipts"]}
        if len(receipts) != 21 or set(receipts) != {r["name"] for r in ledger["roster"]}:
            raise ValueError("missing or extra selected models")
        for model in ledger["roster"]:
            item = receipts[model["name"]]
            raw = archive.read("RESULTS/" + model["name"] + ".json")
            if digest(raw) != item["receipt"]["sha256"] or len(raw) != item["receipt"]["bytes"]:
                raise ValueError("temperature receipt byte identity")
            receipt = json.loads(raw)
            if receipt["selected_model"] != model or receipt["status"] != "CALIBRATED_AND_ARITHMETIC_CHECKED":
                raise ValueError("temperature/selected model mismatch")
            if receipt["independent_arithmetic"]["status"] != "PASS" or receipt["E_payload_or_labels_accessed"]:
                raise ValueError("temperature arithmetic or E separation")
            temperature, beta = receipt["fit"]["temperature"], receipt["fit"]["beta"]
            if not math.isfinite(temperature) or not .01 <= temperature <= 100 or temperature != item["temperature"]:
                raise ValueError("temperature domain or manifest mismatch")
            if beta != item["beta"] or temperature != 1.0 / beta:
                raise ValueError("inverse temperature mismatch")
            if item["model_binding_sha256"] != model["model_binding_sha256"] or item["D_logits_sha256"] != model["D_logits"]["sha256"]:
                raise ValueError("calibration input mismatch")
            models.append({key: model[key] for key in ["name", "arm", "seed", "learning_rate", "selected_epoch",
                          "checkpoint", "configuration_canonical_sha256", "model_tensor_manifest_sha256",
                          "model_binding_sha256", "source_map_canonical_sha256", "D_logits", "D_manifest_sha256",
                          "D_episode_order_sha256", "D_label_array_sha256", "recorded_training_adequacy"]} |
                          {"temperature": temperature, "beta": beta, "temperature_receipt": item["receipt"]})
    return {"schema": "C2-fixed-model-and-D-temperature-seal-v1", "status": "SEALED_METADATA_E_NOT_ADMITTED",
            "selection_ledger_sha256": digest(ledger_raw), "temperature_manifest_sha256": digest(manifest_raw),
            "temperature_archive_sha256": digest(archive_path.read_bytes()), "models": models,
            "calibration_source_commit": "a81f9e13cab9d27b0a59248e68dc11f32c61b652",
            "calibration_result_commit": "922b9ea10a3aa68bacec714948badb4c8ff2d3b1",
            "runtime_restoration_result_commit": "12641597631d84d292ae35133540d7abe58b171d",
            "E_data_read": False, "E_execution_admitted": False, "automatic_trigger": False,
            "scope": "Model and temperature choices are immutable metadata. No E data, predictions or score are present; original admission conditions remain separate."}


if __name__ == "__main__":
    raw = (json.dumps(compose(), sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    target = HERE / "SEALED_SELECTION.json"
    if "--verify-existing" in sys.argv:
        if target.read_bytes() != raw:
            raise ValueError("sealed selection differs from exact recomposition")
    else:
        with target.open("xb") as stream:
            stream.write(raw)
    print(json.dumps({"models": 21, "sha256": digest(raw), "bytes": len(raw), "E_data_read": False}))
