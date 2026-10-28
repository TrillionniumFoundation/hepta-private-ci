"""Reserve genuinely new original videos for the fixed bounded host policy.

This cohort is separate from all natural-study train/calibration/qualification
roles. It is not the new high-resolution semantic-generation qualification.
"""

import argparse
import json
from pathlib import Path
import time
import zipfile

import numpy as np

from ..continuation_20261027.control.client import sha
from ..unified_20261028.natural_data import (URL, RemoteZip, annotations, canonical,
                                           eligible_events, ffmpeg)
from ..unified_20261028.profile import digest
from .control_study import save


SEED, COUNT = "hepta-new-host-tail-sources-20261028-v1", 16


def freeze(root, parent, prior, reserved):
    root.mkdir(parents=True, exist_ok=False)
    excluded, pins = set(), {}
    for path in (prior / "natural_assets/EVENTS.json", prior / "natural_expanded_assets/EVENTS.json"):
        document = json.loads(path.read_text())
        excluded.update(row["source_id"] for row in document["events"])
        pins[str(path)] = sha(path)
    reservation = json.loads(reserved.read_text())
    excluded.update(row["source_id"] for row in reservation["selected"])
    pins[str(reserved)] = sha(reserved)
    parent_result = json.loads((parent / "SUMMARY.json").read_text())
    actor = json.loads((parent / "ACTOR.json").read_text())
    if digest(actor) != parent_result["actor_sha256"]:
        raise ValueError("Freeze source calibration only after the actual deployed actor is fixed")
    ann, annotation_receipts = annotations(root)
    remote = RemoteZip(URL)
    archive = zipfile.ZipFile(remote)
    candidates = []
    for member in archive.infolist():
        source = Path(member.filename).stem
        if (not member.filename.endswith(".mp4") or member.file_size > 5_000_000
                or source in excluded or source not in ann["action"] or source not in ann["sound"]):
            continue
        events = eligible_events(ann["action"][source], ann["sound"][source])
        if len(events) < 2:
            continue
        event = events[0]
        start = round(event["start_seconds"] * 8) / 8
        overlaps = [max(0.0, min(a["timestamps"][1] / 1e6, s["timestamps"][1] / 1e6, start + .75)
                        - max(a["timestamps"][0] / 1e6, s["timestamps"][0] / 1e6, start + .25))
                    for a in ann["action"][source]["action_localisation"] if a["label_id"] == event["action_id"]
                    for s in ann["sound"][source]["sound_localisation"] if s["label_id"] == event["sound_id"] and s.get("is_visible")]
        if max(overlaps, default=0.0) < .15:
            continue
        candidates.append({"source_id": source, "member": member.filename,
                           "bytes": member.file_size, "compressed_bytes": member.compress_size,
                           "zip_crc32": f"{member.CRC:08x}", "event": event,
                           "target_annotated_overlap_seconds": max(overlaps),
                           "priority": digest([SEED, source])})
    selected = sorted(candidates, key=lambda row: row["priority"])[:COUNT]
    if len(selected) != COUNT:
        raise ValueError("Insufficient independently reserved eligible original sources")
    plan = {"schema": "hepta.ndu.additional-host-calibration-sources.v1", "seed": SEED,
            "selected": selected, "excluded_source_ids": sorted(excluded), "excluded_manifest_sha256": pins,
            "profile_sha256": parent_result["profile_sha256"], "policy_sha256": parent_result["actor_sha256"],
            "parent_study_summary_sha256": sha(parent / "SUMMARY.json"), "annotation_receipts": annotation_receipts,
            "archive": {"url": URL, "generation": remote.generation, "etag": remote.etag, "length": remote.length},
            "vocabulary": json.loads((prior / "natural_assets/SOURCE_PROTOCOL.json").read_text())["vocabulary"],
            "source_unit": "one original video, one fixed annotated event, one complete policy episode",
            "selection": "SHA order among new <=5MB official train videos with >=2 existing bounded-task eligible events and >=0.15s label overlap within actual target",
            "task_scope": "historical 32px, 0.5-second visible-overlap reconstruction task; inherited excluded sound classes 12/13/16; not new full-class natural qualification",
            "scenario": {"declared_fault": False, "expires": 7, "media_budget": 2},
            "future_risk_population": "same declared source filter and normal transport regime; no injected-fault-mixture extrapolation",
            "return_threshold": 0.0, "alpha": .05, "family_size": 1,
            "emission_seed_base": 2826100400,
            "execution_source_sha256": sha(Path(__file__).with_name("control_calibration_run.py")),
            "tail_source_sha256": sha(Path(__file__).with_name("tail_calibration.py")),
            "qualification": False, "fresh_source_calibration": True,
            "selection_source_sha256": sha(Path(__file__)), "created_at_unix": time.time(),
            "participant_independence_proven": False,
            "no_metric_selection": "all sixteen frozen source episodes must be retained, including failures and high cost"}
    plan["protocol_sha256"] = digest(plan)
    save(root / "SOURCE_PROTOCOL.json", plan)
    return plan


