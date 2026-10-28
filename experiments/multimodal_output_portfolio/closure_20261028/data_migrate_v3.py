"""Activate the approved train-only expansion without altering previous evidence."""
import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import time

from .data_sources import digest, save
from .data_v3_contract import APPROVED_SOURCE_SHA, implementation_hashes, validate_receipt


def activate(original, proposal, destination):
    old = json.loads((original / "SOURCE_PROTOCOL.json").read_text())
    new = json.loads(proposal.read_text())
    body = dict(new)
    if body.pop("protocol_sha256") != digest(body) or new["protocol_sha256"] != APPROVED_SOURCE_SHA:
        raise ValueError("Unapproved source expansion")
    if (len(old["selected"]) != 768 or new["selected"][:768] != old["selected"]
            or new["coverage_amendment"]["parent_source_protocol_sha256"] != old["protocol_sha256"]
            or new["ontology"] != old["ontology"]):
        raise ValueError("An original source, event, role or ontology changed")
    if destination.exists():
        raise FileExistsError("Preserve the previous activation attempt")
    destination.mkdir(parents=True)
    shutil.copyfile(proposal, destination / "SOURCE_PROTOCOL.json")
    for path in original.glob("*.zip"):
        os.link(path, destination / path.name)
    (destination / "pretrained").symlink_to((original / "pretrained").resolve(), target_is_directory=True)
    parent = json.loads((original / "FEATURE_PROTOCOL.json").read_text())
    shutil.copyfile(original / "FEATURE_PROTOCOL.json", destination / "PARENT_FEATURE_PROTOCOL.json")
    shutil.copyfile(original / "SOURCE_PROTOCOL.json", destination / "PARENT_SOURCE_PROTOCOL.json")
    contract = {**parent, "schema": "hepta.closure.semantic-feature-protocol.v2",
                "source_protocol_sha256": new["protocol_sha256"],
                "source_hashes": implementation_hashes(), "parent_feature_protocol_sha256": digest(parent),
                "migration": "Original extraction receipts and hashes preserved separately; allocation metadata only changes. New sources use the unchanged decoder, window rule and pretrained feature implementations."}
    save(destination / "FEATURE_PROTOCOL.json", contract)
    expected = {row["source_id"]: row for row in new["selected"]}
    copied, byte_sources = [], {}
    for origin in sorted((original / "prepared").glob("*/*/RECEIPT.json")):
        receipt = json.loads(origin.read_text())
        source = expected[receipt["source_id"]]
        folder = destination / "prepared" / source["role"] / source["source_id"]
        folder.mkdir(parents=True)
        for name, pin in receipt["retained_files"].items():
            path = origin.parent / name
            if digest(path.read_bytes()) != pin:
                raise ValueError("An immutable original tensor or feature changed")
            os.link(path, folder / name)
        shutil.copyfile(origin, folder / "ORIGIN_RECEIPT.json")
        migrated = copy.deepcopy(receipt)
        migrated.update(schema="hepta.closure.prepared-source.v3", source_protocol_sha256=new["protocol_sha256"],
                        feature_protocol_sha256=digest(contract),
                        allocation_migration_v3={"origin_receipt_sha256": digest(origin.read_bytes()),
                            "parent_feature_protocol_sha256": digest(parent),
                            "metadata_migration_source_hashes": contract["source_hashes"],
                            "array_or_feature_bytes_changed": False})
        validate_receipt(destination, new, source, migrated)
        save(folder / "RECEIPT.json", migrated)
        pin = receipt["original_source_sha256"]
        if pin in byte_sources:
            raise ValueError("Different source IDs contain identical original video bytes")
        byte_sources[pin] = source["source_id"]
        copied.append({"source_id": source["source_id"], "role": source["role"],
                       "origin_receipt_sha256": digest(origin.read_bytes()),
                       "new_receipt_sha256": digest((folder / "RECEIPT.json").read_bytes())})
    record = {"schema": "hepta.closure.source-expansion-activation.v1", "created_at_unix": time.time(),
              "source_protocol_sha256": new["protocol_sha256"], "parent_source_protocol_sha256": old["protocol_sha256"],
              "approved_proposal_file_sha256": digest(proposal.read_bytes()), "all_original_768_entries_identical": True,
              "roles": new["roles"], "migrated_sources": copied, "literal_source_byte_duplicates": [],
              "new_source_pixels_read": 0, "development_calibration_qualification_predictions": 0,
              "implementation_sha256": implementation_hashes()}
    save(destination / "ACTIVATION.json", record)
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("original", "proposal", "destination"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = activate(args.original, args.proposal, args.destination)
    print(json.dumps({key: value for key, value in result.items() if key != "migrated_sources"}))
