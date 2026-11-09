"""Check bounded exposure declarations, never authenticate unseen-task custody.

Training must contain at least one declaration. Empty tuning/selection lists
explicitly declare that those sets were not used. One successor is required.
Different tasks within a split may share a lineage; different splits may not.
The caller must read the registry through the existing hash-bound Evidence API.
"""

import re

import hepta_cell_joint_config as joint


SCHEMA = "hepta.cell-source-registry.v1"
MAX_TASKS = 4096
SPLITS = ("training", "tuning", "selection")
IDENTITY = re.compile(r"[\w./:@-]{1,256}\Z")


def shape(value, fields):
    if not isinstance(value, dict) or len(value) != len(fields) or set(value) != fields:
        raise ValueError("source registry has unknown or missing fields")


def review(document, *, configuration_sha256, protocol_sha256, successor_task_id):
    """Verify only declared identities, exact pins and pairwise split separation."""
    shape(
        document,
        {
            "schema",
            "joint_configuration_sha256",
            "protocol_sha256",
            *SPLITS,
            "successor",
        },
    )
    if document["schema"] != SCHEMA:
        raise ValueError("unknown source registry schema")
    for key, expected in (
        ("joint_configuration_sha256", configuration_sha256),
        ("protocol_sha256", protocol_sha256),
    ):
        declared = document[key]
        if (
            not isinstance(declared, str)
            or joint.SHA256.fullmatch(declared) is None
            or declared != expected
        ):
            raise ValueError(f"source registry conflicts with the declared {key}")
    if any(not isinstance(document[split], list) for split in SPLITS):
        raise ValueError("source registry exposure sets must be lists")
    count = 1 + sum(len(document[split]) for split in SPLITS)
    if not document["training"] or count > MAX_TASKS:
        raise ValueError("source registry needs training and at most 4096 total tasks")
    ids, digests, lineages = {}, {}, {}
    groups = [(split, document[split]) for split in SPLITS]
    groups.append(("successor", [document["successor"]]))
    for split, records in groups:
        for record in records:
            shape(record, {"task_id", "task_sha256", "lineage_group"})
            task_id, task_sha, lineage = (
                record["task_id"],
                record["task_sha256"],
                record["lineage_group"],
            )
            if any(
                not isinstance(value, str) or IDENTITY.fullmatch(value) is None
                for value in (task_id, lineage)
            ):
                raise ValueError("source registry task and lineage IDs must be bounded")
            if (
                not isinstance(task_sha, str)
                or joint.SHA256.fullmatch(task_sha) is None
            ):
                raise ValueError("source registry task requires a complete SHA256")
            if task_id in ids:
                raise ValueError(
                    "source registry has a duplicate or conflicting task ID"
                )
            if task_sha in digests:
                raise ValueError(
                    "source registry reuses task bytes under a duplicate or alias"
                )
            if lineage in lineages and lineages[lineage] != split:
                raise ValueError("source registry lineage crosses exposure sets")
            ids[task_id], digests[task_sha], lineages[lineage] = task_sha, split, split
    successor = document["successor"]
    if successor["task_id"] != successor_task_id:
        raise ValueError("source registry successor differs from the declared task")
    return {
        "schema": "hepta.cell-source-registry-review.v1",
        "registry_schema": SCHEMA,
        "declaration_integrity": "verified",
        "declared_split_disjointness_verified": True,
        "declaration_counts": {
            **{split: len(document[split]) for split in SPLITS},
            "successor": 1,
        },
        "declared_successor": dict(successor),
        "registry_authenticity_verified": False,
        "successor_custody_verified": False,
        "successor_unseen_verified": False,
    }
