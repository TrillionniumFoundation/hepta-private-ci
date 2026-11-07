"""Compare pinned, inert packet rosters without importing their contents."""

import hashlib
import json
from pathlib import Path

BASE = Path("/dev/shm/ndu_windows44_checkpoint_20261107")
OUT = Path("/dev/shm/ndu_windows44_packet_peer_20261107/REVISION_DELTA.json")
PINS = {
    "INPUT_ROSTER.json": "91d8207d90177d14c456d2dab88802c9d152bb80602ea1b11c082b949f2f5257",
    "INPUT_ROSTER_v2.json": "14df96951737d091acda46a1ec4c167e31f9d4244ad3dfd875bcceb71f194146",
}
rosters = []
for name, expected in PINS.items():
    data = (BASE / name).read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("ROSTER_IDENTITY")
    rosters.append(json.loads(data))
old, new = ({row["archive_name"]: row for row in r["packet_files"]} for r in rosters)
removed = set(old) - set(new)
if len(removed) != 1 or set(new) - set(old):
    raise ValueError("REVISION_MEMBERS")
alias = old[next(iter(removed))]
if alias["bytes"] != 8888 or not alias["source_path"].endswith(
    "/assertion_values44_v3.before_format.py.txt"
):
    raise ValueError("REMOVED_MEMBER")
if any(old[name] != row for name, row in new.items()):
    raise ValueError("RETAINED_OBJECT_CHANGED")
for key in (
    "separate_plain_publication",
    "excluded_private_identity_only",
    "omitted_implementation_identity_only",
):
    if rosters[0][key] != rosters[1][key]:
        raise ValueError("EXCLUSION_CONTRACT_CHANGED")
result = {
    "schema": "windows44-independent-revision-delta-v1",
    "decision": "PASS_EXACT_SINGLE_ALIAS_REMOVAL",
    "roster_sha256": PINS,
    "removed": alias,
    "retained_full_roster_objects_unchanged": len(new),
    "retained_original_bytes": sum(row["bytes"] for row in new.values()),
    "three_exclusion_inventories_unchanged": True,
    "original_package_finding": "Declared plain-source exclusion mismatch; not a secret leak or a new algorithm.",
    "payload_or_native_execution": False,
}
with OUT.open("x") as output:
    json.dump(result, output, indent=2)
    output.write("\n")
print(result["decision"])
