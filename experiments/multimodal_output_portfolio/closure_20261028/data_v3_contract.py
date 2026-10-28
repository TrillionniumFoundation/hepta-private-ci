"""Validate expanded source identities and truthful, byte-preserving migrations."""
import json
from pathlib import Path

from .data_sources import digest

APPROVED_SOURCE_SHA = "ad58bf5529af473f722c8e48a44f34ae07e364356b664a3a79458fecf1405b9d"
SOURCE_FILES = ("data_v3_contract.py", "data_migrate_v3.py", "data_prepare_v3.py",
                "data_prepare_v2.py", "data_prepare.py", "semantic_backbones.py", "semantic_tsm.py")


def implementation_hashes():
    return {name: digest((Path(__file__).parent / name).read_bytes()) for name in SOURCE_FILES}


def load_plan(root):
    plan = json.loads((root / "SOURCE_PROTOCOL.json").read_text())
    body = dict(plan)
    expected = body.pop("protocol_sha256")
    if digest(body) != expected or expected != APPROVED_SOURCE_SHA:
        raise ValueError("The approved v3 source allocation changed")
    if plan["schema"] != "hepta.closure.natural-sources.v3":
        raise ValueError("Unexpected source allocation schema")
    return plan


def feature_contract(root, plan):
    contract = json.loads((root / "FEATURE_PROTOCOL.json").read_text())
    parent = json.loads((root / "PARENT_FEATURE_PROTOCOL.json").read_text())
    if (contract["source_protocol_sha256"] != plan["protocol_sha256"]
            or contract["source_hashes"] != implementation_hashes()
            or contract["parent_feature_protocol_sha256"] != digest(parent)
            or parent["source_protocol_sha256"] != plan["coverage_amendment"]["parent_source_protocol_sha256"]
            or contract["weights"] != parent["weights"]):
        raise ValueError("Feature implementation, allocation or parent provenance changed")
    for name, pin in parent["source_hashes"].items():
        if digest((Path(__file__).parent / name).read_bytes()) != pin:
            raise ValueError("Compatible parent feature implementation changed")
    return contract, parent


def validate_receipt(root, plan, source, receipt, *, verify_bytes=True):
    contract, parent = feature_contract(root, plan)
    directory = root / "prepared" / source["role"] / source["source_id"]
    if (receipt["source_id"] != source["source_id"] or receipt["role"] != source["role"]
            or receipt["source_protocol_sha256"] != plan["protocol_sha256"]
            or receipt["feature_protocol_sha256"] != digest(contract)
            or receipt["original_source_bytes"] != source["source_bytes"]
            or receipt["original_member"] != source["member"]
            or receipt["original_url"] != plan["archive"][source["official_split"]]["url"]):
        raise ValueError("Prepared source provenance mismatch")
    migration = receipt.get("allocation_migration_v3")
    if migration is None:
        if receipt["source_hashes"] != contract["source_hashes"]:
            raise ValueError("New source extraction implementation changed")
    else:
        origin_path = directory / "ORIGIN_RECEIPT.json"
        origin = json.loads(origin_path.read_text())
        if (digest(origin_path.read_bytes()) != migration["origin_receipt_sha256"]
                or migration["parent_feature_protocol_sha256"] != digest(parent)
                or migration["metadata_migration_source_hashes"] != contract["source_hashes"]
                or origin["source_protocol_sha256"] != parent["source_protocol_sha256"]):
            raise ValueError("Original extraction receipt or migration binding changed")
        for key in ("source_id", "role", "original_source_sha256", "original_source_bytes",
                    "original_member", "original_url", "retained_files", "events"):
            if receipt[key] != origin[key]:
                raise ValueError("Migration changed original bytes, events or source identity")
        if "source_hashes" in origin:
            if (origin["source_hashes"] != parent["source_hashes"]
                    or origin["feature_protocol_sha256"] != digest(parent)
                    or receipt["source_hashes"] != origin["source_hashes"]):
                raise ValueError("Original feature execution was incorrectly relabelled")
        elif (source["role"] != "generator_train" or set(origin["retained_files"]) != {"EVENT.npz"}
                or origin["source_code_sha256"] != parent["source_hashes"]["data_prepare.py"]
                or not origin.get("migration", {}).get("time_window_identical")):
            raise ValueError("Unsupported older tensor-only provenance")
    events = source["events"][:source["retained_event_count"]]
    if len(receipt["events"]) != len(events):
        raise ValueError("Frozen retained event count changed")
    for index, (row, event) in enumerate(zip(receipt["events"], events)):
        if (row["event_id"] != f'{source["source_id"]}-closure-{index}'
                or row["source_id"] != source["source_id"] or row["role"] != source["role"]
                or row["source_sha256"] != receipt["original_source_sha256"]
                or any(row[key] != value for key, value in event.items())):
            raise ValueError("Retained event labels or temporal windows changed")
    if verify_bytes:
        for name, pin in receipt["retained_files"].items():
            if digest((directory / name).read_bytes()) != pin:
                raise ValueError("Retained tensor or feature bytes changed")
    return receipt
