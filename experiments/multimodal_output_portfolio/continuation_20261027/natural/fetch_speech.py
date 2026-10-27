"""Fetch fresh source-speaker groups before any new ASR output is generated."""
import argparse
import json
from pathlib import Path
import subprocess
import urllib.parse

from .common import download, read, save, sha


def run(output):
    source = Path(__file__).parent
    spec = read(source / "SPEECH_PROTOCOL.json")
    historical = source.parents[1] / "repair_20261026/natural/evidence/SOURCE_MANIFEST.json"
    prior = read(historical)
    excluded = set(prior["fit_speakers"]) | set(prior["test_speakers"])
    used = set(excluded)
    output.mkdir(parents=True, exist_ok=False)
    files, rows, skipped = [], [], []
    metadata = output / "dataset.json"
    files.append(download("https://huggingface.co/api/datasets/" + spec["dataset"], metadata, 2000000))
    if read(metadata)["sha"] != spec["dataset_revision"]:
        raise ValueError("Dataset revision moved")
    for role in ("fit", "test"):
        for config in ("clean", "other"):
            split = spec["selection"][role]["split"]
            count = spec["selection"][role][config + "_speakers"]
            chosen, collecting = [], {}
            offset = 0
            while len(chosen) < count and offset < 4000:
                query = urllib.parse.urlencode({"dataset": spec["dataset"], "config": config,
                    "split": split, "offset": offset, "length": 100})
                meta = output / "metadata" / f"{role}-{config}-{offset}.json"
                files.append(download("https://datasets-server.huggingface.co/rows?" + query, meta, 4000000))
                batch = read(meta)["rows"]
                if not batch:
                    break
                for item in batch:
                    row = item["row"]
                    speaker = row["speaker_id"]
                    if speaker in used or speaker in chosen:
                        continue
                    url = row["audio"][0]["src"]
                    if f"/--/{spec['dataset_revision']}/--/" not in url:
                        raise ValueError("Audio revision differs from pinned dataset")
                    asset = download(url, output / "audio" / (row["id"] + ".flac"), 4000000)
                    files.append(asset)
                    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "json", asset["path"]], check=True, capture_output=True, text=True)
                    duration = float(json.loads(probe.stdout)["format"]["duration"])
                    if duration > spec["selection"]["maximum_seconds"]:
                        skipped.append({"id": row["id"], "reason": "public_duration_limit", "seconds": duration})
                        continue
                    collecting.setdefault(speaker, []).append({"id": row["id"], "speaker_id": speaker,
                        "chapter_id": row["chapter_id"], "reference": row["text"], "role": role,
                        "config": config, "split": split, "row_index": item["row_idx"], "duration": duration, **asset})
                    if len(collecting[speaker]) == spec["selection"]["utterances_per_speaker"]:
                        rows.extend(collecting[speaker])
                        chosen.append(speaker)
                    if len(chosen) == count:
                        break
                offset += len(batch)
            if len(chosen) != count:
                raise ValueError("Insufficient prespecified new speaker groups")
            used.update(chosen)
            print(json.dumps({"role": role, "config": config, "speakers": chosen}), flush=True)
    for name in ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt", "README.md"):
        url = f"https://huggingface.co/{spec['model']}/resolve/{spec['model_revision']}/{name}"
        files.append(download(url, output / "model" / name, 85000000))
    fit = {r["speaker_id"] for r in rows if r["role"] == "fit"}
    test = {r["speaker_id"] for r in rows if r["role"] == "test"}
    if fit & test or (fit | test) & excluded or len({r["sha256"] for r in rows}) != len(rows):
        raise ValueError("Source groups or actual bytes overlap")
    save(output / "MANIFEST.json", {"schema": "hepta.ndu.natural.speech.assets.v1",
        "protocol_sha256": sha(source / "SPEECH_PROTOCOL.json"), "historical_manifest_sha256": sha(historical),
        "excluded_historical_speakers": sorted(excluded), "fit_speakers": sorted(fit), "test_speakers": sorted(test),
        "speech": rows, "files": files, "skipped": skipped, "model_directory": str(output / "model"),
        "upstream_pretraining_exposure_unknown": True})
    print(json.dumps({"rows": len(rows), "bytes": sum(r["bytes"] for r in files)}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
