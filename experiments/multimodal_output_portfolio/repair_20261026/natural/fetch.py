"""Fetch bounded public sources and a pinned ASR checkpoint without private data."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.parse
import urllib.request


DATASET_REVISION = "71cacbfb7e2354c4226d01e70d77d5fca3d04ba1"
VIDEO_REVISION = "579424605134b7d7027377bdc51f3c23536c4414"
MODEL_REVISION = "0d3d19a32d3338f10357c0889762bd8d64bbdeba"


def download(url, path, limit):
    path.parent.mkdir(parents=True, exist_ok=True)
    sha, size = hashlib.sha256(), 0
    with urllib.request.urlopen(url, timeout=30) as response, path.open("xb") as stream:
        while block := response.read(1024 * 1024):
            size += len(block)
            if size > limit:
                raise ValueError("Public asset exceeds registered size limit")
            sha.update(block)
            stream.write(block)
    return {"path": str(path), "sha256": sha.hexdigest(), "bytes": size, "source_url": url.split("?Expires=")[0]}


def main(root):
    root.mkdir(parents=True, exist_ok=False)
    files, audio = [], []
    dataset = "openslr/librispeech_asr"
    metadata = root / "dataset-metadata.json"
    files.append(download(f"https://huggingface.co/api/datasets/{dataset}", metadata, 1000000))
    if json.loads(metadata.read_text())["sha"] != DATASET_REVISION:
        raise ValueError("Dataset revision changed before source freeze")
    selection = {"fit": ("validation", [0, 300, 600, 900]), "test": ("test", [0, 300, 600, 900, 1200, 1500, 1800, 2100])}
    for role, (split, offsets) in selection.items():
        for offset in offsets:
            query = urllib.parse.urlencode(dict(dataset=dataset, config="clean", split=split, offset=offset, length=3))
            path = root / "metadata" / f"{role}-{offset}.json"
            files.append(download("https://datasets-server.huggingface.co/rows?" + query, path, 1000000))
            for item in json.loads(path.read_text())["rows"]:
                row = item["row"]
                url = row["audio"][0]["src"]
                if f"/--/{DATASET_REVISION}/--/" not in url:
                    raise ValueError("Dataset byte revision differs from frozen selection")
                asset = download(url, root / "speech" / (row["id"] + ".flac"), 3000000)
                files.append(asset)
                audio.append({"role": role, "split": split, "row_index": item["row_idx"], "id": row["id"],
                    "speaker_id": row["speaker_id"], "chapter_id": row["chapter_id"], "reference": row["text"], **asset})
    fit = {r["speaker_id"] for r in audio if r["role"] == "fit"}
    test = {r["speaker_id"] for r in audio if r["role"] == "test"}
    if fit & test or len(fit) != 4 or len(test) != 8:
        raise ValueError("Prespecified actual speaker split failed")
    videos = []
    for name, role in (("david", "fit"), ("dudek", "test"), ("faceocc2", "test")):
        base = f"https://raw.githubusercontent.com/opencv/opencv_extra/{VIDEO_REVISION}/testdata/cv/tracking/{name}"
        video = download(base + f"/data/{name}.webm", root / "video" / f"{name}.webm", 10000000)
        annotation = download(base + "/gt.txt", root / "video" / f"{name}.gt.txt", 100000)
        config = download(base + f"/{name}.yml", root / "video" / f"{name}.yml", 10000)
        files.extend((video, annotation, config))
        videos.append({"name": name, "role": role, "video": video, "annotation": annotation, "config": config})
    for filename in ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt", "README.md"):
        files.append(download(f"https://huggingface.co/Systran/faster-whisper-tiny.en/resolve/{MODEL_REVISION}/{filename}",
                              root / "whisper" / filename, 85000000))
    manifest = {"schema": "hepta.repair.natural.assets.v1", "dataset_revision": DATASET_REVISION,
        "video_revision": VIDEO_REVISION, "asr_revision": MODEL_REVISION, "speech": audio, "video": videos,
        "fit_speakers": sorted(fit), "test_speakers": sorted(test), "speaker_overlap": [], "files": files,
        "scope": "Natural ASR and annotated visual tracking; not natural multimodal generation"}
    (root / "MANIFEST.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"speech_rows": len(audio), "fit_speakers": sorted(fit), "test_speakers": sorted(test),
                      "downloaded_bytes": sum(r["bytes"] for r in files)}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args().output)
