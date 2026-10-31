"""Explicitly allocate the reserve; the original unallocated-role guard stays intact."""

import hashlib
import json
from pathlib import Path
import time

from ...abc_recovery.base_recovery import file_sha, write_json
from ...abc_next.settings import MANIFEST
from ...v7.sources import _read_cache, build_manifest, digest, read_manifest


HERE = Path(__file__).parent
ASSIGNMENT = HERE / "ROLE_ASSIGNMENT.json"
ROLE = "repair_test"
ORIGIN_ROLE = "unallocated_test"


def register():
    from .protocol import source_identity
    allocation = source_identity()
    write_json(ASSIGNMENT, {"schema": "hepta.abc4.explicit-reserve-assignment.v1",
        "registered_unix_ns": time.time_ns(), "origin_manifest_sha256": file_sha(MANIFEST),
        "source_allocation_sha256": file_sha(HERE / "SOURCE_ALLOCATION.json"),
        "origin_role": ORIGIN_ROLE, "assigned_role": ROLE, "allocation": allocation,
        "purpose": "new frozen confirmation of the matched-success-reference repair",
        "authorization_scope": "User-authorized next experimental round on new frozen sources; metadata allocation precedes any model outcome access",
        "original_loader_modified": False, "old_excluded_roles_allowed": False,
        "materialization_condition": "complete frozen20-model evaluation protocol plus explicit access registration; only this assigned role",
        "loader_sha256": file_sha(__file__), "new_source_outcomes_opened": False})
    print(json.dumps({"assignment_sha256": file_sha(ASSIGNMENT), "assigned_role": ROLE}), flush=True)


def verify_assignment():
    from .protocol import source_identity
    record = json.loads(ASSIGNMENT.read_text())
    if (record["schema"] != "hepta.abc4.explicit-reserve-assignment.v1"
            or record["origin_manifest_sha256"] != file_sha(MANIFEST)
            or record["source_allocation_sha256"] != file_sha(HERE / "SOURCE_ALLOCATION.json")
            or record["origin_role"] != ORIGIN_ROLE or record["assigned_role"] != ROLE
            or record["allocation"] != source_identity() or record["loader_sha256"] != file_sha(__file__)):
        raise ValueError("Explicit new-source assignment identity changed")
    return record


def materialize(cache, protocol_path):
    """Original archives are checked again, after all candidates are frozen."""
    from ...v6.data import SourceCorpus, SourceSplit
    from .evaluate import verify
    import torch

    spec = json.loads(Path(protocol_path).read_text())
    verify(spec)
    assignment = verify_assignment()
    access = json.loads((Path(spec["output"]) / "access-registration.json").read_text())
    if (access["protocol_sha256"] != file_sha(protocol_path)
            or access["role"] != ROLE or access["origin_role"] != ORIGIN_ROLE
            or access["role_assignment_sha256"] != file_sha(ASSIGNMENT)
            or access["source_identity"] != assignment["allocation"]):
        raise ValueError("Source materialization lacks its exact prospective access registration")
    original = read_manifest(MANIFEST)
    if original != build_manifest(cache):
        raise ValueError("Original manifest differs from validated source archive reconstruction")
    registered = original["roles"][ORIGIN_ROLE]
    ids = tuple(registered["source_ids"])
    if hashlib.sha256("\n".join(ids).encode()).hexdigest() != assignment["allocation"]["ordered_source_ids_sha256"]:
        raise ValueError("Assigned source identities differ from the original reserve")
    images, labels, hashes = _read_cache(cache)[registered["official_partition"]]
    indices = [int(identity.split(":")[2]) for identity in ids]
    if any(identity.rsplit(":", 1)[1] != hashes[index] for identity, index in zip(ids, indices)):
        raise ValueError("Actual original pixels differ from their assigned source identity")
    pixels = torch.frombuffer(bytearray(images), dtype=torch.uint8).reshape(-1, 1, 28, 28)
    values = torch.tensor(list(labels), dtype=torch.long)
    split = SourceSplit(pixels[indices].clone(), values[indices].clone(), ids,
                        tuple(identity.rsplit(":", 1)[1] for identity in ids))
    derived = {"schema": "hepta.abc4.assigned-source-corpus.v1",
        "origin_manifest_sha256": file_sha(MANIFEST), "role_assignment_sha256": file_sha(ASSIGNMENT),
        "roles": {ROLE: registered}, "origin_role": ORIGIN_ROLE}
    derived["manifest_sha256"] = digest(derived)
    return SourceCorpus({ROLE: split}, derived)


if __name__ == "__main__":
    register()
