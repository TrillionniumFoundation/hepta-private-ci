"""Audit the union of closed joint output parts and the final remainder.

Recheck compressed identities and manifests, relying on the sealer's complete
member-byte verification. Do not hash live model/media files or decompress them.
"""

import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import time


PROTOCOL_SHA = "b118cdf44764408f9ee1906545159092093a2a48023343a3851f73970dac17fb"
AUDIT_SHA = "966b6c762fe28975ba1b1cffe7d99a035d593423c1fc20038c7629be1078a9bf"
MEDIA = ("caption.txt", "image.png", "audio.wav", "video.mp4")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def volume(receipt_path, role):
    receipt = read(receipt_path)
    require(receipt["status"] == "passed" and receipt["all_member_bytes_rehashed_after_archive_close"],
            "A volume lacks successful complete sealer verification")
    archive, manifest_path = Path(receipt["archive"]), Path(receipt["member_manifest"])
    require(archive.stat().st_size == receipt["archive_bytes"] and sha(archive) == receipt["archive_sha256"],
            "Compressed archive identity changed: " + str(archive))
    manifest_bytes = manifest_path.read_bytes()
    require(hashlib.sha256(manifest_bytes).hexdigest() == receipt["manifest_sha256"], "External manifest changed")
    with tarfile.open(archive, "r|gz") as packed:
        first = packed.next()
        require(first is not None and first.name == "MANIFEST.json" and first.isfile(), "Manifest must be first")
        require(packed.extractfile(first).read() == manifest_bytes, "Internal and external manifests differ")
    manifest = json.loads(manifest_bytes)
    expanded_path = Path(receipt["expanded_inputs"])
    require(sha(expanded_path) == manifest["input_spec_sha256"], "Expanded source mapping identity changed")
    expanded = read(expanded_path)
    require(expanded["definition_sha256"] == receipt["definition_sha256"], "Definition identity differs")
    entries = manifest["files"]
    inputs = {item["name"]: item for item in expanded["files"]}
    require(len(inputs) == len(expanded["files"]) == len(entries) == receipt["member_count"], "Member count differs")
    require(receipt["verified_members_including_manifest"] == len(entries) + 1, "Verified count differs")
    mapping, members = {}, set()
    for item in entries:
        source, member = item["original_path"], item["member"]
        require(Path(source).is_absolute() and ".." not in Path(source).parts, "Noncanonical source path")
        require(str(Path(source)) == source and source not in mapping and member not in members,
                "Duplicate or noncanonical original/member path within a volume")
        require(member in inputs and inputs[member]["path"] == source
                and inputs[member]["sha256"] == item["sha256"], "Manifest and source mapping differ")
        require(isinstance(item["bytes"], int) and item["bytes"] >= 0, "Invalid member size")
        mapping[source] = (item["sha256"], item["bytes"])
        members.add(member)
    identity = {key: receipt[key] for key in ("archive", "archive_bytes", "archive_sha256", "manifest_sha256")}
    identity.update(role=role, receipt=str(receipt_path), receipt_sha256=sha(receipt_path),
                    manifest=str(manifest_path), expanded_inputs_sha256=manifest["input_spec_sha256"], members=len(entries))
    return identity, mapping


