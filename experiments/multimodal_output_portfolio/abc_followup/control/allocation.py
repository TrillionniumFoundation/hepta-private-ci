"""Audit image identities without materializing prospective source outcomes."""

import hashlib
import json
from pathlib import Path
import re

from ...abc_next.settings import MANIFEST, MANIFEST_SHA, REPO, WORKSPACE
from ...abc_recovery.base_recovery import file_sha, write_json


RANGES = {
    "historical_main_test": (0, 512),
    "control_and_generator_final": (512, 768),
    "native_new_calibration": (768, 1568),
    "native_new_verification": (1568, 3000),
}


def identities(manifest, start, end):
    return manifest["roles"]["test"]["source_ids"][2 * start:2 * end]


def identity_digest(values):
    return hashlib.sha256("\n".join(values).encode()).hexdigest()


def audit():
    if file_sha(MANIFEST) != MANIFEST_SHA:
        raise ValueError("Historical source manifest changed")
    manifest = json.loads(MANIFEST.read_text())
    if len(manifest["roles"]["test"]["source_ids"]) != 6000:
        raise ValueError("Unexpected registered test capacity")
    evidence = []
    names = {"registration.json", "protocol.json", "PROTOCOL.json", "result.json",
             "access-registration.json", "summary.json", "freeze.json"}

    def walk(value, at=""):
        if isinstance(value, dict):
            role = value.get("role", value.get("source_role"))
            if role in {"test", "unallocated_test", "unallocated_train"}:
                yield {"at": at, "role": role,
                       "start": value.get("pair_start", value.get("start", value.get("source_pair_start"))),
                       "count": value.get("pair_count", value.get("count"))}
            for key, child in value.items():
                if key not in {"source_ids", "output_sha256", "source_sha256"}:
                    yield from walk(child, at + "/" + key)
        elif isinstance(value, list) and len(value) < 100:
            for index, child in enumerate(value):
                yield from walk(child, at + "/" + str(index))

    inspected, large_inspected, all_bound_ids = 0, [], set()
    prospective = set(identities(manifest, 512, 3000))

    def bound_ids(value):
        if isinstance(value, str) and re.fullmatch(r"mnist:(train|test):[0-9]+:[0-9a-f]{64}", value):
            yield value
        elif isinstance(value, dict):
            for child in value.values():
                yield from bound_ids(child)
        elif isinstance(value, list):
            for child in value:
                yield from bound_ids(child)

    for directory in ("abc2-runs", "abc3-runs", "abc3-native-runs"):
        root = WORKSPACE / directory
        for path in sorted(root.rglob("*.json")):
            if path.name not in names or any(part in {"target", "cargo-home", "media"} for part in path.parts):
                continue
            value = json.loads(path.read_text())
            inspected += 1
            matches = list(walk(value))
            used_ids = set(bound_ids(value))
            all_bound_ids.update(used_ids)
            if used_ids & prospective:
                raise ValueError("Historical metadata binds a prospective original image")
            if path.stat().st_size > 200000:
                large_inspected.append({"file": str(path.relative_to(WORKSPACE)), "sha256": file_sha(path),
                    "bytes": path.stat().st_size, "distinct_bound_source_ids": len(used_ids),
                    "ordered_bound_ids_sha256": identity_digest(sorted(used_ids)),
                    "prospective_individual_id_overlap": 0,
                    "declared_source_roles_read": value.get("source_roles_read"),
                    "test_or_unallocated_ranges": matches})
            if matches:
                evidence.append({"file": str(path.relative_to(WORKSPACE)), "sha256": file_sha(path),
                                 "declared_or_executed_ranges": matches})
                for item in matches:
                    if item["role"] != "test" or not isinstance(item["start"], int) or not isinstance(item["count"], int):
                        raise ValueError("Unrecognized historical source access requires explicit review")
                    if item["start"] < 0 or item["start"] + item["count"] > 512:
                        raise ValueError("Historical test access crosses the reserved boundary")
    groups = {name: identities(manifest, start, end) for name, (start, end) in RANGES.items()}
    others = [identity for role, record in manifest["roles"].items() if role != "test"
              for identity in record["source_ids"]]
    groups["all_non_test_manifest_roles"] = others
    comparisons = []
    for index, (left, left_ids) in enumerate(groups.items()):
        for right, right_ids in list(groups.items())[index + 1:]:
            overlap = set(left_ids) & set(right_ids)
            pixel_overlap = {v.rsplit(":", 1)[1] for v in left_ids} & {v.rsplit(":", 1)[1] for v in right_ids}
            if overlap or pixel_overlap:
                raise ValueError("Individual original images or pixel identities overlap")
            comparisons.append({"left": left, "right": right, "individual_id_overlap": 0, "pixel_hash_overlap": 0})
    return {"schema": "hepta.abc-followup.source-allocation.v1", "manifest_sha256": MANIFEST_SHA,
            "baseline_remote_commit": "39faddd747e87c31d01301d353526623eae0da83",
            "metadata_only_no_prospective_outcomes_materialized": True,
            "metadata_files_inspected": inspected, "large_metadata_excluded_from_recursive_scan": [],
            "large_metadata_explicitly_inspected": large_inspected,
            "all_metadata_bound_distinct_ids": len(all_bound_ids),
            "all_metadata_bound_ids_sha256": identity_digest(sorted(all_bound_ids)),
            "all_metadata_vs_prospective_individual_id_overlap": 0,
            "historical_access_evidence": evidence,
            "scope": "Frozen repository experiment code, role manifest and available local execution metadata; does not attest unknown external experiments. Role declarations are conservatively included as used.",
            "groups": {name: {"pair_start": RANGES[name][0], "pair_end_exclusive": RANGES[name][1],
                               "source_pairs": len(values) // 2, "individual_sources": len(values),
                               "ordered_source_ids_sha256": identity_digest(values),
                               "sorted_pixel_hashes_sha256": identity_digest(sorted(v.rsplit(":", 1)[1] for v in values))}
                       for name, values in groups.items() if name in RANGES},
            "non_test_roles_ordered_ids_sha256": identity_digest(others), "disjointness": comparisons,
            "source_units": "No-replacement adjacent original image pairs; views/scenarios/policies/seeds retain source clustering. Unknown original writer clusters are not invented.",
            "shared_control_training_final": "Both experiments use exactly the control_and_generator_final identities, with separately frozen candidates; they do not create independent extra N.",
            "new_native_ranges_are_reservations_not_already_executed": True}


if __name__ == "__main__":
    output = Path(__file__).with_name("SOURCE_ALLOCATION.json")
    write_json(output, audit())
    print(json.dumps({"path": str(output.relative_to(REPO)), "sha256": file_sha(output)}))
