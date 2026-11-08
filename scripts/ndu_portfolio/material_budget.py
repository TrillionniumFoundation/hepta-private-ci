"""Validate a pinned, serialized material ledger after an image-transfer anchor.

Receipts retain their original UTF-8 bytes inside the index. This verifies the
hash chain and accounting, not remote body authenticity or a distributed lock.
The dispatcher must select the latest terminal head before starting a consumer.
"""

import hashlib
import json
from pathlib import Path


SCHEMA = "hepta.material-ledger-chain.v1"
INCREMENT = "hepta.bounded-material-increment.v1"
LIMIT = 131072


def advance_material_budget(anchor, anchor_sha256, path, expected_sha256):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > LIMIT:
        raise ValueError("Invalid material ledger index file")
    with path.open("rb") as stream:
        data = stream.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError("Material ledger index exceeds its byte cap")
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError("Material ledger index hash differs")
    chain = json.loads(data)
    if (
        chain.get("schema") != SCHEMA
        or chain.get("anchor_sha256") != anchor_sha256
        or not isinstance(chain.get("receipts"), list)
        or len(chain["receipts"]) > 32
    ):
        raise ValueError("Material ledger anchor or schema differs")
    previous = anchor_sha256
    spent = anchor["cumulative_body_bytes"]
    cap = anchor["shared_cap_bytes"]
    for entry in chain["receipts"]:
        raw = entry["receipt_utf8"].encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        if (
            type(entry.get("bytes")) is not int
            or not 0 < len(raw) == entry["bytes"] <= LIMIT
            or digest != entry.get("sha256")
        ):
            raise ValueError("Material increment bytes or hash differ")
        receipt = json.loads(raw)
        counts = tuple(
            receipt.get(key)
            for key in (
                "prior_body_bytes",
                "new_body_bytes",
                "cumulative_body_bytes",
                "shared_cap_bytes",
                "reservation_bytes",
            )
        )
        if (
            receipt.get("schema") != INCREMENT
            or receipt.get("status") not in ("completed", "failed")
            or receipt.get("prior_receipt_sha256") != previous
            or any(type(value) is not int for value in counts)
            or counts[0] != spent
            or counts[3] != cap
            or not 0 <= counts[1] <= counts[4] <= cap - spent
            or counts[4] == 0
            or counts[2] != spent + counts[1]
        ):
            raise ValueError("Material increment chain or accounting differs")
        attempts = receipt.get("attempts")
        if not isinstance(attempts, list) or any(
            attempt.get("status") not in ("completed", "failed")
            or type(attempt.get("bytes_read")) is not int
            or attempt["bytes_read"] < 0
            for attempt in attempts
        ):
            raise ValueError("Material increment has unresolved attempts")
        if sum(attempt["bytes_read"] for attempt in attempts) != counts[1]:
            raise ValueError("Material increment attempt total differs")
        for attempt in attempts:
            body = attempt.get("body")
            if body is None and attempt["bytes_read"] == 0:
                continue
            if (
                not isinstance(body, dict)
                or type(body.get("bytes")) is not int
                or body["bytes"] != attempt["bytes_read"]
                or body["bytes"] <= 0
                or not isinstance(body.get("sha256"), str)
                or len(body["sha256"]) != 64
                or any(c not in "0123456789abcdef" for c in body["sha256"])
                or (
                    attempt["status"] == "completed"
                    and attempt.get("sha256") != body["sha256"]
                )
            ):
                raise ValueError("Material attempt body binding differs")
        previous, spent = digest, counts[2]
    if (
        chain.get("head_receipt_sha256") != previous
        or type(chain.get("cumulative_body_bytes")) is not int
        or chain["cumulative_body_bytes"] != spent
    ):
        raise ValueError("Material ledger declared head differs")
    return spent, previous, data
