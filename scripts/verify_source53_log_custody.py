"""Verify frozen source53 logs through their unchanged original manifests."""

import json
from pathlib import Path
import sys

from verify_frozen_gzip import read_original
from verify_source_custody_container import identity, require

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "qa/repository-consolidation/20261115"))
from restore_raw_evidence import EXTENSION_INDEX, entries, read_regular, read_verified

COLLECTION = (
    "qualification/evaluated-current-read-20261112/source53-cross-platform-readback"
)


def verify(repository):
    require(not sys.flags.optimize, "optimized verification refused")
    inventory = entries(repository)
    transport = json.loads(read_regular(repository, EXTENSION_INDEX, 1024 * 1024))
    require(
        transport["collection"] == COLLECTION
        and transport["source_executed"] is False
        and transport["scientific_or_runtime_qualification"] is False,
        "historical evidence boundary changed",
    )
    for entry in transport["prior_controls"]:
        read_original(repository, entry)
    snapshots, unique_parts = [], {}
    for original in transport["original_manifests"]:
        raw = read_regular(repository, original["path"], original["bytes"])
        require(
            identity(raw) == {key: original[key] for key in ("bytes", "sha256", "oid")},
            "original log manifest drift",
        )
        manifest = json.loads(raw)
        expected_schema = (
            "hepta.original-ci-log-archive.v1"
            if original["path"].endswith("/MANIFEST_FINAL.json")
            else "hepta.ci-readback-manifest.v1"
        )
        require(
            manifest["schema"] == expected_schema
            and manifest["source_head"] == "53b3227a8dff5af9e39ecef6356cfce702d80b1c",
            "original log source identity changed",
        )
        seen_jobs, total_bytes, part_count = set(), 0, 0
        for log in manifest["logs"]:
            require(log["job_id"] not in seen_jobs, "duplicate original job")
            seen_jobs.add(log["job_id"])
            chunks, offset = [], 0
            for part in log["parts"]:
                name = COLLECTION + "/" + part["path"]
                require(name in inventory, "missing original part carrier")
                data = read_verified(repository, name, part["bytes"], part["sha256"])
                require(
                    identity(data)["oid"] == part["git_blob"]
                    and part["offset"] == offset,
                    "original part Git identity or offset mismatch",
                )
                if name in unique_parts:
                    require(
                        unique_parts[name] == identity(data),
                        "inconsistent original part",
                    )
                unique_parts[name] = identity(data)
                chunks.append(data)
                offset += len(data)
                part_count += 1
            combined = b"".join(chunks)
            require(
                identity(combined)
                == {
                    "bytes": log["whole_bytes"],
                    "sha256": log["whole_sha256"],
                    "oid": log["whole_git_blob"],
                },
                "complete original log identity mismatch",
            )
            total_bytes += len(combined)
        require(
            (len(seen_jobs), part_count, total_bytes)
            == (
                manifest["original_log_count"],
                manifest["original_parts"],
                manifest["original_bytes"],
            ),
            "original manifest totals mismatch",
        )
        snapshots.append(
            {
                "manifest": original["path"],
                "jobs": len(seen_jobs),
                "parts": part_count,
                "bytes": total_bytes,
            }
        )
    require(
        set(unique_parts)
        == {name for name in inventory if name.startswith(COLLECTION + "/")},
        "unreferenced source53 carrier",
    )
    return {
        "snapshots": snapshots,
        "unique_original_parts": len(unique_parts),
        "unique_original_bytes": sum(row["bytes"] for row in unique_parts.values()),
        "original_manifests_unchanged": True,
        "historical_logs_replayed": False,
        "scientific_or_runtime_qualification": False,
    }


if __name__ == "__main__":
    print(json.dumps(verify(REPOSITORY), indent=2))
