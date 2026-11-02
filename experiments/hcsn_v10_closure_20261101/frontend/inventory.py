"""Inspect recovered archives and build an explicitly partial recording ledger."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile

import numpy as np


def digest(data):
    return hashlib.sha256(data).hexdigest()


def inspect(archive, remote_tree, repository):
    expected_hash = "b9bc77d41716de8e2babec5899f3e2c80f2ebacc9ced6553ce6d7ccd2a764518"
    archive_hash = digest(archive.read_bytes())
    if archive_hash != expected_hash:
        raise ValueError("Recovered Library package bytes differ")
    prefix = "experiments/hcsn_v9_followup_20261101/"
    tree_record = json.loads(remote_tree.read_text())
    tree = tree_record["tree"]
    if tree["truncated"]:
        raise ValueError("Remote identity tree truncated")
    remote = {row["path"]: row for row in tree["tree"] if row["type"] == "blob"}
    checked = []
    with zipfile.ZipFile(archive) as z:
        seen = set()
        for info in z.infolist():
            name = PurePosixPath(info.filename)
            if (name.is_absolute() or ".." in name.parts or info.filename in seen or
                    stat.S_ISLNK(info.external_attr >> 16)):
                raise ValueError("Unsafe or ambiguous ZIP member")
            seen.add(info.filename)
            z.read(info)  # verifies compressed member CRC as well
        manifest = json.loads(z.read(prefix + "BUNDLE_MANIFEST.json"))
        for row in manifest["files"]:
            data = z.read(prefix + row["path"])
            if len(data) != row["size_bytes"] or digest(data) != row["sha256"]:
                raise ValueError("Package manifest mismatch")
        for name in sorted(n for n in seen if n.startswith(prefix)):
            data = z.read(name)
            relative = name[len(prefix):]
            blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            if (relative not in remote or blob != remote[relative]["sha"] or
                    len(data) != remote[relative]["size"]):
                raise ValueError("Package differs from fixed remote v9 tree")
            checked.append(relative)
        if set(checked) != set(remote):
            raise ValueError("Package omits remote v9 files")
        npz_inventory = {}
        for task in ("async_av", "av_binding"):
            with z.open(prefix + "persistent_av/results002/" + task + "/training.npz") as stream:
                with np.load(stream, allow_pickle=False) as values:
                    npz_inventory[task] = {k: {"shape": list(values[k].shape), "dtype": str(values[k].dtype)} for k in values.files}
        bundle = z.read("HCSN_V9_commits.bundle")
        bundle_header = bundle[:bundle.index(b"\n\n")].decode().splitlines()
        package = {"schema": "hcsn-v10-recovered-package-inventory.v1",
                   "library_file_id": "libfile_7b0ea4bcecd88191ac9ee31765d67012",
                   "filename": archive.name, "bytes": archive.stat().st_size, "sha256": archive_hash,
                   "zip_members_crc_verified": len(seen), "manifest_files_verified": len(manifest["files"]),
                   "remote_commit": tree_record["commit"], "remote_v9_tree": tree["sha"],
                   "remote_v9_blobs_exactly_matched": len(checked),
                   "local_incremental_bundle_header": bundle_header,
                   "training_npz": npz_inventory,
                   "raw_media_members": [n for n in seen if PurePosixPath(n).suffix.lower() in {".wav", ".mp4", ".flv", ".avi"}],
                   "v6_source_or_strong_audio_recovered": False, "new_independent_recordings_recovered": False,
                   "interpretation": "Persistent AV ordinary weights/features and old execution evidence; neither new capture nor v6 frontend. Raw media and capture-completeness evidence absent."}
    recovered = repository / "recovered/v3"
    manifest_path = recovered / "experiments/hcsn_task_value_v1/data/async_manifest.json"
    source_manifest = json.loads(manifest_path.read_text())
    base = recovered / "experiments/hcsn_task_value_v1/results/async_frontend001"
    decode = {row["clip"]: row for row in map(json.loads, (base / "decode.jsonl").read_text().splitlines())}
    records = []
    for source in source_manifest["records"]:
        record = decode[source["clip"]]
        feature = base / "clip_features" / (source["clip"] + ".npz")
        if record["source_sha256"] != source["sha256"] or digest(feature.read_bytes()) != record["feature_sha256"]:
            raise ValueError("Historical recording/decode/feature lineage differs")
        records.append({"recording_id": source["clip"], "actor_id": source["actor"],
                        "old_split": source["split"], "sentence": source["sentence"],
                        "emotion": source["emotion"], "original_media_sha256_from_manifest": source["sha256"],
                        "original_media_bytes_from_manifest": source["bytes"],
                        "original_media_bytes_rehashed_this_run": False,
                        "feature_file_sha256_rehashed_this_run": record["feature_sha256"],
                        "known_prior_uses": ["v3 historical preparation/selection", "v8 replay", "v9 historical control study"]})
    ledger = {"schema": "hcsn-v10-partial-historical-recording-exclusions.v1",
              "scope": "Known 48-recording v3 cohort reused by v8 and recovered v9; NOT comprehensive v5/v6/all-project exclusions",
              "complete": False, "v5_v6_usage_known": None,
              "source_manifest_sha256": digest(manifest_path.read_bytes()),
              "records": records, "recordings": len(records), "actors": len({r["actor_id"] for r in records}),
              "new_confirmation_allowed_by_this_ledger": False}
    return package, ledger


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--remote-tree", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    package, ledger = inspect(args.archive, args.remote_tree, args.repository)
    for name, value in (("RECOVERED_PACKAGE.json", package), ("HISTORICAL_EXCLUSIONS_PARTIAL.json", ledger)):
        with (args.output / name).open("x") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
    print(json.dumps({"package": package, "partial_exclusion_recordings": ledger["recordings"]}, indent=2))