def audit(remainder, parts, output):
    phase = Path(__file__).resolve().parent
    raw = Path("/tmp/hepta-ndu-advance-joint")
    run = raw / "confirmation-001"
    protocol_path, audit_path = phase / "joint/CONFIRMATION_PROTOCOL.json", run / "COMPLETENESS_AUDIT.json"
    require(sha(protocol_path) == PROTOCOL_SHA and sha(audit_path) == AUDIT_SHA, "Frozen protocol/audit changed")
    spec, closed, checked = read(protocol_path), read(audit_path), read(run / "CHECKED_RESULT.json")
    require(closed["passed"] and checked["audit_passed"] and checked["audit_sha256"] == AUDIT_SHA,
            "The complete study was not successfully audited")
    require(closed["protocol_sha256"] == PROTOCOL_SHA and closed["rows_sha256"] == sha(run / "ROWS.json")
            and checked["results_sha256"] == sha(run / "RESULTS.json"), "Closed study identities differ")
    require(read(raw / "confirmation-001-process/receipt.json")["returncode"] == 0, "Collector did not complete")
    require(parts and spec["pair_count"] == 170 and len(spec["routes"]) == 4 and len(spec["arms"]) == 8,
            "Expected the registered full study and at least one output part")
    require(not output.exists() and not output.resolve().is_relative_to(raw)
            and not output.resolve().is_relative_to(phase / "joint"), "Never overwrite or modify frozen study trees")
    merged, owners, identities, archives = {}, {}, [], set()
    for receipt, role in [(path, "output_part") for path in parts] + [(remainder, "final_remainder")]:
        identity, mapping = volume(receipt, role)
        require(identity["archive"] not in archives, "The same archive was supplied twice")
        archives.add(identity["archive"])
        identities.append(identity)
        for path, value in mapping.items():
            require(path not in merged or merged[path] == value, "Cross-volume identity conflict: " + path)
            merged[path] = value
            owners.setdefault(path, []).append(identity["archive"])
    bundles = {run / "raw" / f"case-{case:03d}" / route / arm["name"]
               for case in range(spec["pair_count"]) for route in spec["routes"] for arm in spec["arms"]}
    outputs = {str(bundle / "output" / name) for bundle in bundles for name in MEDIA}
    records = {str(bundle / "RECORD.json") for bundle in bundles}
    videos = {str(run / "input" / f"case-{case:03d}" / "video/video/input.mp4")
              for case in range(spec["pair_count"])}
    actual_outputs = {p for p in merged if Path(p).is_relative_to(run / "raw") and Path(p).parent.name == "output"}
    actual_records = {p for p in merged if Path(p).is_relative_to(run / "raw") and Path(p).name == "RECORD.json"}
    actual_videos = {p for p in merged if Path(p).is_relative_to(run / "input") and Path(p).name == "input.mp4"}
    require(outputs == actual_outputs and len(outputs) == closed["actual_output_files_checked"] == 21760,
            "Output union differs from the complete registered Cartesian census")
    require(all(len(owners[path]) == 1 for path in outputs), "An actual output occurs in more than one volume")
    require(records == actual_records and len(records) == closed["complete_registered_cases"] == 5440,
            "The complete RECORD census is not covered")
    require(videos == actual_videos and len(videos) == closed["actual_input_videos_checked"] == 170,
            "The complete physical input-video census is not covered")
    for path in (protocol_path, audit_path, run / "CHECKED_RESULT.json", run / "RESULTS.json", run / "ROWS.json"):
        require(merged.get(str(path)) == (sha(path), path.stat().st_size), "Closed identity absent from union")
    model_paths, model_counts = {}, {}
    for study in ("training-001", "nll-repair-001"):
        path = raw / study / "RESULTS.json"
        require(sha(path) == spec["frozen_candidate_sha256"][str(path)], "Training result changed")
        arms = read(path)["arms"]
        model_counts[study] = len(arms)
        for arm in arms.values():
            for key in ("checkpoint", "native_export"):
                source = arm[key]
                require(source not in model_paths and source in merged, "Missing or duplicate training artifact")
                require(merged[source][0] == arm[key + "_sha256"]
                        == spec["frozen_candidate_sha256"][source], "Training artifact identity differs")
                model_paths[source] = key
    require(model_counts == {"training-001": 6, "nll-repair-001": 6}, "Training candidate census differs")
    live_count, live_bytes = 0, 0
    for path in raw.rglob("*"):
        require(not path.is_symlink(), "Symlink in frozen raw tree")
        if path.is_file():
            require(str(path) in merged and path.stat().st_size == merged[str(path)][1],
                    "Current frozen raw file absent or wrong size: " + str(path))
            live_count += 1
            live_bytes += path.stat().st_size
    require(live_count > 0, "Frozen raw tree is empty")
    union_digest = hashlib.sha256(json.dumps(sorted(merged.items()), separators=(",", ":")).encode()).hexdigest()
    result = {"schema": "hepta.advance.joint-multipart-custody-coverage.v1", "passed": True,
              "recorded_unix_ns": time.time_ns(), "protocol_sha256": PROTOCOL_SHA, "closed_audit_sha256": AUDIT_SHA,
              "results_sha256": checked["results_sha256"], "scientific_primary_passed": checked["passed"],
              "archives": identities, "union_original_paths": len(merged), "union_path_identity_sha256": union_digest,
              "actual_output_paths": len(outputs), "each_output_in_exactly_one_volume": True,
              "record_paths": len(records), "input_video_paths": len(videos), "training_arms": model_counts,
              "training_checkpoints": sum(k == "checkpoint" for k in model_paths.values()),
              "training_exports": sum(k == "native_export" for k in model_paths.values()),
              "current_raw_files_covered": live_count, "current_raw_bytes_covered": live_bytes,
              "identical_cross_volume_paths": sum(len(v) > 1 for v in owners.values()),
              "scope": "All listed output parts plus final remainder jointly constitute the complete joint study; no single volume does.",
              "byte_verification": "Compressed SHA and exact first-member manifest rechecked; all member bytes were previously verified by each sealer.",
              "live_raw_verification": "Complete current path and size census; model/media content not rehashed. Frozen-tree assumption retained.",
              "external_inputs": "Original external sources/runtime assets remain subject to the remainder's explicitly linked archives and scope.",
              "no_raw_or_model_mutation": True, "upload_performed": False}
    with output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"coverage": str(output), "sha256": sha(output), "passed": True,
                      "archives": len(identities), "actual_outputs": len(outputs), "current_raw_files": live_count}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remainder", type=Path, required=True)
    parser.add_argument("--parts", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    audit(**vars(parser.parse_args()))
