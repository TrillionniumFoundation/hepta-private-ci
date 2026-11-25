"""Select reviewed current guards while retaining the complete historical cases.

The fixed projection binds every field of each current guard. Source SHA fields
remain part of that identity; the original protected-source verifier still
decides whether an actual source mutation is rejected.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path


PROJECTION_SHA256 = "3b1ce93d06dc08e0aa52c3cafe1b1bd37150d88ac516935564912163dc67cc65"


def _canonical_sha256(value):
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def load_current_contract(root, manifest, identifier, historical_path):
    projection = json.loads(
        Path(__file__).with_name("original_current_source_contracts.json").read_text()
    )
    if _canonical_sha256(projection) != PROJECTION_SHA256:
        raise AssertionError("unreviewed current-source projection")
    current = projection["contracts"][str(identifier)]
    historical_path = Path(historical_path)
    if historical_path.is_absolute():
        historical_path = historical_path.relative_to(root)
    if historical_path.as_posix() != current["historical_path"]:
        raise AssertionError("wrong historical contract")
    original = (root / historical_path).read_bytes()
    if hashlib.sha256(original).hexdigest() != current["historical_sha256"]:
        raise AssertionError("historical contract bytes changed")
    rows = [
        row for row in manifest["protected_file"]
        if row["path"] in current["record_counts"]
    ]
    if Counter(row["path"] for row in rows) != Counter(current["record_counts"]):
        raise AssertionError("missing or unknown guard for a protected path")
    expected = Counter(
        (row["path"], row["canonical_sha256"]) for row in current["guard_rows"]
    )
    actual = Counter((row["path"], _canonical_sha256(row)) for row in rows)
    if actual != expected:
        raise AssertionError("changed, missing, duplicate or unknown complete guard")
    return json.loads(original), current, rows


def project_case(current, original):
    matches = [
        item["after"] for item in current["case_mappings"]
        if item["before"] == original
    ]
    if len(matches) > 1:
        raise AssertionError("ambiguous original-case mapping")
    return matches[0] if matches else original
