"""Freeze original-video cohorts before accessing any new held-out media score."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import urllib.request
import zipfile

from ..unified_20261028.natural_data import RemoteZip

BASE = "https://storage.googleapis.com/dm-perception-test/zip_data/"
SEED = "hepta-natural-closure-20261028-source-v1"
ROLES = {"generator_train":128,"observer_train":384,"development":64,
         "observer_calibration":64,"policy_calibration":64,"qualification":64}
SIZE_LIMIT = 12_000_000


def digest(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(value).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def load_annotations(root, split, kind):
    name = (f"{kind}_localisation_train_annotations.zip" if split == "train" else
            f"challenge_{kind}_localisation_valid_annotations.zip")
    path = root / name
    if not path.exists():
        with urllib.request.urlopen(BASE+name, timeout=30) as response:
            payload = response.read(3_000_001)
        if len(payload)>3_000_000:
            raise ValueError("Annotation archive exceeds predeclared bound")
        path.write_bytes(payload)
    with zipfile.ZipFile(path) as archive:
        data = json.loads(archive.read(archive.namelist()[0]))
    return data, {"url":BASE+name, "sha256":digest(path.read_bytes()), "bytes":path.stat().st_size}


def events(action, sound):
    """All labels eligible; visible paired interaction is the frozen task scope."""
    meta = action["metadata"]
    duration = min(meta["num_frames"]/meta["frame_rate"],
                   sound["metadata"]["audio_samples"]/sound["metadata"]["audio_sample_rate"])
    if duration < 4.125:
        return []
    rows = []
    for a in action["action_localisation"]:
        for s in sound["sound_localisation"]:
            begin = max(a["timestamps"][0], s["timestamps"][0])/1e6
            end = min(a["timestamps"][1], s["timestamps"][1])/1e6
            if not s.get("is_visible", False) or end-begin < .15:
                continue
            center = (begin+end)/2
            start = int(max(0, min(center-2, duration-4.125))*8)/8
            row = {"action_id":a["label_id"], "action":a["label"],
                   "sound_id":s["label_id"], "sound":s["label"],
                   "action_annotation_id":a["id"], "sound_annotation_id":s["id"],
                   "action_interval_seconds":[v/1e6 for v in a["timestamps"]],
                   "sound_interval_seconds":[v/1e6 for v in s["timestamps"]],
                   "overlap_seconds":end-begin,"window_start_seconds":start,
                   "target_start_seconds":start+1, "target_end_seconds":start+3}
            row["priority"] = digest([SEED, meta["video_id"], a["id"], s["id"]])
            rows.append(row)
    rows.sort(key=lambda x:x["priority"])
    kept = []
    for row in rows:
        if all(abs(row["window_start_seconds"]-x["window_start_seconds"]) >= 1 for x in kept):
            kept.append(row)
        if len(kept) == 8:
            break
    return kept


def freeze(root, prior):
    root.mkdir(parents=True, exist_ok=True)
    destination = root / "SOURCE_PROTOCOL.json"
    if destination.exists():
        raise FileExistsError("Preserve frozen source allocation; use a new protocol directory")
    excluded = set()
    prior_pins = {}
    for name in ("natural_assets","natural_expanded_assets"):
        path = prior / name / "EVENTS.json"
        data = json.loads(path.read_text())
        prior_pins[str(path)] = digest(path.read_bytes())
        excluded.update(row["source_id"] for row in data["events"])
    selected, archives, annotation_receipts, ontology = [], {}, {}, {"action":{},"sound":{}}
    census = {}
    for split in ("train","valid"):
        ann = {}
        for kind in ("action","sound"):
            ann[kind], receipt = load_annotations(root, split, kind)
            annotation_receipts[f"{split}_{kind}"] = receipt
            for video in ann[kind].values():
                for item in video[f"{kind}_localisation"]:
                    key = str(item["label_id"])
                    if key in ontology[kind] and ontology[kind][key] != item["label"]:
                        raise ValueError("Published ontology ID conflict")
                    ontology[kind][key] = item["label"]
        remote = RemoteZip(BASE+split+"_videos.zip")
        archive = zipfile.ZipFile(remote)
        candidates=[]
        for member in archive.infolist():
            source = Path(member.filename).stem
            if (not member.filename.endswith(".mp4") or member.file_size>SIZE_LIMIT or
                    source in excluded or source not in ann["action"] or source not in ann["sound"]):
                continue
            clips = events(ann["action"][source],ann["sound"][source])
            if not clips:
                continue
            candidates.append({"source_id":source,"official_split":split,
                "member":member.filename,"source_bytes":member.file_size,
                "compressed_bytes":member.compress_size,"zip_crc32":f"{member.CRC:08x}",
                "priority":digest([SEED,source]),"events":clips})
        candidates.sort(key=lambda x:x["priority"])
        role_names = list(ROLES)[:3] if split=="train" else list(ROLES)[3:]
        need = sum(ROLES[role] for role in role_names)
        if len(candidates)<need:
            raise ValueError(f"Frozen requested source count unavailable for {split}: {len(candidates)} < {need}")
        cursor=0
        for role in role_names:
            for row in candidates[cursor:cursor+ROLES[role]]:
                row["role"]=role
                # Observer training may use all eight predeclared events. Other
                # roles use the first hashed event, with no outcome-dependent filtering.
                row["retained_event_count"]=len(row["events"]) if role=="observer_train" else 1
                selected.append(row)
            cursor+=ROLES[role]
        census[split]={"eligible_sources":len(candidates),"requested_sources":need,
                       "eligible_action_ids":sorted({e["action_id"] for v in candidates for e in v["events"]}),
                       "eligible_sound_ids":sorted({e["sound_id"] for v in candidates for e in v["events"]})}
        archives[split]={"url":remote.url,"length":remote.length,"generation":remote.generation,
                         "etag":remote.etag,"index_range_receipts":remote.receipts}
    plan={"schema":"hepta.closure.natural-sources.v1","seed":SEED,
          "created_at_unix":time.time(),"roles":ROLES,"selected":selected,
          "source_unit":"original_video_id","participant_independence_proven":False,
          "excluded_prior_video_ids":sorted(excluded),"prior_allocation_pins":prior_pins,
          "census":census,"annotation_archives":annotation_receipts,"archive":archives,
          "ontology":ontology,"selection_code_sha256":digest(Path(__file__).read_bytes()),
          "task":"same-event 2-second natural audio/video missing-segment reconstruction and action/sound caption",
          "selection":"SHA256 order among all <=12MB original MP4s with >=4.125s duration and visible sound/action overlap >=0.15s; no class or quality filtering; first hash event outside observer training",
          "decode":{"side":112,"fps":8,"sample_rate":16000,"window_seconds":4,
                    "context_video_frames":list(range(8))+list(range(24,32)),
                    "target_video_frames":list(range(8,24)),"image_target_frame":16,
                    "context_audio_samples":[[0,16000],[48000,64000]],
                    "target_audio_samples":[16000,48000]},
          "license":"CC-BY-4.0","official_documentation":"https://github.com/google-deepmind/perception_test",
          "attribution":"Patraucean et al., Perception Test: A Diagnostic Benchmark for Multimodal Video Models, NeurIPS 2023",
          "access_rule":"Only generator_train, observer_train and development media may be scored before observer and policy freezes. Separate new observer_calibration, policy_calibration and qualification sources are reserved now.",
          "qualification_rule":"No qualification feedback changes observer, model, actions, thresholds or this allocation. An inadequate observer blocks a semantic qualification claim.",
          "limits":["Visible-overlap/size-bounded task, not the full official benchmark or open-domain synthesis.",
                    "All annotated labels remain in the frozen ontology, including training-unseen classes; no future removal.",
                    "Observer training original videos are disjoint from generator training original videos.",
                    "Strong fixed interpolation, frozen neural prior and equal-budget mean-return controls are mandatory."]}
    plan["protocol_sha256"]=digest(plan)
    save(destination,plan)
    return plan


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--assets",type=Path,required=True)
    parser.add_argument("--prior-root",type=Path,required=True)
    args=parser.parse_args()
    p=freeze(args.assets,args.prior_root)
    print(json.dumps({"protocol_sha256":p["protocol_sha256"],"roles":p["roles"],
                      "original_source_bytes":sum(x["source_bytes"] for x in p["selected"]),
                      "ontology_counts":{k:len(v) for k,v in p["ontology"].items()},"census":p["census"]}))
