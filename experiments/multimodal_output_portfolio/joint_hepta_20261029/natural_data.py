"""Real Perception Test data, immutable source roles, and public-only inputs.

This module never reassigns an old observer source to generator training. The
small generator task is a mechanism check, not semantic qualification.
"""

import base64
from collections import Counter
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import resource
import subprocess
import tarfile
import time
from urllib.request import Request, urlopen
import wave
import zipfile

HERE = Path(__file__).parent
OLD = HERE.parent / "closure_20261028"
BASE = "https://storage.googleapis.com/dm-perception-test/zip_data/"


def digest(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(value).hexdigest()


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def cpu_seconds():
    own, child = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
    return own.ru_utime + own.ru_stime + child.ru_utime + child.ru_stime


def budget_check(start_cpu, start_wall, protocol):
    if cpu_seconds() - start_cpu >= protocol["budget"]["cpu_seconds"]:
        raise TimeoutError("Registered CPU admission budget exhausted; incurred work remains charged")
    if time.monotonic() - start_wall >= protocol["budget"]["wall_seconds"]:
        raise TimeoutError("Registered wall admission budget exhausted")


def restore_portable_seed(destination, source=None):
    """Verify every original chunk/member; extract only the fixed training seed."""
    source = Path(source) if source else OLD / "semantic_top1_v4"
    manifest_path = source / "ci/PILOT.json"
    if not manifest_path.exists():
        manifest_path = source / "PILOT.json"
    manifest = json.loads(manifest_path.read_text())
    checked = dict(manifest)
    expected = checked.pop("pilot_sha256")
    if digest(checked) != expected:
        raise ValueError("Original portable pilot manifest changed")
    chunks = []
    for row in manifest["seed"]["parts"]:
        data = (source / row["path"]).read_bytes()
        if len(data) != row["bytes"] or digest(data) != row["sha256"]:
            raise ValueError("Original portable seed part changed")
        record = json.loads(data)
        if set(record) != {"part", "base64"} or record["part"] != row["part"]:
            raise ValueError("Portable seed order or fields changed")
        chunks.append(record["base64"])
    payload = base64.b64decode("".join(chunks), validate=True)
    if len(payload) != manifest["seed"]["bytes"] or digest(payload) != manifest["seed"]["sha256"]:
        raise ValueError("Portable archive identity changed")
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    expected_members = {row["path"]: row for row in manifest["seed"]["members"]}
    seen = set()
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            if (not member.isfile() or name.is_absolute() or ".." in name.parts
                    or str(name) != member.name or member.name not in expected_members
                    or member.name in seen):
                raise ValueError("Unexpected or unsafe original seed member")
            row = expected_members[member.name]
            if member.size != row["bytes"]:
                raise ValueError("Original seed member length changed")
            data = archive.extractfile(member).read(member.size + 1)
            if len(data) != row["bytes"] or digest(data) != row["sha256"]:
                raise ValueError("Original seed member hash changed")
            path = destination / member.name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(data)
            seen.add(member.name)
    if seen != set(expected_members):
        raise ValueError("Incomplete portable seed")
    return destination


def read_inputs(assets, registry_path=None):
    protocol = json.loads((HERE / "natural_protocol.json").read_text())
    source_bytes = (Path(assets) / "SOURCE_PROTOCOL.json").read_bytes()
    registry_bytes = Path(registry_path or OLD / "data_source_usage_register.json").read_bytes()
    if (digest(source_bytes) != protocol["parent_source_file_sha256"]
            or digest(registry_bytes) != protocol["history_registry_sha256"]):
        raise ValueError("Original source allocation or full history registry changed")
    source, registry = json.loads(source_bytes), json.loads(registry_bytes)
    if source["protocol_sha256"] != protocol["parent_source_protocol_sha256"]:
        raise ValueError("Original source protocol identity changed")
    return protocol, source, registry


def select_training(source, protocol):
    selected = []
    for old_role, count, prefix in (("observer_train", protocol["observer_training_sources"],
                                    "hepta-joint-natural-observer-20261029:"),
                                   ("generator_train", protocol["generator_mechanism_sources"],
                                    "hepta-joint-natural-generator-20261029:")):
        rows = sorted((r for r in source["selected"] if r["role"] == old_role),
                      key=lambda r: digest((prefix + r["source_id"]).encode()))[:count]
        if len(rows) != count:
            raise ValueError("Registered training source count unavailable")
        for rank, row in enumerate(rows):
            selected.append({**row, "study_role": old_role,
                             "fold": rank % protocol["source_folds"] if old_role == "observer_train" else None})
    if len({r["source_id"] for r in selected}) != len(selected):
        raise ValueError("Generator and observer training share a source")
    return selected


def eligible_fresh_events(action, sound):
    """Original visible-overlap eligibility and corrected two-second target alignment."""
    duration = min(action["metadata"]["num_frames"] / action["metadata"]["frame_rate"],
                   sound["metadata"]["audio_samples"] / sound["metadata"]["audio_sample_rate"])
    if duration < 4.125:
        return []
    rows = []
    for a in action["action_localisation"]:
        for s in sound["sound_localisation"]:
            begin = max(a["timestamps"][0], s["timestamps"][0]) / 1e6
            end = min(a["timestamps"][1], s["timestamps"][1]) / 1e6
            if not s.get("is_visible", False) or end - begin < .15:
                continue
            target = int(max(0, min((begin + end) / 2 - 1, duration - 2.125)) * 8) / 8
            overlap = max(0, min(end, target + 2) - max(begin, target))
            if overlap < .15 - 1e-9:
                raise ValueError("Selected annotation is outside its real target")
            rows.append({"action_id": a["label_id"], "sound_id": s["label_id"],
                         "action": a["label"], "sound": s["label"],
                         "action_annotation_id": a["id"], "sound_annotation_id": s["id"],
                         "window_start_seconds": target - 1, "target_start_seconds": target,
                         "target_end_seconds": target + 2, "target_label_overlap_seconds": overlap,
                         "priority": digest(["hepta-natural-closure-20261028-source-v1",
                                             action["metadata"]["video_id"], a["id"], s["id"]])})
    return sorted(rows, key=lambda r: r["priority"])


def freeze_allocation(assets, output, registry_path=None):
    """Read archive/annotation metadata only; freeze all IDs before any predictions."""
    from ..unified_20261028.natural_data import RemoteZip
    protocol, source, registry = read_inputs(assets, registry_path)
    excluded = ({r["source_id"] for r in registry["source_rows"]}
                | set(registry["historical112_source_ids"]) | set(registry["host16_source_ids"]))
    ann = {}
    annotation_receipts = {}
    for kind in ("action", "sound"):
        name = f"challenge_{kind}_localisation_valid_annotations.zip"
        with urlopen(BASE + name, timeout=60) as response:
            data = response.read(3_000_001)
        if len(data) > 3_000_000 or digest(data) != source["annotation_archives"]["valid_" + kind]["sha256"]:
            raise ValueError("Original valid annotation identity changed")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            ann[kind] = json.loads(archive.read(archive.namelist()[0]))
        annotation_receipts[kind] = {"url": BASE + name, "sha256": digest(data), "bytes": len(data)}
    remote = RemoteZip(source["archive"]["valid"]["url"])
    pin = source["archive"]["valid"]
    if any(getattr(remote, k) != pin[k] for k in ("length", "generation", "etag")):
        raise ValueError("Original valid archive identity changed")
    candidates = []
    with zipfile.ZipFile(remote) as archive:
        for member in archive.infolist():
            sid = PurePosixPath(member.filename).stem
            if (not member.filename.endswith(".mp4") or sid in excluded
                    or member.file_size > protocol["budget"]["maximum_source_bytes"]
                    or sid not in ann["action"] or sid not in ann["sound"]):
                continue
            events = eligible_fresh_events(ann["action"][sid], ann["sound"][sid])
            if events:
                candidates.append({"source_id": sid, "member": member.filename,
                                   "source_bytes": member.file_size, "zip_crc32": f"{member.CRC:08x}",
                                   "official_split": "valid", "role": "fresh_observer_calibration",
                                   "study_role": "fresh_observer_calibration", "events": events[:1],
                                   "retained_event_count": 1, "fold": None})
    candidates.sort(key=lambda r: digest(("hepta-joint-natural-fresh-20261029:" + r["source_id"]).encode()))
    fresh = candidates[:protocol["fresh_observer_calibration_sources"]]
    if len(fresh) != protocol["fresh_observer_calibration_sources"]:
        raise ValueError("Insufficient fresh eligible sources; no source replacement allowed")
    allocation = {"schema": "hepta.joint-natural-source-allocation.v1", "protocol": protocol,
                  "protocol_sha256": digest(protocol), "parent_source_protocol_sha256": source["protocol_sha256"],
                  "ontology": source["ontology"], "archive": source["archive"],
                  "excluded_source_ids": sorted(excluded), "selected": select_training(source, protocol) + fresh,
                  "known_hashes": {r["source_id"]: r["original_video_sha256"] for r in registry["source_rows"]
                                   if "original_video_sha256" in r}, "annotation_receipts": annotation_receipts,
                  "metadata_range_receipts": remote.receipts, "media_predictions_before_freeze": 0,
                  "source_unit": "original_video_id; participant independence unknown"}
    allocation["allocation_sha256"] = digest(allocation)
    write_new(Path(output) / "ALLOCATION.json", allocation)
    return allocation


def load_allocation(path):
    value = json.loads(Path(path).read_text())
    body = dict(value)
    expected = body.pop("allocation_sha256")
    if digest(body) != expected or digest(value["protocol"]) != value["protocol_sha256"]:
        raise ValueError("Frozen natural allocation changed")
    ids = [row["source_id"] for row in value["selected"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Repeated source in natural allocation")
    for row in value["selected"]:
        role = row["study_role"]
        if role not in ("observer_train", "generator_train", "fresh_observer_calibration"):
            raise ValueError("Unregistered natural role")
        if role in ("observer_train", "generator_train") and row["role"] != role:
            raise ValueError("Original training source role reassigned")
        if role == "fresh_observer_calibration" and row["source_id"] in value["excluded_source_ids"]:
            raise ValueError("Old allocated source cannot be fresh calibration")
    return value


def require_role_access(allocation, role, freeze=None):
    if role in ("generator_train", "observer_train"):
        return
    if role != "fresh_observer_calibration" or not isinstance(freeze, dict):
        raise ValueError("Only the registered fresh observer calibration may be opened")
    if (freeze.get("allocation_sha256") != allocation["allocation_sha256"]
            or freeze.get("protocol_sha256") != allocation["protocol_sha256"]
            or freeze.get("development_passed") is not True or freeze.get("complete_folds") != 5
            or freeze.get("models_refitted_and_frozen") is not True):
        raise ValueError("Fresh media requires all complete folds and viable frozen observers")
    # Recompute admission from frozen predictions and original allocation labels;
    # a changed success flag or summary metric cannot open fresh media.
    rows = [{**event, "source_id": source["source_id"], "fold": source["fold"]}
            for source in allocation["selected"] if source["study_role"] == "observer_train"
            for event in source["events"][:source["retained_event_count"]]]
    counts = Counter(row["source_id"] for row in rows)
    if not counts or {row["fold"] for row in rows} != set(range(5)):
        raise ValueError("Admission requires all original training-source folds")
    weights = [1 / (len(counts) * counts[row["source_id"]]) for row in rows]
    for kind in ("action", "sound"):
        labels = [row[kind + "_id"] for row in rows]
        classes = sorted(map(int, allocation["ontology"][kind]))
        majority = []
        for held in range(5):
            training = [row for row in rows if row["fold"] != held]
            tc = Counter(row["source_id"] for row in training)
            mass = {label: 0.0 for label in classes}
            for row in training:
                mass[row[kind + "_id"]] += 1 / (len(tc) * tc[row["source_id"]])
            majority.append(max(classes, key=lambda label: mass[label]))
        expected_majority = [majority[row["fold"]] for row in rows]
        candidates = freeze.get("candidates", {}).get(kind, [])
        if [value["candidate"] for value in candidates] != allocation["protocol"]["candidate_order"]:
            raise ValueError("Observer candidate family changed after registration")
        for candidate in candidates:
            if sorted(value["fold"] for value in candidate["folds"]) != list(range(5)):
                raise ValueError("Incomplete frozen cross-validation fits")
            for name in ("out_of_fold", "majority_control"):
                report = candidate[name]
                predicted = report["predictions"]
                if (report["labels"] != labels or report["source_ids"] != [row["source_id"] for row in rows]
                        or len(predicted) != len(rows) or any(p not in classes for p in predicted)
                        or (name == "majority_control" and predicted != expected_majority)):
                    raise ValueError("Frozen OOF predictions do not match original source/label rows")
                actual = sum(w for w, p, label in zip(weights, predicted, labels, strict=True) if p == label)
                if (not math.isfinite(report["source_uniform_accuracy"])
                        or abs(report["source_uniform_accuracy"] - actual) > 1e-12):
                    raise ValueError("Frozen OOF summary disagrees with its actual predictions")
        chosen = max(candidates, key=lambda value: value["out_of_fold"]["source_uniform_accuracy"])
        selected = freeze.get("selected", {}).get(kind, {})
        if (selected.get("candidate") != chosen["candidate"]
                or selected.get("out_of_fold") != chosen["out_of_fold"]
                or selected.get("majority_control") != chosen["majority_control"]
                or chosen["out_of_fold"]["source_uniform_accuracy"] < allocation["protocol"]["adequacy"][kind + "_accuracy"]
                or chosen["out_of_fold"]["source_uniform_accuracy"] <= chosen["majority_control"]["source_uniform_accuracy"]):
            raise ValueError("Fresh media admission failed its registered source-uniform adequacy rule")


def download_weights(destination):
    """Only the two original small pinned backbones; no checkpoint selection."""
    manifest = json.loads((OLD / "semantic_top1_v4/ci/PILOT.json").read_text())
    rows = [r for r in manifest["weights"] if r["name"] in ("s3d-d76dad2f.pth", "MobileNetV2_mAP_0.383.pth")]
    if len(rows) != 2:
        raise ValueError("Required original pretrained identities missing")
    Path(destination).mkdir(parents=True, exist_ok=True)
    receipts = []
    for row in rows:
        path = Path(destination) / row["name"]
        if not path.exists():
            with urlopen(Request(row["url"], headers={"User-Agent": "hepta-natural-observer/1"}), timeout=120) as response:
                with path.open("xb") as stream:
                    total = 0
                    while True:
                        block = response.read(min(1048576, row["bytes"] - total + 1))
                        if not block:
                            break
                        total += len(block)
                        if total > row["bytes"]:
                            raise ValueError("Pretrained file exceeded its frozen size")
                        stream.write(block)
        if path.stat().st_size != row["bytes"] or digest(path.read_bytes()) != row["sha256"]:
            raise ValueError("Pretrained file identity mismatch")
        receipts.append(row)
    return receipts


def media_roundtrip(directory, video, audio, image, caption):
    """Write real media and reopen it before any semantic feature calculation."""
    import numpy as np
    from PIL import Image
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "caption.txt").write_text(caption, encoding="utf-8")
    Image.fromarray(image).save(directory / "image.png")
    pcm = (np.clip(audio, -1, 1) * 32767).round().astype("<i2")
    with wave.open(str(directory / "audio.wav"), "wb") as stream:
        stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(16000); stream.writeframes(pcm.tobytes())
    command = ["ffmpeg", "-v", "error", "-threads", "1", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", "112x112", "-r", "8", "-i", "pipe:0", "-c:v", "ffv1", "-threads", "1",
               "-pix_fmt", "rgb24", str(directory / "video.mkv")]
    subprocess.run(command, input=video.tobytes(), capture_output=True, check=True, timeout=60)
    result = subprocess.run(["ffmpeg", "-v", "error", "-threads", "1", "-i", str(directory / "video.mkv"),
                             "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], capture_output=True, check=True, timeout=60)
    reopened = np.frombuffer(result.stdout, np.uint8).reshape(16, 112, 112, 3)
    with wave.open(str(directory / "audio.wav"), "rb") as stream:
        wave_bytes = stream.readframes(stream.getnframes())
        if stream.getnchannels() != 1 or stream.getsampwidth() != 2 or stream.getframerate() != 16000:
            raise ValueError("Delivered audio format changed")
    if (not np.array_equal(reopened, video) or wave_bytes != pcm.tobytes()
            or not np.array_equal(np.asarray(Image.open(directory / "image.png")), image)
            or (directory / "caption.txt").read_text() != caption):
        raise ValueError("Real media roundtrip differs from its declared conversion")
    hashes = {p.name: digest(p.read_bytes()) for p in sorted(directory.iterdir())}
    return reopened, np.frombuffer(wave_bytes, "<i2").astype(np.float32) / 32767, hashes


def prepare_role(allocation, assets, role, *, models=None, freeze=None, start_cpu=None, start_wall=None):
    import numpy as np
    from ..unified_20261028.natural_data import RemoteZip
    from ..closure_20261028.data_prepare import decode
    from ..closure_20261028.data_prepare_v2 import window
    require_role_access(allocation, role, freeze)
    start_cpu = cpu_seconds() if start_cpu is None else start_cpu
    start_wall = time.monotonic() if start_wall is None else start_wall
    selected = [r for r in allocation["selected"] if r["study_role"] == role]
    archives, remotes, seen_hashes = {}, {}, dict(allocation["known_hashes"])
    rows = []
    for source in selected:
        budget_check(start_cpu, start_wall, allocation["protocol"])
        sid, split = source["source_id"], source["official_split"]
        destination = Path(assets) / "prepared" / role / sid
        destination.mkdir(parents=True, exist_ok=False)
        if split not in archives:
            remote = RemoteZip(allocation["archive"][split]["url"])
            if any(getattr(remote, k) != allocation["archive"][split][k] for k in ("length", "generation", "etag")):
                raise ValueError("Frozen official media archive changed")
            remotes[split], archives[split] = remote, zipfile.ZipFile(remote)
        payload = archives[split].read(source["member"])
        sha = digest(payload)
        if len(payload) != source["source_bytes"]:
            raise ValueError("Frozen media member size changed")
        if sid in seen_hashes and seen_hashes[sid] != sha:
            raise ValueError("Previously observed original source bytes changed")
        if any(other != sid and old == sha for other, old in seen_hashes.items()):
            raise ValueError("Duplicated original media cannot supply a fresh source")
        seen_hashes[sid] = sha
        raw = destination / "source.mp4"
        raw.write_bytes(payload)
        frames, waveform = decode(raw)
        event_rows, visual, sound = [], [], []
        for index, event in enumerate(source["events"][:source["retained_event_count"]]):
            budget_check(start_cpu, start_wall, allocation["protocol"])
            video, audio, vm, am = window(frames, waveform, event)
            event_dir = destination / f"event-{index:02d}"
            reopened, wav, files = media_roundtrip(event_dir, video[8:24], audio[16000:48000], video[16],
                                                 event["action"].lower() + "; " + event["sound"].lower())
            if models is not None:
                vf, af, _ = models.features(reopened[None], wav[None])
                visual.append(vf[0]); sound.append(af[0])
            if role == "generator_train":
                np.savez_compressed(event_dir / "EVENT.npz", context_video=video[np.r_[0:8, 24:32]],
                                    context_audio=audio[np.r_[0:16000, 48000:64000]],
                                    context_video_mask=vm[np.r_[0:8, 24:32]],
                                    context_audio_mask=am[np.r_[0:16000, 48000:64000]],
                                    target_video=reopened, target_audio=wav, target_image=video[16])
                files["EVENT.npz"] = digest((event_dir / "EVENT.npz").read_bytes())
            event_rows.append({**event, "event_id": sid + f"-joint-{index}", "source_id": sid,
                               "source_sha256": sha, "role": role, "fold": source["fold"],
                               "directory": str(event_dir.relative_to(Path(assets))), "files": files})
        if models is not None:
            np.savez_compressed(destination / "FEATURES.npz", video=np.stack(visual), audio=np.stack(sound))
        receipt = {"allocation_sha256": allocation["allocation_sha256"], "source_id": sid, "role": role,
                   "original_sha256": sha, "source_member": source["member"], "events": event_rows,
                   "observer_freeze_sha256": digest(freeze) if freeze else None,
                   "feature_sha256": digest((destination / "FEATURES.npz").read_bytes()) if models else None}
        write_new(destination / "RECEIPT.json", receipt)
        rows.extend(event_rows)
        print(json.dumps({"natural_role": role, "source": sid, "events": len(event_rows),
                          "cpu_seconds": cpu_seconds() - start_cpu}), flush=True)
    write_new(Path(assets) / (role + "_PREPARED.json"), {"allocation_sha256": allocation["allocation_sha256"],
              "role": role, "rows": rows, "range_receipts": {k: v.receipts for k, v in remotes.items()}})
    return rows


def load_natural_clips(manifest, assets, *, video_frames=4, side=16, audio_samples=1024):
    """Return public masked context separately from training/scorer-only targets.

    These eight original generator-training sources are never qualification.
    Reduced media resolution is explicitly a new mechanism task.
    """
    import numpy as np
    import torch
    from scipy.signal import resample_poly
    from torch.nn import functional as F
    if (video_frames < 1 or video_frames > 16 or 2000 % video_frames
            or audio_samples < 2 or audio_samples % 2 or not 1 <= side <= 112):
        raise ValueError("Reduced real-media clock must preserve exactly two seconds")
    allocation = load_allocation(manifest)
    record = json.loads((Path(assets) / "generator_train_PREPARED.json").read_text())
    if record["allocation_sha256"] != allocation["allocation_sha256"]:
        raise ValueError("Prepared generator media belongs to another allocation")
    permitted = {r["source_id"] for r in allocation["selected"] if r["study_role"] == "generator_train"}
    inputs, targets, metadata = [], [], []
    classes = {k: sorted(map(int, allocation["ontology"][k])) for k in ("action", "sound")}
    for row in record["rows"]:
        if row["source_id"] not in permitted or row["role"] != "generator_train":
            raise ValueError("Observer or held-out sources cannot enter generator training")
        path = Path(assets) / row["directory"] / "EVENT.npz"
        if digest(path.read_bytes()) != row["files"]["EVENT.npz"]:
            raise ValueError("Actual prepared media changed")
        with np.load(path, allow_pickle=False) as x:
            def visual(name):
                value = torch.tensor(x[name].copy()).permute(0, 3, 1, 2).float() / 255
                ids = torch.arange(video_frames) * len(value) // video_frames
                return F.interpolate(value[ids], (side, side), mode="area")
            def audio(name):
                waveform = x[name].copy()
                divisor = math.gcd(len(waveform), audio_samples)
                converted = resample_poly(waveform, audio_samples // divisor, len(waveform) // divisor)
                return torch.from_numpy(np.asarray(converted, np.float32))
            ids = torch.arange(video_frames) * len(x["context_video"]) // video_frames
            inputs.append({"video": visual("context_video"), "audio": audio("context_audio"),
                           "video_mask": torch.tensor(x["context_video_mask"].copy())[ids],
                           "audio_mask": F.interpolate(torch.tensor(x["context_audio_mask"].copy()).float()[None, None],
                                                        size=audio_samples, mode="nearest")[0, 0]})
            target_video = visual("target_video")
            target_image = F.interpolate(torch.tensor(x["target_image"].copy()).permute(2, 0, 1)[None].float() / 255,
                                         (side, side), mode="area")[0]
            targets.append({"video": target_video, "image": target_image, "audio": audio("target_audio"),
                            "text_ids": torch.tensor([classes[k].index(row[k + "_id"]) for k in ("action", "sound")])})
            metadata.append({k: row[k] for k in ("event_id", "source_id", "source_sha256", "role")})
    if set(m["source_id"] for m in metadata) != permitted:
        raise ValueError("Incomplete registered generator mechanism cohort")
    return {"inputs": {k: torch.stack([r[k] for r in inputs]) for k in inputs[0]},
            "targets": {k: torch.stack([r[k] for r in targets]) for k in targets[0]},
            "metadata": metadata, "classes": classes, "qualification": False,
            "media_clock": {"target_seconds": 2, "video_frames": video_frames,
                            "video_frame_duration_ms": 2000 // video_frames,
                            "audio_sample_rate": audio_samples // 2,
                            "audio_resample": "Polyphase FIR antialiasing; severely bandwidth-limited restoration diagnostic",
                            "image_target_seconds": 1.0},
            "scope": "Real source-separated small reconstruction mechanism; no semantic ability claim"}