def prepare(root):
    plan = json.loads((root / "SOURCE_PROTOCOL.json").read_text())
    unsigned = {key: value for key, value in plan.items() if key != "protocol_sha256"}
    if digest(unsigned) != plan["protocol_sha256"] or sha(Path(__file__)) != plan["selection_source_sha256"]:
        raise ValueError("Frozen source/decode implementation changed")
    remote = RemoteZip(URL)
    if remote.generation != plan["archive"]["generation"] or remote.etag != plan["archive"]["etag"]:
        raise ValueError("Official source archive version changed after selection")
    archive = zipfile.ZipFile(remote)
    decoded, rows, sources = [], [], []
    for index, row in enumerate(plan["selected"]):
        payload = archive.read(row["member"])
        if len(payload) != row["bytes"]:
            raise ValueError("Frozen source byte length changed")
        path = root / (row["source_id"] + ".mp4")
        with path.open("xb") as stream:
            stream.write(payload)
        source_hash = sha(path)
        frames = np.frombuffer(ffmpeg(["-i", str(path), "-vf", "fps=8,scale=32:32:flags=area",
                                       "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]), np.uint8).reshape(-1, 32, 32, 3)
        audio = np.frombuffer(ffmpeg(["-i", str(path), "-vn", "-ac", "1", "-ar", "8000",
                                     "-f", "f32le", "pipe:1"]), "<f4")
        event = row["event"]
        first = int(round(event["start_seconds"] * 8))
        video = frames[first:first + 8]
        waveform = audio[first * 1000:first * 1000 + 8000]
        if video.shape != (8, 32, 32, 3) or waveform.shape != (8000,):
            raise ValueError("Selected source has an incomplete synchronized window; no replacement allowed")
        lookup = {token: i for i, token in enumerate(plan["vocabulary"])}
        tokens = np.zeros(16, dtype=np.int64)
        for j, token in enumerate(event["caption"].replace(";", " ; ").split()[:16]):
            tokens[j] = lookup.get(token, 1)
        decoded.append((video[[0, 1, 6, 7]], waveform[np.r_[0:2000, 6000:8000]], video[2:6], waveform[2000:6000], video[4], tokens))
        rows.append({"event_id": row["source_id"] + "-host-tail-event-0", "source_id": row["source_id"],
                     "split": "calibration", "source_sha256": source_hash, "actual_start_seconds": first / 8, **event})
        sources.append({"source_id": row["source_id"], "member": row["member"], "sha256": source_hash,
                        "bytes": len(payload), "zip_crc32": row["zip_crc32"]})
        path.unlink()  # Only the exact downloaded member owned by this script.
        print(json.dumps({"prepared": index + 1, "source_id": row["source_id"]}), flush=True)
    names = ("context_video", "context_audio", "target_video", "target_audio", "target_image", "target_text")
    np.savez_compressed(root / "EVENTS.npz", **{name: np.stack([row[i] for row in decoded]) for i, name in enumerate(names)})
    save(root / "EVENTS.json", {"source_protocol_sha256": plan["protocol_sha256"], "events": rows,
                               "arrays_sha256": sha(root / "EVENTS.npz"), "sources": sources,
                               "range_receipts": remote.receipts})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--parent-run", type=Path)
    parser.add_argument("--prior-root", type=Path)
    parser.add_argument("--reserved-source-plan", type=Path)
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        prepare(args.assets)
    else:
        plan = freeze(args.assets, args.parent_run, args.prior_root, args.reserved_source_plan)
        print(json.dumps({"source_protocol_sha256": plan["protocol_sha256"], "selected_ids": [row["source_id"] for row in plan["selected"]]}))
