"""Fail-closed split and pre-reveal gate for prospective MemoryCell evaluation.

Caller-supplied timestamps and root IDs are NOT authenticated. This only
checks logical contamination and preserves the external-review requirement.
"""

from datetime import datetime
import re

HEX64 = re.compile(r"[0-9a-f]{64}\Z")
KINDS = frozenset(("new_fact", "updated_fact", "composition", "program"))
PARTITIONS = frozenset(("train", "select", "test"))


def check(condition, message):
    if not condition:
        raise ValueError(message)


def utc(s):
    check(isinstance(s, str) and s.endswith("Z"), "UTC Z timestamp required")
    try:
        value = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as e:
        raise ValueError("invalid UTC timestamp") from e
    check(value.utcoffset().total_seconds() == 0, "UTC offset required")
    return value


def admission(manifest):
    check(
        isinstance(manifest, dict)
        and manifest.get("schema") == "hepta.memory.prospective-source-cut.v1",
        "source cut schema required",
    )
    check(
        manifest.get("contains_answers") is False
        and manifest.get("publisher_answer_oracle") is False,
        "gold access or answer oracle prohibited",
    )
    registered = utc(manifest.get("registered_at"))
    frozen = utc(manifest.get("frozen_at"))
    check(registered < frozen, "registration must precede freeze")
    source = manifest.get("sources")
    check(
        isinstance(source, list) and 4 <= len(source) <= 100000,
        "bounded real source cohort required",
    )
    ids, blobs, families, kinds = set(), {}, {}, set()
    partition_counts = dict.fromkeys(PARTITIONS, 0)
    for row in source:
        check(isinstance(row, dict), "source object required")
        check(
            set(
                (
                    "id",
                    "family",
                    "partition",
                    "kind",
                    "source_digest",
                    "source_at",
                    "exposed_at",
                )
            )
            <= set(row),
            "source fields missing",
        )
        identity, family, part = row["id"], row["family"], row["partition"]
        check(
            isinstance(identity, str) and identity and identity not in ids,
            "duplicate source ID",
        )
        check(isinstance(family, str) and family, "missing family root")
        check(part in PARTITIONS, "invalid source partition")
        check(row["kind"] in KINDS, "unknown task kind")
        digest = row["source_digest"]
        check(
            isinstance(digest, str) and HEX64.fullmatch(digest),
            "source byte digest missing",
        )
        source_at = utc(row["source_at"])
        exposed = utc(row["exposed_at"])
        check(
            source_at <= frozen < exposed if part == "test" else source_at <= frozen,
            "source chronology/source exposure failure",
        )
        check(
            registered <= source_at or part != "test",
            "test source predates preregistered capture",
        )
        check(
            family not in families or families[family] == part,
            "source family crosses train/select/test boundary",
        )
        check(
            digest not in blobs or blobs[digest] == part,
            "identical source bytes cross partition boundary",
        )
        ids.add(identity)
        families[family] = part
        blobs[digest] = part
        if part == "test":
            kinds.add(row["kind"])
        partition_counts[part] += 1
    check(all(partition_counts.values()), "missing train/select/test partition")
    check(kinds == KINDS, "four untouched test task strata required")
    check(
        len({f for f, p in families.items() if p == "test"}) >= 4,
        "four distinct test family roots required",
    )
    check(
        isinstance(manifest.get("policy_snapshot_sha256"), str)
        and HEX64.fullmatch(manifest["policy_snapshot_sha256"]),
        "policy snapshot missing",
    )
    check(
        isinstance(manifest.get("knowledge_snapshot_sha256"), str)
        and HEX64.fullmatch(manifest["knowledge_snapshot_sha256"]),
        "knowledge snapshot missing",
    )
    return {
        "schema": "hepta.memory.prospective-source-cut-audit.v1",
        "sources": len(source),
        "distinct_family_roots_not_independently_authenticated": len(families),
        "partition_source_counts": partition_counts,
        "four_test_strata_registered": True,
        "source_lineage_independently_authenticated": False,
        "timestamp_authority_authenticated": False,
        "independent_semantic_review": False,
        "model_training_admitted": False,
        "production_accepted": False,
    }
