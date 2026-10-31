"""Stream the official public archive and restore only registered new WAVs."""

import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import time
import urllib.request

from .sources import sha


class HashedReader:
    def __init__(self, source):
        self.source = source
        self.digest = hashlib.sha256()
        self.bytes_read = 0
        self.next_report = 256 * 1024 * 1024

    def read(self, size=-1):
        value = self.source.read(size)
        self.digest.update(value)
        self.bytes_read += len(value)
        if self.bytes_read >= self.next_report:
            print(json.dumps({"official_archive_bytes_streamed": self.bytes_read}), flush=True)
            self.next_report += 256 * 1024 * 1024
        return value


def restore(allocation, metadata_root, output, receipt):
    spec = json.loads(Path(allocation).read_text())
    output, receipt, metadata_root = Path(output), Path(receipt), Path(metadata_root)
    if receipt.exists() or sha(metadata_root / "manifest.json") != spec["audio_manifest_sha256"]:
        raise ValueError("Receipt already exists or original metadata identity changed")
    selected = {}
    for name, role in spec["roles"].items():
        for row in role.get("audio_rows_by_source_digit", role.get("recordings", [])):
            if row["path"] in selected and selected[row["path"]] != row:
                raise ValueError("Conflicting selected recording identities")
            selected[row["path"]] = row
    if len({row["sha256"] for row in selected.values()}) != len(selected):
        raise ValueError("Selected WAV identities unexpectedly duplicate")
    output.mkdir(parents=True, exist_ok=True)
    start = time.time_ns(); restored = []; reused = []
    result = {"schema": "hepta.advance.official-source-restore.v1", "started_unix_ns": start,
              "allocation_sha256": sha(allocation), "source_url": spec["audio_source_url"],
              "expected_whole_archive_sha256": spec["audio_whole_archive_sha256"],
              "selected_unique_wavs": len(selected), "output": str(output.resolve()),
              "model_or_audio_scoring_executed": False}
    stream = None
    try:
        request = urllib.request.Request(spec["audio_source_url"], headers={"User-Agent": "Hepta-research-source-restoration/1.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            stream = HashedReader(response)
            with tarfile.open(fileobj=stream, mode="r|gz", bufsize=1024 * 1024) as archive:
                for member in archive:
                    name = member.name[2:] if member.name.startswith("./") else member.name
                    if name not in selected:
                        continue
                    row = selected[name]
                    if not member.isfile() or member.size != row["bytes"] or member.size > 100000:
                        raise ValueError("Expected selected finite PCM source file")
                    payload = archive.extractfile(member).read()
                    if hashlib.sha256(payload).hexdigest() != row["sha256"]:
                        raise ValueError("Official selected recording hash differs: " + name)
                    path = output / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    if path.exists():
                        if sha(path) != row["sha256"]:
                            raise ValueError("Refuse to overwrite a different restored recording")
                        reused.append(name)
                    else:
                        with path.open("xb") as destination:
                            destination.write(payload)
                        restored.append(name)
            while stream.read(1024 * 1024):
                pass
        if stream.digest.hexdigest() != spec["audio_whole_archive_sha256"]:
            raise ValueError("Whole official source archive checksum differs")
        if set(restored + reused) != set(selected):
            raise ValueError("Official archive did not provide every registered WAV")
        for name, row in selected.items():
            path = output / name
            if path.stat().st_size != row["bytes"] or sha(path) != row["sha256"]:
                raise ValueError("Restored recording changed after write")
        for name in ("manifest.json", "LICENSE", "README.md", "testing_list.txt", "validation_list.txt"):
            data = (metadata_root / name).read_bytes(); target = output / name
            if target.exists() and target.read_bytes() != data:
                raise ValueError("Existing metadata differs")
            if not target.exists():
                target.write_bytes(data)
        result["status"] = "passed"
    except Exception as error:
        result.update({"status": "failed", "error_type": type(error).__name__, "error": str(error)})
        raise
    finally:
        result.update({"finished_unix_ns": time.time_ns(), "restored": restored, "reused": reused,
                       "actual_archive_bytes_read": stream.bytes_read if stream else 0,
                       "actual_archive_sha256": stream.digest.hexdigest() if stream else None,
                       "whole_archive_stored": False, "only_selected_files_written": True})
        receipt.parent.mkdir(parents=True, exist_ok=True)
        with receipt.open("x") as destination:
            json.dump(result, destination, indent=2, sort_keys=True); destination.write("\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("allocation", "metadata-root", "output", "receipt"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    result = restore(args.allocation, args.metadata_root, args.output, args.receipt)
    print(json.dumps({k: result[k] for k in ("status", "selected_unique_wavs", "actual_archive_bytes_read", "actual_archive_sha256")}))
