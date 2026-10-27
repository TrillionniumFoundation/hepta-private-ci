"""Collect untouched LibriSpeech speakers with bounded, logged public requests."""
import argparse
import json
from pathlib import Path
import subprocess
import time
import urllib.parse
import urllib.request

from .common import read, save, sha


def obtain(url, path, limit, attempts):
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(4):
        temporary = path.with_name(path.name + f".attempt-{attempt}.partial")
        if temporary.exists() or path.exists():
            raise FileExistsError("Fresh source collection refuses overwrite")
        try:
            with urllib.request.urlopen(url, timeout=60) as response, temporary.open("xb") as stream:
                received = 0
                while block := response.read(1024 * 1024):
                    received += len(block)
                    if received > limit:
                        raise ValueError("Source exceeds bounded size")
                    stream.write(block)
                expected = response.headers.get("Content-Length")
                if expected and received != int(expected):
                    raise ValueError("Truncated public response")
            temporary.rename(path)
            return {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size,
                "source_url": url.split("?Expires=")[0]}
        except Exception as error:
            attempts.append({"path": str(path), "attempt": attempt,
                "error": type(error).__name__ + ": " + str(error), "partial_bytes_retained": temporary.exists()})
            if attempt == 3:
                raise
            time.sleep(3 * (attempt + 1))


def run(previous, output):
    source = Path(__file__).parent
    spec = read(source / "SPEECH_PROTOCOL.json")
    prior = read(previous / "MANIFEST.json")
    excluded = set(prior["initially_excluded_speakers"])
    for group in prior["groups"].values():
        excluded.update(group)
    used, files, speech, attempts, skipped = set(excluded), [], [], [], []
    previous_hashes = {r["sha256"] for r in prior["speech"]}
    output.mkdir(parents=True, exist_ok=False)
    try:
        for config in ("clean", "other"):
            selected, collecting, offset = [], {}, 0
            while len(selected) < spec["test_speakers_each_config"] and offset < 5000:
                query = urllib.parse.urlencode({"dataset": spec["dataset"], "config": config,
                    "split": "test", "offset": offset, "length": 100})
                metadata = output / "metadata" / f"test-{config}-{offset}.json"
                files.append(obtain("https://datasets-server.huggingface.co/rows?" + query, metadata, 5000000, attempts))
                batch = read(metadata)["rows"]
                if not batch:
                    break
                for item in batch:
                    row = item["row"]
                    speaker = row["speaker_id"]
                    if speaker in used or speaker in selected:
                        continue
                    url = row["audio"][0]["src"]
                    if f"/--/{spec['dataset_revision']}/--/" not in url:
                        raise ValueError("Speech dataset revision differs")
                    asset = obtain(url, output / "audio" / (row["id"] + ".flac"), 5000000, attempts)
                    if asset["sha256"] in previous_hashes:
                        raise ValueError("New source repeats an earlier waveform")
                    files.append(asset)
                    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", asset["path"]],
                        check=True, capture_output=True, text=True)
                    duration = float(json.loads(probe.stdout)["format"]["duration"])
                    if duration > 29:
                        skipped.append({"id": row["id"], "reason": "public_duration_limit", "duration": duration})
                        continue
                    collecting.setdefault(speaker, []).append({"id": row["id"], "speaker_id": speaker,
                        "chapter_id": row["chapter_id"], "reference": row["text"], "role": "test", "config": config,
                        "row_index": item["row_idx"], "duration": duration, **asset})
                    if len(collecting[speaker]) == spec["utterances_per_speaker"]:
                        speech.extend(collecting[speaker])
                        selected.append(speaker)
                    if len(selected) == spec["test_speakers_each_config"]:
                        break
                offset += len(batch)
            if len(selected) != spec["test_speakers_each_config"]:
                raise ValueError("Insufficient untouched speech sources")
            used.update(selected)
            print({"config": config, "new_speakers": selected}, flush=True)
        if len({r["sha256"] for r in speech}) != len(speech):
            raise ValueError("Duplicate fresh audio content")
        save(output / "MANIFEST.json", {"schema": "hepta.ndu.closure-v2.natural.speech.assets.v1",
            "protocol_sha256": sha(source / "SPEECH_PROTOCOL.json"), "previous_manifest_sha256": sha(previous / "MANIFEST.json"),
            "excluded_speakers": sorted(excluded), "speech": speech, "files": files, "skipped": skipped,
            "test_speakers": sorted({r["speaker_id"] for r in speech}), "model_directory": prior["base_model_directory"]})
    finally:
        save(output / "FETCH_ATTEMPTS.json", attempts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.previous, args.output)
