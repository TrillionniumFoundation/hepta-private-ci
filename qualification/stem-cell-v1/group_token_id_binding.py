"""Canonical digest of the exact frozen Encoder input-ID stream (research only)."""
import hashlib
import json

def token_ids_sha256(values):
    if (type(values) not in (list, tuple) or not 1 <= len(values) <= 256
            or any(type(v) is not int or not 0 <= v <= 2**31-1 for v in values)):
        raise ValueError("bounded nonnegative integer token ID stream required")
    obj = {"schema": "hepta.group.encoder-token-ids.v1", "token_ids": list(values)}
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()
