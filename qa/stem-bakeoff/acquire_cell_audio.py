"""Acquire only the frozen ESC-50 cohort; verify pinned Git objects and WAV data."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import io
import json
from pathlib import Path
import time
import urllib.request
import wave

from prepare_cell_media import ESC_REVISION, canonical, input_identity, sha


def verify_audio(raw, row):
    if len(raw) != row["media_bytes"] or not 0 < len(raw) <= 1_000_000:
        raise ValueError("audio object size differs from the pinned tree")
    git_sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if git_sha != row["upstream_blob_sha"]:
        raise ValueError("audio bytes differ from the pinned Git blob")
    with wave.open(io.BytesIO(raw), "rb") as clip:
        details = {"channels": clip.getnchannels(), "sample_rate": clip.getframerate(),
                   "sample_width": clip.getsampwidth(), "frames": clip.getnframes()}
        if (details != {"channels": 1, "sample_rate": 44100, "sample_width": 2, "frames": 220500}
                or clip.getcomptype() != "NONE" or len(clip.readframes(220501)) != 441000):
            raise ValueError("published full five-second PCM waveform required")
    expected = input_identity("audio", row["text"], "git-blob-sha1:" + git_sha)
    if row["input_content_sha256"] != expected:
        raise ValueError("full predictor identity differs")
    return {"source_id": row["source_id"], "relative_path": row["record"]["audio"],
            "sha256": sha(raw), "bytes": len(raw), "git_blob_sha1": git_sha, **details}


def acquire_one(root, row):
    relative = row["record"]["audio"]
    if relative != "media/" + row["filename"] or Path(row["filename"]).name != row["filename"]:
        raise ValueError("audio output must stay in the frozen media directory")
    expected_url = f"https://raw.githubusercontent.com/karolpiczak/ESC-50/{ESC_REVISION}/audio/" + row["filename"]
    if row["upstream_url"] != expected_url or row["source_version"] != "git:" + ESC_REVISION:
        raise ValueError("only pinned official audio objects may be acquired")
    destination = root / relative
    if destination.is_symlink():
        raise ValueError("media destination cannot be a symlink")
    if destination.exists():
        return {**verify_audio(destination.read_bytes(), row), "acquisition": "verified_existing"}
    started = time.perf_counter_ns()
    errors = []
    for attempt in range(3):
        try:
            request = urllib.request.Request(expected_url, headers={"User-Agent": "hepta-local-research/1"})
            with urllib.request.urlopen(request, timeout=45) as response:
                raw = response.read(1_000_001)
            result = verify_audio(raw, row)
            with destination.open("xb") as stream:
                stream.write(raw)
            return {**result, "acquisition": "pinned_https", "attempts": attempt + 1,
                    "prior_errors": errors, "wall_ns": time.perf_counter_ns() - started}
        except Exception as error:
            errors.append({"type": type(error).__name__, "message": str(error)[:500]})
    raise RuntimeError(json.dumps({"source_id": row["source_id"], "errors": errors}))


def acquire(dataset, workers=4):
    path = Path(dataset)
    raw = path.read_bytes()
    data = json.loads(raw)
    root = path.parent
    if (data["protocol"]["revision"] != ESC_REVISION or data["protocol"]["input_modality"] != "audio"
            or not 1 <= workers <= 6 or not 1 <= len(data["rows"]) <= 1000):
        raise ValueError("bounded frozen audio cohort required")
    inventory_path = root / "media-inventory.json"
    if inventory_path.exists():
        raise FileExistsError("completed acquisition inventory already exists")
    (root / "media").mkdir(exist_ok=True)
    started = time.perf_counter_ns()
    entries, errors = [], []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(acquire_one, root, row): row["source_id"] for row in data["rows"]}
        for future in as_completed(futures):
            try:
                entries.append(future.result())
            except Exception as error:
                errors.append({"source_id": futures[future], "error": str(error)[:2000]})
            if (len(entries) + len(errors)) % 50 == 0:
                print(json.dumps({"verified": len(entries), "failures": len(errors), "total": len(futures)}), flush=True)
    report = {"schema": "hepta.real-media-acquisition.v1", "dataset_sha256": sha(raw),
              "revision": ESC_REVISION, "workers": workers, "wall_ns": time.perf_counter_ns() - started,
              "entries": sorted(entries, key=lambda x: x["source_id"]), "errors": errors,
              "complete": not errors, "source_code_sha256": sha(Path(__file__).read_bytes())}
    if path.read_bytes() != raw:
        raise ValueError("cohort changed during acquisition")
    if errors:
        (root / ("failed-acquisition-" + str(time.time_ns()) + ".json")).write_bytes(canonical(report) + b"\n")
        raise ValueError("frozen audio cohort incomplete; failures retained, no selected row dropped")
    inventory_path.write_bytes(canonical(report) + b"\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--workers", type=int, default=4)
    report = acquire(**vars(parser.parse_args()))
    print(json.dumps({"complete": report["complete"], "objects": len(report["entries"]),
                      "total_bytes": sum(x["bytes"] for x in report["entries"]), "wall_ns": report["wall_ns"]}))
