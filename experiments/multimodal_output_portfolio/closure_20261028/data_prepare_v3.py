"""Stream the approved expanded cohorts with unchanged decoding and holdout gates."""
import argparse
import json
from pathlib import Path
import time
import zipfile

import numpy as np
import torch

from ..unified_20261028.natural_data import RemoteZip
from .data_prepare import decode
from .data_prepare_v2 import TRAIN_ROLES, validate_freeze, window
from .data_sources import digest, save
from .data_v3_contract import feature_contract, load_plan, validate_receipt
from .semantic_backbones import SemanticBackbones
from .semantic_tsm import TsmObserver


def prepare(root, roles, freeze_path):
    plan = load_plan(root)
    if not set(roles).issubset(plan["roles"]):
        raise ValueError("Unknown frozen source role")
    freeze_sha = validate_freeze(plan, roles, freeze_path)
    contract, _ = feature_contract(root, plan)
    torch.set_num_threads(2)
    models = tsm = None
    original_hashes = {}
    for path in (root / "prepared").glob("*/*/RECEIPT.json"):
        receipt = json.loads(path.read_text())
        pin, sid = receipt["original_source_sha256"], receipt["source_id"]
        if pin in original_hashes and original_hashes[pin] != sid:
            raise ValueError("Different allocated IDs contain identical original source bytes")
        original_hashes[pin] = sid
    remotes, archives = {}, {}
    started, done, fresh = time.monotonic(), 0, 0
    selected = [row for row in plan["selected"] if row["role"] in roles]
    for source in selected:
        role, sid = source["role"], source["source_id"]
        destination = root / "prepared" / role / sid
        receipt_path = destination / "RECEIPT.json"
        if receipt_path.exists():
            validate_receipt(root, plan, source, json.loads(receipt_path.read_text()))
            done += 1
            continue
        destination.mkdir(parents=True, exist_ok=True)
        split = source["official_split"]
        if split not in archives:
            remote = RemoteZip(plan["archive"][split]["url"])
            identity = plan["archive"][split]
            if (remote.generation != identity["generation"] or remote.etag != identity["etag"]
                    or remote.length != identity["length"]):
                raise ValueError("Official archive object identity changed")
            remotes[split], archives[split] = remote, zipfile.ZipFile(remote)
        payload = archives[split].read(source["member"])
        if len(payload) != source["source_bytes"]:
            raise ValueError("Original member length changed")
        source_sha = digest(payload)
        if source_sha in original_hashes and original_hashes[source_sha] != sid:
            save(root / f"SOURCE_DUPLICATE_FAILURE_{sid}.json", {
                "source_id": sid, "same_bytes_as": original_hashes[source_sha],
                "original_source_sha256": source_sha, "allocation_changed": False})
            raise ValueError("New source duplicates an allocated original video; protocol fails closed")
        raw = root / ("pending-" + sid + ".mp4")
        raw.write_bytes(payload)
        del payload
        try:
            frames, audio = decode(raw)
            clips = [(*window(frames, audio, event), event)
                     for event in source["events"][:source["retained_event_count"]]]
            features = {key: [] for key in ("video", "video_tsm", "audio")}
            cpu = 0.
            retained_names = []
            if role != "generator_train":
                if models is None:
                    models, tsm = SemanticBackbones(root / "pretrained"), TsmObserver(root / "pretrained")
                for offset in range(0, len(clips), 2):
                    group = clips[offset:offset + 2]
                    videos = np.stack([item[0][8:24] for item in group])
                    waves = np.stack([item[1][16000:48000] for item in group])
                    start = time.process_time()
                    v, a, _ = models.features(videos, waves)
                    tv = tsm.features(videos)
                    cpu += time.process_time() - start
                    features["video"].append(v)
                    features["video_tsm"].append(tv)
                    features["audio"].append(a)
                np.savez_compressed(destination / "FEATURES.npz", **{key: np.concatenate(value) for key, value in features.items()})
                retained_names.append("FEATURES.npz")
            if role != "observer_train":
                v, a, vm, am, _ = clips[0]
                indices, audio_indices = np.r_[0:8, 24:32], np.r_[0:16000, 48000:64000]
                np.savez_compressed(destination / "EVENT.npz", context_video=v[indices], context_audio=a[audio_indices],
                    context_video_mask=vm[indices], context_audio_mask=am[audio_indices],
                    target_video=v[8:24], target_audio=a[16000:48000], target_image=v[16])
                retained_names.append("EVENT.npz")
            rows = [{"event_id": f"{sid}-closure-{i}", "source_id": sid, "source_sha256": source_sha,
                     "role": role, **clip[-1]} for i, clip in enumerate(clips)]
            receipt = {"schema": "hepta.closure.prepared-source.v3", "source_protocol_sha256": plan["protocol_sha256"],
                "source_id": sid, "role": role, "original_source_sha256": source_sha,
                "original_source_bytes": source["source_bytes"], "original_url": plan["archive"][split]["url"],
                "original_member": source["member"], "events": rows,
                "retained_files": {name: digest((destination / name).read_bytes()) for name in retained_names},
                "feature_cpu_seconds": cpu, "source_hashes": contract["source_hashes"],
                "feature_protocol_sha256": digest(contract), "heldout_freeze_sha256": freeze_sha}
            validate_receipt(root, plan, source, receipt)
            save(receipt_path, receipt)
            original_hashes[source_sha] = sid
        finally:
            raw.unlink(missing_ok=True)
        done, fresh = done + 1, fresh + 1
        if fresh % 8 == 0 or done == len(selected):
            print(json.dumps({"prepared": done, "total": len(selected), "new_sources": fresh,
                "last_source": sid, "last_role": role, "elapsed_wall_seconds": time.monotonic() - started}), flush=True)
    save(root / ("PREPARATION_" + str(time.time_ns()) + ".json"), {
        "schema": "hepta.closure.preparation-pass.v3", "source_protocol_sha256": plan["protocol_sha256"],
        "roles": roles, "sources_completed": done, "new_sources_prepared": fresh,
        "source_hashes": contract["source_hashes"], "wall_seconds": time.monotonic() - started,
        "range_receipts": {key: value.receipts for key, value in remotes.items()},
        "literal_source_byte_duplicates": [], "qualified_predictions_computed": 0})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--roles", nargs="+", default=list(TRAIN_ROLES))
    parser.add_argument("--holdout-freeze", type=Path)
    args = parser.parse_args()
    prepare(args.assets, args.roles, args.holdout_freeze)
