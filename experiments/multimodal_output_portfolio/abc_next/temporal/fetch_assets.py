"""Fetch bounded public Piper/Vosk assets, preserving content identities.

This preparation emits no private data. No model archive is added to Git.
"""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import stat
import time
import urllib.request
import zipfile


PIPER_REVISION = "5041a7a49ae5b3a0f30e6837769eb03fdbb231bd"
VOICE_DIRECTORY = "en/en_US/ljspeech/medium"
VOICE = "en_US-ljspeech-medium"
VOSK_NAME = "vosk-model-small-en-us-0.15"
FILES = {
    f"{VOICE}.onnx": f"https://huggingface.co/rhasspy/piper-voices/resolve/{PIPER_REVISION}/{VOICE_DIRECTORY}/{VOICE}.onnx",
    f"{VOICE}.onnx.json": f"https://huggingface.co/rhasspy/piper-voices/resolve/{PIPER_REVISION}/{VOICE_DIRECTORY}/{VOICE}.onnx.json",
    "PIPER_MODEL_CARD": f"https://huggingface.co/rhasspy/piper-voices/resolve/{PIPER_REVISION}/{VOICE_DIRECTORY}/MODEL_CARD",
    f"{VOSK_NAME}.zip": f"https://alphacephei.com/vosk/models/{VOSK_NAME}.zip",
}


def download(url, path, maximum_bytes):
    checksum, transferred = hashlib.sha256(), 0
    with urllib.request.urlopen(url, timeout=60) as response, path.open("xb") as stream:
        status = response.status
        while block := response.read(1024 * 1024):
            transferred += len(block)
            if transferred > maximum_bytes:
                raise ValueError(f"Public asset exceeds bound: {path.name}")
            checksum.update(block)
            stream.write(block)
    return {"url": url, "path": path.name, "sha256": checksum.hexdigest(),
            "bytes": transferred, "http_status": status}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    rows = []
    metadata_url = f"https://huggingface.co/api/models/rhasspy/piper-voices/tree/{PIPER_REVISION}/{VOICE_DIRECTORY}"
    metadata_path = args.output / "piper-file-metadata.json"
    rows.append(download(metadata_url, metadata_path, 2_000_000))
    metadata = json.loads(metadata_path.read_text())
    onnx_record = next(row for row in metadata if row["path"].endswith(f"/{VOICE}.onnx"))
    expected_onnx = onnx_record["lfs"]["oid"]
    for name, url in FILES.items():
        row = download(url, args.output / name, 90_000_000)
        if name.endswith(".onnx") and row["sha256"] != expected_onnx:
            raise ValueError("Piper ONNX does not match its pinned LFS identity")
        rows.append(row)
    extracted = []
    with zipfile.ZipFile(args.output / f"{VOSK_NAME}.zip") as archive:
        if len(archive.infolist()) > 100 or sum(row.file_size for row in archive.infolist()) > 100_000_000:
            raise ValueError("Vosk expanded asset census exceeds bound")
        for row in archive.infolist():
            path = Path(row.filename)
            mode = row.external_attr >> 16
            if path.is_absolute() or ".." in path.parts or path.parts[0] != VOSK_NAME or stat.S_ISLNK(mode):
                raise ValueError("Unsafe public archive member")
            target = args.output / path
            if row.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            payload = archive.read(row)
            with target.open("xb") as stream:
                stream.write(payload)
            extracted.append({"path": str(path), "bytes": len(payload),
                              "sha256": hashlib.sha256(payload).hexdigest()})
    manifest = {"schema": "hepta.abc3.public-text-speech-assets.v1",
                "voice": VOICE, "voice_repository_revision": PIPER_REVISION,
                "voice_dataset_license_from_model_card": "public domain LJ Speech dataset",
                "piper_runtime_license": "GPL-3.0-or-later", "vosk_model_license": "Apache-2.0",
                "sources": rows, "extracted_vosk_files": extracted,
                "packages": {name: importlib.metadata.version(name) for name in
                             ("piper-tts", "vosk", "onnxruntime", "numpy", "scipy")},
                "downloaded_bytes": sum(row["bytes"] for row in rows),
                "wall_ns_before_report": time.perf_counter_ns() - started,
                "cpu_ns_before_report": time.process_time_ns() - cpu,
                "preparation_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    payload = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    (args.output / "manifest.json").write_bytes(payload)
    print(json.dumps({"status": "complete", "manifest_sha256": hashlib.sha256(payload).hexdigest(),
                      "downloaded_bytes": manifest["downloaded_bytes"], "voice_sha256": expected_onnx,
                      "expanded_vosk_bytes": sum(row["bytes"] for row in extracted)}))


if __name__ == "__main__":
    main()
