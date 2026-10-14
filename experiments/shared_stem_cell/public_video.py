"""Pinned real sample videos -> frozen CLIP frames -> temporal Cell controls.

The registered task is forward-vs-reversed presentation of identical source
frames. It measures temporal-order use, not human action labels or generation.
Source media are downloaded for the run and are NOT uploaded as result artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import io
from pathlib import Path
from urllib.request import Request, urlopen

from PIL import Image
import torch

from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell.public_smoke import stage_model
from experiments.shared_stem_cell.video_temporal import run as run_temporal

DATA_REPO = "ryukenzen/360action"
DATA_REVISION = "6e99f3e7393ef3fa690b43f38fd4ea261a16a804"
README_BLOB = "8eae80b1cfcd83dddc366cc1769265389d0060c0"
VISION = "openai/clip-vit-base-patch32"
VISION_REVISION = "3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268"
INVENTORY = {
    "Scene1A_14.mp4": ("29fe53ba7da904313663eef6d4c0cafe88640105", 216503, "train"),
    "Scene1B_84.mp4": ("eb2500dc321d8b0ad082db71ee3064831ddfe230", 211301, "train"),
    "Scene2_22.mp4": ("1fb7540fe6e225de34b4d042199ac99f19691fe4", 113842, "train"),
    "Scene3A_55.mp4": ("f52aa01c3a3edf3a813205a9be7b56d15f43b26a", 209921, "train"),
    "Scene4A_4.mp4": ("18cfc6bfcca25a06a3ff036425a576b878f276f6", 162536, "train"),
    "Scene4B_17.mp4": ("810e09720435c52dddb08b11bea824c288b02849", 437945, "train"),
    "Scene5A_48.mp4": ("f51133145194c9beaf3743275bf1fea742e2e1e3", 359962, "calibration"),
    "Scene5B_20.mp4": ("b9016469bc9a73dd1e94058185faeff2806387d8", 136073, "calibration"),
    "Scene6A_47.mp4": ("a7807a5a3fa0b0d1054a2b4eaf9c586d94df967e", 261320, "holdout"),
    "Scene6B_59.mp4": ("846b26cd75edf08d710a5a58dd60ba19d1b85c5c", 194440, "holdout"),
}
MAX_DOWNLOAD = 2 * 1024**2
SCOPE = "public-360action-temporal-order-research"


def git_blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def read_url(url, maximum):
    with urlopen(Request(url, headers={"User-Agent": "hepta-public-video-research"}), timeout=60) as response:
        raw = response.read(maximum + 1)
    if len(raw) > maximum:
        raise e.InputError("public video acquisition exceeds byte budget")
    return raw


def verify_tree(record, *, inventory=INVENTORY, revision=DATA_REVISION, readme_blob=README_BLOB):
    if (not isinstance(record, dict) or record.get("sha") != revision
            or record.get("truncated") is not False or not isinstance(record.get("tree"), list)):
        raise e.InputError("complete pinned public video tree required")
    videos = {}
    for item in record["tree"]:
        path = item.get("path")
        if isinstance(path, str) and path.startswith("videos/small/") and path.endswith(".mp4"):
            name = Path(path).name
            if (name in videos or item.get("type") != "blob" or item.get("mode") != "100644"
                    or type(item.get("size")) is not int or not isinstance(item.get("sha"), str)):
                raise e.InputError("ordinary unique MP4 tree member required")
            videos[name] = (item["sha"], item["size"])
    expected = {name: value[:2] for name, value in inventory.items()}
    if videos != expected:
        raise e.InputError("public sample video inventory drift")
    readmes = [item for item in record["tree"] if item.get("path") == "README.md"]
    if len(readmes) != 1 or readmes[0].get("sha") != readme_blob:
        raise e.InputError("video source attribution drift")
    return videos


def decode_mp4(raw):
    """Decode bounded RGB frames with exact monotone source presentation times."""
    try:
        import av
    except ImportError as error:
        raise e.InputError("PyAV is required for explicit MP4 decoding") from error
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_DOWNLOAD:
        raise e.InputError("bounded MP4 bytes required")
    frames = []
    with av.open(io.BytesIO(raw), mode="r") as container:
        streams = list(container.streams.video)
        if len(streams) != 1:
            raise e.InputError("one video stream required")
        stream = streams[0]
        for frame in container.decode(stream):
            if len(frames) >= 512 or frame.pts is None:
                raise e.InputError("bounded timestamped decoded frames required")
            base = frame.time_base or stream.time_base
            stamp = int(frame.pts * base.numerator * 1_000_000 // base.denominator)
            image = frame.to_image().convert("RGB")
            if image.width * image.height > 4_194_304 or min(image.size) < 32:
                raise e.InputError("bounded nontrivial video frame required")
            frames.append((image, stamp))
    if not 32 <= len(frames) <= 512:
        raise e.InputError("at least32 bounded decoded frames required")
    offset = frames[0][1]
    normalized = [(image, stamp - offset) for image, stamp in frames]
    if normalized[0][1] != 0 or any(b[1] <= a[1] for a, b in zip(normalized, normalized[1:])):
        raise e.InputError("strict source frame chronology required")
    return normalized


def select_landmarks(frames):
    if not isinstance(frames, list) or not 32 <= len(frames) <= 512:
        raise e.InputError("32..512 decoded frames required")
    indices = [i * (len(frames) - 1) // 31 for i in range(32)]
    if len(set(indices)) != 32:
        raise e.InputError("unique temporal landmarks required")
    return [(index, *frames[index]) for index in indices]


def png_bytes(image):
    image = image.resize((224, 224), Image.Resampling.LANCZOS)
    stream = io.BytesIO()
    image.save(stream, format="PNG", optimize=False, compress_level=9)
    raw = stream.getvalue()
    if not 100 <= len(raw) <= 1024**2:
        raise e.InputError("bounded deterministic staged PNG required")
    return raw


def stage(root, *, _read=read_url, _decode=decode_mp4, inventory=INVENTORY,
          revision=DATA_REVISION, readme_blob=README_BLOB):
    tree_raw = _read(f"https://api.github.com/repos/{DATA_REPO}/git/trees/{revision}?recursive=1", 2*1024**2)
    record = e.decode(tree_raw)
    verify_tree(record, inventory=inventory, revision=revision, readme_blob=readme_blob)
    (root / "source-tree.json").write_bytes(tree_raw)
    readme = _read(f"https://raw.githubusercontent.com/{DATA_REPO}/{revision}/README.md", 64*1024)
    if git_blob(readme) != readme_blob:
        raise e.InputError("source README bytes drift")
    (root / "SOURCE-README.txt").write_bytes(readme)
    frames_root = root / "frames"; frames_root.mkdir(exist_ok=False)
    rows, cohort, receipts = [], [], []
    for source_index, (name, (blob, size, split)) in enumerate(inventory.items()):
        raw = _read(f"https://raw.githubusercontent.com/{DATA_REPO}/{revision}/videos/small/{name}", MAX_DOWNLOAD)
        if len(raw) != size or git_blob(raw) != blob:
            raise e.InputError("pinned MP4 source bytes drift")
        decoded = _decode(raw)
        selected = select_landmarks(decoded)
        staged = []
        for landmark, (decoded_index, image, source_stamp) in enumerate(selected):
            payload = png_bytes(image)
            digest = e.sha(payload)
            path = frames_root / (digest + ".png")
            if path.exists() and path.read_bytes() != payload:
                raise e.InputError("staged frame hash collision")
            if not path.exists():
                path.write_bytes(payload)
            staged.append({"path": path.relative_to(root).as_posix(), "sha256": digest,
                           "decoded_index": decoded_index, "source_timestamp_us": source_stamp})
        source_id = e.sha(e.canonical([revision, name, blob]))
        receipts.append({"source_id": source_id, "source_name": name, "source_git_blob": blob,
            "source_bytes": size, "decoded_frames": len(decoded), "landmarks": staged, "split": split})
        for window in range(4):
            base = staged[window*8:(window+1)*8]
            pair_id = e.sha(e.canonical([source_id, window]))
            for direction, label, sequence in (("forward", 0, base), ("reverse", 1, list(reversed(base)))):
                case_id = e.sha(e.canonical([pair_id, direction]))
                video = [{"path": frame["path"], "sha256": frame["sha256"],
                          "timestamp_us": i * 40000} for i, frame in enumerate(sequence)]
                rows.append({"case_id": case_id, "group": source_id, "split": split,
                    "scope": SCOPE, "observed_at": 7*40000, "inputs": {"video": video}, "label": label})
                cohort.append({"case_id": case_id, "pair_id": pair_id, "source_id": source_id,
                    "split": split, "direction": direction,
                    "frame_sha256s": [frame["sha256"] for frame in sequence]})
    counts = {s: sum(row["split"] == s for row in rows) for s in ("train", "calibration", "holdout")}
    if counts != {"train": 48, "calibration": 16, "holdout": 16}:
        raise e.InputError("fixed source-disjoint temporal denominator changed")
    cohort_raw = e.canonical(cohort)
    (root / "cohort.json").write_bytes(cohort_raw)
    dataset_raw = b"".join(e.canonical(row) for row in rows)
    (root / "dataset.jsonl").write_bytes(dataset_raw)
    e.write_once(root / "video-provenance.json", {"repository": DATA_REPO, "revision": revision,
        "sources": receipts, "source_video_split_disjoint": True,
        "task": "same frame multiset, original vs reversed presentation",
        "resize": "Pillow LANCZOS to224x224 before CLIP", "source_license_declared": None,
        "source_media_uploaded_as_artifact": False, "independent_evaluation": False,
        "production_accepted": False})
    return ({"path": "dataset.jsonl", "sha256": e.sha(dataset_raw)},
            {"path": "cohort.json", "sha256": e.sha(cohort_raw)})


def main(root, *, _read=read_url, _decode=decode_mp4, _stage_model=stage_model,
         _tower_factory=None):
    root = Path(root); root.mkdir(parents=True, exist_ok=False)
    e.write_once(root / "plan.json", {"schema": "hepta.public-video-plan.v1",
        "source_revision": DATA_REVISION, "model": VISION, "model_revision": VISION_REVISION,
        "source_files": list(INVENTORY), "split_by_source_video": True,
        "task": "original_vs_reversed_same_frames", "classes": 2, "steps": 80,
        "source_license_declared": None, "source_media_uploaded_as_artifact": False,
        "production_accepted": False})
    try:
        with e.measured() as acquisition:
            dataset, cohort = stage(root, _read=_read, _decode=_decode)
            model_root = root / "vision"; model_root.mkdir()
            model = _stage_model(model_root, VISION, VISION_REVISION, kind="clip", allow_conversion=False)
        model["path"] = "vision/model"
        manifest = {"schema": "hepta.shared-stem-media.v1", "classes": 2, "steps": 80,
            "seed": 20261014, "temporal": False, "video_profile": "paired_temporal_order_v1",
            "dataset": dataset, "cohort": cohort, "models": {"clip": model}}
        e.write_once(root / "manifest.json", manifest)
        kwargs = {} if _tower_factory is None else {"_tower_factory": _tower_factory}
        result = run_temporal(root / "manifest.json", root / "execution", **kwargs)
        report = {"schema": "hepta.public-video-executed.v1", "acquisition": acquisition,
            "execution_report_sha256": e.sha((root / "execution/report.json").read_bytes()),
            "scores": result["scores"], "frame_cache": result["frame_cache"],
            "simulated_towers": result["simulated_towers"], "production_accepted": False}
        e.write_once(root / "report.json", report)
        return report
    except Exception as error:
        e.write_once(root / "failure.json", {"error": type(error).__name__, "message": str(error),
                                            "production_accepted": False})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(2)
    main(args.output)
