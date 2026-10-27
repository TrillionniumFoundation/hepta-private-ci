"""New source groups for the separately frozen two-model speech portfolio."""
import argparse
import json
from pathlib import Path
import subprocess
import urllib.parse

from .common import download, read, save, sha, verify_files


def run(previous, output, resume=False):
    source = Path(__file__).parent
    spec = read(source / "CASCADE_PROTOCOL.json")
    earlier = read(previous / "MANIFEST.json")
    verify_files(earlier["files"])
    used = set(earlier["excluded_historical_speakers"]) | set(earlier["fit_speakers"]) | set(earlier["test_speakers"])
    initially_excluded = sorted(used)
    if resume and (not output.exists() or (output / "MANIFEST.json").exists()):
        raise ValueError("Resume requires an incomplete existing source collection")
    output.mkdir(parents=True, exist_ok=resume)
    resumed = []

    def obtain(url, path, limit):
        if not (resume and path.exists()):
            return download(url, path, limit)
        if path.stat().st_size > limit or path.stat().st_size == 0:
            raise ValueError("Incomplete or oversized cached source")
        if path.suffix == ".json":
            read(path)
        elif path.suffix == ".flac":
            subprocess.run(["ffmpeg", "-v", "error", "-threads", "1", "-i", str(path), "-f", "null", "-"],
                check=True, capture_output=True)
        else:
            raise ValueError("Only completed metadata and audio are eligible for this source-fetch recovery")
        record = {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size,
            "source_url": url.split("?Expires=")[0]}
        resumed.append(record)
        return record
    rows = [{**row, "role": "train"} for row in earlier["speech"] if row["role"] == "fit"]
    files = [row for row in earlier["files"] if any(row["path"] == r["path"] for r in rows) or Path(row["path"]).parent == Path(earlier["model_directory"])]
    skipped = []
    for role, split, count in (("validation", "validation", 4), ("test", "test", 8)):
        for config in ("clean", "other"):
            chosen, collecting, offset = [], {}, 0
            while len(chosen) < count and offset < 4000:
                query = urllib.parse.urlencode({"dataset": spec["dataset"], "config": config,
                    "split": split, "offset": offset, "length": 100})
                metadata = output / "metadata" / f"{role}-{config}-{offset}.json"
                files.append(obtain("https://datasets-server.huggingface.co/rows?" + query, metadata, 4000000))
                batch = read(metadata)["rows"]
                if not batch:
                    break
                for item in batch:
                    row = item["row"]
                    speaker = row["speaker_id"]
                    if speaker in used or speaker in chosen:
                        continue
                    url = row["audio"][0]["src"]
                    if f"/--/{spec['dataset_revision']}/--/" not in url:
                        raise ValueError("Audio revision differs")
                    asset = obtain(url, output / "audio" / (row["id"] + ".flac"), 4000000)
                    files.append(asset)
                    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "json", asset["path"]], check=True, capture_output=True, text=True)
                    duration = float(json.loads(probe.stdout)["format"]["duration"])
                    if duration > 29:
                        skipped.append({"id": row["id"], "reason": "public_duration_limit", "duration": duration})
                        continue
                    collecting.setdefault(speaker, []).append({"id": row["id"], "speaker_id": speaker,
                        "chapter_id": row["chapter_id"], "reference": row["text"], "role": role,
                        "config": config, "split": split, "row_index": item["row_idx"], "duration": duration, **asset})
                    if len(collecting[speaker]) == 3:
                        rows.extend(collecting[speaker])
                        chosen.append(speaker)
                    if len(chosen) == count:
                        break
                offset += len(batch)
            if len(chosen) != count:
                raise ValueError("Insufficient new registered speaker groups")
            used.update(chosen)
            print({"role": role, "config": config, "speakers": chosen}, flush=True)
    for filename in ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt", "README.md"):
        url = f"https://huggingface.co/{spec['base_model']}/resolve/{spec['base_revision']}/{filename}"
        files.append(download(url, output / "base_model" / filename, 160000000))
    groups = {role: sorted({r["speaker_id"] for r in rows if r["role"] == role}) for role in ("train", "validation", "test")}
    if len(set(groups["train"]+groups["validation"]+groups["test"])) != sum(map(len, groups.values())):
        raise ValueError("Source speakers overlap")
    if set(groups["test"]) & set(initially_excluded):
        raise ValueError("Previously scored test speaker included")
    save(output / "MANIFEST.json", {"schema": "hepta.ndu.continuation.natural.cascade.assets.v1",
        "protocol_sha256": sha(source / "CASCADE_PROTOCOL.json"), "previous_manifest_sha256": sha(previous / "MANIFEST.json"),
        "groups": groups, "initially_excluded_speakers": initially_excluded, "speech": rows, "files": files,
        "skipped": skipped, "tiny_model_directory": earlier["model_directory"], "base_model_directory": str(output / "base_model")})
    save(output / "FETCH_RECOVERY.json", {"resumed": resume, "verified_cached_inputs": resumed,
        "source_order_and_protocol_unchanged": True, "heldout_model_execution_started": False})
    print({"rows": len(rows), "total_referenced_bytes": sum(r["bytes"] for r in files)}, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    run(args.previous, args.output, args.resume)
