"""Reproducible natural-input ingestion smoke; no model or generation scoring.

Downloads one public, explicitly licensed source clip (about 12 MB), extracts
its real audio, one frame and a four-frame temporal excerpt, and validates the
resulting tensors. Media derivatives retain CC BY-SA 4.0 attribution. The human
description is not an ASR transcript or a time-aligned caption benchmark.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time
import urllib.request
import wave

import numpy as np
from PIL import Image


SOURCE = {
    "title": "Lachender Hans (Tierpark Zittau).webm",
    "author": "Fiver, der Hellseher",
    "source_page": "https://commons.wikimedia.org/wiki/File:Lachender_Hans_(Tierpark_Zittau).webm",
    "source_page_revision": "https://commons.wikimedia.org/w/index.php?title=File:Lachender_Hans_(Tierpark_Zittau).webm&oldid=1138468463",
    "original_file_url": "https://upload.wikimedia.org/wikipedia/commons/5/5f/Lachender_Hans_%28Tierpark_Zittau%29.webm",
    "license": "CC-BY-SA-4.0",
    "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
    "source_creation_date": "2022-05-08",
    "source_declaration": "own work by the credited uploader",
    "expected_bytes": 12123649,
    "expected_sha1": "42b0f35d2c2f44197c97c6ce2686ed9fc7ca28d7",
    "caption_language": "de",
    "caption_provenance": "human-provided Description field on the pinned Commons file page",
    "caption_is_generated": False,
    "caption_is_time_aligned_transcript": False,
}
CAPTION = "Lachender Hans (Dacelo novaeguineae) im Tierpark Zittau"


def digest(path, algorithm="sha256"):
    result = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def download(path):
    if path.exists():
        return "existing_verified_original"
    partial = path.with_suffix(".part")
    request = urllib.request.Request(SOURCE["original_file_url"], headers={
        "User-Agent": "HEPTA-natural-input-ingestion-smoke/1.0 (licensed research fixture)"})
    count = 0
    with urllib.request.urlopen(request, timeout=30) as response, partial.open("wb") as target:
        for chunk in iter(lambda: response.read(1024 * 1024), b""):
            count += len(chunk)
            if count > 20 * 1024 * 1024:
                raise ValueError("source exceeds the declared 20 MiB download cap")
            target.write(chunk)
    partial.rename(path)
    return "downloaded_exact_public_original"


def run(command, commands, *, binary=False):
    started = time.perf_counter()
    result = subprocess.run(command, check=True, capture_output=True, timeout=120)
    commands.append({"argv": command, "wall_seconds": time.perf_counter() - started,
                     "returncode": result.returncode,
                     "stderr": result.stderr.decode("utf-8", errors="replace")[-4000:]})
    return result.stdout if binary else result.stdout.decode("utf-8")


def probe(path, commands):
    return json.loads(run(["ffprobe", "-v", "error", "-threads", "1", "-count_frames",
        "-show_entries", "stream=index,codec_type,codec_name,width,height,pix_fmt,sample_rate,channels,channel_layout,r_frame_rate,avg_frame_rate,time_base,start_time,duration,nb_frames,nb_read_frames:format=filename,format_name,start_time,duration,size,bit_rate",
        "-of", "json", str(path)], commands))


def stats(value):
    if value.size == 0 or not np.isfinite(value).all():
        raise ValueError("empty or nonfinite decoded tensor")
    return {"shape": list(value.shape), "dtype": str(value.dtype),
            "all_finite": True, "min": float(value.min()), "max": float(value.max()),
            "mean": float(value.mean()), "std": float(value.std())}


def ingest(output_directory, receipt_path=None):
    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report_file = output / "ingestion-receipt.json"
    if report_file.exists():
        raise FileExistsError("use a fresh output directory; retain earlier receipts")
    started = time.perf_counter()
    source = output / "original.webm"
    download_status = download(source)
    if source.stat().st_size != SOURCE["expected_bytes"] or digest(source, "sha1") != SOURCE["expected_sha1"]:
        raise ValueError("downloaded media does not match the pinned Commons original")
    commands = []
    original_probe = probe(source, commands)
    videos = [stream for stream in original_probe["streams"] if stream["codec_type"] == "video"]
    audios = [stream for stream in original_probe["streams"] if stream["codec_type"] == "audio"]
    if not videos or not audios or float(original_probe["format"]["duration"]) < 5:
        raise ValueError("source needs real nonempty video and audio tracks")
    audio_path, image_path, video_path = (output / name for name in
                                         ("recorded-audio-16khz.wav", "recorded-frame.png", "recorded-four-frames.webm"))
    run(["ffmpeg", "-v", "error", "-nostdin", "-threads", "1", "-i", str(source),
         "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio_path)], commands)
    run(["ffmpeg", "-v", "error", "-nostdin", "-threads", "1", "-ss", "2", "-i", str(source),
         "-map", "0:v:0", "-frames:v", "1", "-vf", "scale=256:-2", str(image_path)], commands)
    run(["ffmpeg", "-v", "error", "-nostdin", "-threads", "1", "-ss", "1", "-i", str(source),
         "-map", "0:v:0", "-an", "-t", "4", "-vf", "fps=1,scale=128:-2", "-frames:v", "4",
         "-c:v", "libvpx-vp9", "-threads", "1", "-b:v", "0", "-crf", "35", str(video_path)], commands)
    with wave.open(str(audio_path), "rb") as reader:
        audio_header = {"sample_rate": reader.getframerate(), "channels": reader.getnchannels(),
                        "sample_width_bytes": reader.getsampwidth(), "frames": reader.getnframes()}
        waveform = np.frombuffer(reader.readframes(reader.getnframes()), dtype="<i2").astype(np.float32) / 32768
    if audio_header["sample_rate"] != 16000 or audio_header["channels"] != 1 or waveform.std() == 0:
        raise ValueError("expected nonconstant real 16 kHz mono recording")
    waveform = waveform[None, :]
    with Image.open(image_path) as image:
        image_array = np.asarray(image.convert("RGB"), dtype=np.float32).transpose(2, 0, 1) / 255
    video_probe = probe(video_path, commands)
    stream = next(value for value in video_probe["streams"] if value["codec_type"] == "video")
    if int(stream["nb_read_frames"]) != 4:
        raise ValueError("temporal excerpt must contain exactly four decoded frames")
    raw_video = run(["ffmpeg", "-v", "error", "-nostdin", "-threads", "1", "-i", str(video_path),
                     "-map", "0:v:0", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], commands, binary=True)
    video = np.frombuffer(raw_video, dtype=np.uint8).reshape(4, stream["height"], stream["width"], 3)
    video_array = video.astype(np.float32).transpose(0, 3, 1, 2) / 255
    temporal_delta = float(np.abs(np.diff(video_array, axis=0)).mean())
    if temporal_delta == 0 or image_array.std() == 0:
        raise ValueError("recorded video must change over time and image must be nonconstant")
    caption_path = output / "human-description.de.txt"
    caption_path.write_text(CAPTION + "\n", encoding="utf-8")
    text = np.frombuffer(CAPTION.encode("utf-8"), dtype=np.uint8).copy()
    np.savez_compressed(output / "input-tensors.npz", audio=waveform, image=image_array,
                        video=video_array, text_utf8=text)
    attribution = {**SOURCE, "derivative_license": "CC-BY-SA-4.0",
                   "changes": ["audio resampled to 16 kHz mono PCM",
                               "frame extracted at 2 seconds and resized to width 256",
                               "original seconds 1 through 5 sampled to four temporal frames, resized to width 128, VP9 encoded without audio",
                               "original human German description copied without translation"],
                   "no_endorsement_implied": True}
    (output / "ATTRIBUTION.json").write_text(json.dumps(attribution, indent=2) + "\n")
    report = {
        "schema": "hepta.natural-input-ingestion-smoke.v1",
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "passed_input_ingestion_only", "source": SOURCE,
        "source_sha256": digest(source), "source_sha1_verified": digest(source, "sha1"),
        "download_status": download_status,
        "original_ffprobe": original_probe, "derived_four_frame_ffprobe": video_probe,
        "audio_pcm_header": audio_header,
        "input_tensors": {"human_description_utf8_bytes": stats(text), "recorded_audio": stats(waveform),
                          "recorded_frame": stats(image_array), "recorded_temporal_video": stats(video_array)},
        "video_mean_absolute_frame_difference": temporal_delta,
        "paired_provenance": {"audio_and_video": "same original captured recording",
                              "image": "one extracted natural-video frame, not independently captured still photography",
                              "text": "human file description, not generated text or timed speech transcript"},
        "artifacts": {name: {"path": str(output / name), "sha256": digest(output / name),
                             "bytes": (output / name).stat().st_size}
                      for name in (source.name, audio_path.name, image_path.name, video_path.name,
                                   caption_path.name, "input-tensors.npz", "ATTRIBUTION.json")},
        "commands": commands, "wall_seconds": time.perf_counter() - started,
        "source_code_sha256": digest(Path(__file__)),
        "scope": {"actual_natural_input_io": True, "four_independent_capture_modalities": False,
                  "pretrained_model_loaded": False, "neural_generation_performed": False,
                  "training_performed": False, "output_quality_evaluated": False,
                  "natural_foundation_model_blocker_closed": False,
                  "formal_v3_protocol_or_confirmation_changed": False},
    }
    payload = json.dumps(report, indent=2) + "\n"
    report_file.write_text(payload)
    if receipt_path is not None:
        receipt = Path(receipt_path)
        receipt.parent.mkdir(parents=True, exist_ok=True)
        with receipt.open("x") as target:
            target.write(payload)
    print(json.dumps({"status": report["status"], "receipt": str(report_file),
                      "source_sha256": report["source_sha256"],
                      "shapes": {name: value["shape"] for name, value in report["input_tensors"].items()},
                      "wall_seconds": report["wall_seconds"]}, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--receipt", help="optional small evidence JSON; existing evidence is never overwritten")
    arguments = parser.parse_args()
    ingest(arguments.output_directory, arguments.receipt)
