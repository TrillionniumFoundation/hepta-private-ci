"""Freeze natural-video source bytes and target-blind frame-index allocation."""
import argparse
from pathlib import Path
import time

import cv2
import numpy as np
from PIL import Image

from .common import download, read, save, sha


def isolated_indices(first, last, count):
    """Choose targets whose pixels cannot also be an endpoint in this clip."""
    eligible = np.asarray([i for i in range(first, last+1) if i % 4 in (2, 3)])
    if len(eligible) < count:
        raise ValueError("Source range too short for isolated frame allocation")
    positions = np.rint(np.linspace(0, len(eligible)-1, count)).astype(int)
    return eligible[positions]


def run(output, download_only=False, prepare_existing=False, resume_downloads=False):
    source = Path(__file__).parent
    spec = read(source / "VIDEO_PROTOCOL.json")
    if prepare_existing and ((output / "MANIFEST.json").exists() or not (output / "SOURCE_VIDEO_FILES.json").exists()):
        raise ValueError("Prepare requires downloaded but unprepared sources")
    if resume_downloads and (not output.exists() or (output / "MANIFEST.json").exists()):
        raise ValueError("Resume requires a partial source collection")
    output.mkdir(parents=True, exist_ok=prepare_existing or resume_downloads)
    files, samples, clips = [], [], []
    cv2.setNumThreads(1)
    start = time.perf_counter()
    if prepare_existing:
        saved = read(output / "SOURCE_VIDEO_FILES.json")
        if saved["protocol_sha256"] != sha(source / "VIDEO_PROTOCOL.json"):
            amendment = read(source / "VIDEO_FRAME_ISOLATION_AMENDMENT.json")
            if (saved["protocol_sha256"] != amendment["original_protocol_sha256"]
                    or sha(source / "VIDEO_PROTOCOL.json") != amendment["amended_protocol_sha256"]):
                raise ValueError("Undocumented protocol change after source download")
        assets = saved["files"]
    else:
        assets=[]
        for item in spec["sources"]:
            path=output/"videos"/(item["name"]+Path(item["url"]).suffix)
            if resume_downloads and path.exists():
                if not 0<path.stat().st_size<=20000000:
                    raise ValueError("Invalid cached source size")
                assets.append({"path":str(path),"sha256":sha(path),"bytes":path.stat().st_size,"source_url":item["url"]})
            else:
                assets.append(download(item["url"],path,20000000))
        save(output / "SOURCE_VIDEO_FILES.json", {"protocol_sha256": sha(source / "VIDEO_PROTOCOL.json"), "files": assets})
    if download_only:
        print({"downloaded_videos": len(assets), "bytes": sum(a["bytes"] for a in assets)}, flush=True)
        return
    for item, asset in zip(spec["sources"], assets):
        if sha(asset["path"]) != asset["sha256"]:
            raise ValueError("Source video bytes changed")
        files.append(asset)
        video = cv2.VideoCapture(asset["path"])
        if not video.isOpened():
            raise ValueError("Actual source video cannot be decoded")
        frames = []
        for _ in range(spec["frame_selection"]["maximum_decoded_frames"]):
            ok, image = video.read()
            if not ok:
                break
            width = spec["frame_selection"]["resize_width"]
            height = round(image.shape[0]*width/image.shape[1])
            frames.append(cv2.cvtColor(cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB))
        fps = video.get(cv2.CAP_PROP_FPS)
        video.release()
        if len(frames) < 36:
            raise ValueError("Source too short for frozen allocation")
        cut = int(.6*len(frames))
        allocations = [("train", isolated_indices(2, cut-3, 12)),
            ("validation", isolated_indices(cut+2, len(frames)-3, 6))] if item["role"] == "development" else [
            ("test", isolated_indices(2, len(frames)-3, 12))]
        target_indices = {int(i) for _, indices in allocations for i in indices}
        public_indices = {i+offset for i in target_indices for offset in (-2, 2)}
        if target_indices & public_indices:
            raise ValueError("Private target frame appears as a public endpoint")
        for role, indices in allocations:
            for index in indices:
                identity = f"{item['name']}-{index:04d}"
                paths = {}
                for label, offset in (("left", -2), ("private_target", 0), ("right", 2)):
                    path = output / "frames" / identity / (label+".png")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    Image.fromarray(frames[index+offset]).save(path)
                    record = {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size,
                        "source_video_sha256": asset["sha256"], "source_frame_index": int(index+offset),
                        "resize_width": width, "generated_canonical_input_from_real_video": True}
                    files.append(record)
                    paths[label] = str(path)
                samples.append({"id": identity, "source": item["name"], "role": role,
                    "target_index": int(index), "source_video_sha256": asset["sha256"], **paths})
        clips.append({**item, **asset, "decoded_frames": len(frames), "fps": fps,
            "canonical_shape": list(frames[0].shape),
            "private_target_frame_indices": sorted(target_indices),
            "public_endpoint_frame_indices": sorted(public_indices),
            "target_endpoint_overlap": sorted(target_indices & public_indices)})
        print({"video_source": item["name"], "decoded_frames": len(frames)}, flush=True)
    if len({c["sha256"] for c in clips}) != len(clips):
        raise ValueError("Duplicate source video")
    save(output / "MANIFEST.json", {"schema": "hepta.ndu.continuation.video.assets.v1",
        "protocol_sha256": sha(source / "VIDEO_PROTOCOL.json"), "clips": clips, "samples": samples, "files": files,
        "common_source_preprocessing_wall_seconds": time.perf_counter()-start,
        "task_input": "Canonical endpoint PNG pairs; preprocessing from source video is common data preparation and separately measured",
        "independent_test_sources": len([c for c in clips if c["role"] == "test"]),
        "attribution": "Original pinned OpenCV and imageio public test assets; no inference of one blanket license for upstream media"})


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--download-only",action="store_true")
    parser.add_argument("--prepare-existing",action="store_true")
    parser.add_argument("--resume-downloads",action="store_true")
    args=parser.parse_args()
    run(args.output,args.download_only,args.prepare_existing,args.resume_downloads)
