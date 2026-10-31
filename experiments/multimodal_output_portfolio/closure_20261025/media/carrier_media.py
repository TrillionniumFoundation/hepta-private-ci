"""Explicit new four-second carrier profile, separate from all old two-second runs.

Codec validation is derived from the immutable v7_media implementation; neural
video still emits twenty distinct frames, now at five frames per second.
"""

import hashlib
import json
from pathlib import Path
import resource
import shutil
import subprocess
import time
import wave

import numpy as np
from PIL import Image
import torch

SAMPLE_RATE, WORD_SAMPLES = 8000, 16000
from ...v7_media.models import validate_probabilities


def file_pin(path):
    path = Path(path)
    return {"path": str(path), "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def require_digest(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("Expected an explicit lower-case SHA-256 identity")


def _command(arguments, stdin=None):
    process = subprocess.run(arguments, input=stdin, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, timeout=30, check=False)
    if process.returncode:
        raise RuntimeError(f"Media codec failed ({process.returncode}): {process.stderr[:2048]!r}")
    return process.stdout


def write_media(directory, caption, pixels, waveforms, frames, bindings, ffmpeg, ffprobe):
    """Preserve decoded content; encode losslessly and independently reopen it."""
    directory = Path(directory)
    if directory.exists():
        raise FileExistsError(directory)
    if not isinstance(caption, str) or len(caption.encode("utf-8")) > 4096:
        raise ValueError("Text output exceeds its byte limit")
    require_digest(bindings["request_sha256"])
    require_digest(bindings["state_sha256"])
    tensors = (pixels, waveforms, frames)
    if any(not torch.isfinite(value).all() for value in tensors):
        raise ValueError("Nonfinite decoded media")
    if tuple(pixels.shape) != (1, 28, 56) or tuple(waveforms.shape) != (2, WORD_SAMPLES):
        raise ValueError("Decoded image/audio shape mismatch")
    if tuple(frames.shape) != (20, 1, 28, 28):
        raise ValueError("Temporal decoder must provide twenty real frames")
    if any(value.min() < 0 or value.max() > 1 for value in (pixels, frames)):
        raise ValueError("Unbounded image/video decoder output")
    if waveforms.abs().max() > 1:
        raise ValueError("Unbounded waveform output")
    directory.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter_ns()
    caption_path = directory / "caption.txt"
    image_path = directory / "image.png"
    audio_path = directory / "audio.wav"
    video_path = directory / "video.mp4"
    caption_path.write_bytes(caption.encode("utf-8"))
    image = (pixels[0].detach().cpu().numpy() * 255).round().astype(np.uint8)
    Image.fromarray(image).save(image_path, format="PNG")
    audio = (waveforms.detach().cpu().numpy().reshape(-1) * 32767).round().astype("<i2")
    with wave.open(str(audio_path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(audio.tobytes())
    gray = (frames[:, 0].detach().cpu().numpy() * 255).round().astype(np.uint8)
    rgb = np.repeat(gray[:, :, :, None], 3, axis=-1)
    _command([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
              "-protocol_whitelist", "file,pipe", "-f", "rawvideo",
              "-pixel_format", "rgb24", "-video_size", "28x28",
              "-framerate", "5", "-i", "pipe:0", "-protocol_whitelist", "file,pipe",
              "-f", "wav", "-i", str(audio_path),
              "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264rgb",
              "-preset", "ultrafast", "-crf", "0", "-pix_fmt", "rgb24",
              "-threads", "1", "-c:a", "alac", "-ar", str(SAMPLE_RATE),
              "-video_track_timescale", "1000", "-frames:v", "20",
              "-map_metadata", "-1", str(video_path)], rgb.tobytes())
    encoded_ns = time.perf_counter_ns() - started
    paths = {"text": caption_path, "image": image_path, "audio": audio_path, "video": video_path}
    verified = read_media(paths, ffmpeg, ffprobe)
    if (verified["caption"] != caption or not np.array_equal(verified["image"], image)
            or verified["audio_bytes"] != audio.tobytes()
            or verified["mux_audio_bytes"] != audio.tobytes()
            or verified["video_bytes"] != rgb.tobytes()):
        raise ValueError("Lossless media roundtrip changed the decoder's bytes")
    return {"schema": "hepta.closure.four-second-carrier-media.v1", "bindings": bindings,
            "required_modalities": ["text", "image", "audio", "video"],
            "files": {name: file_pin(path) for name, path in paths.items()},
            "clock": verified["clock"], "all_required_complete": True,
            "lossless_roundtrip": True, "codec_wall_ns": encoded_ns,
            "verification_wall_ns": verified["verification_wall_ns"],
            "authority": "deny_all"}


def read_media(paths, ffmpeg=None, ffprobe=None):
    """Reparse the actual files and time bases; declared manifest scores are unused."""
    ffmpeg = ffmpeg or shutil.which("ffmpeg")
    ffprobe = ffprobe or shutil.which("ffprobe")
    if not ffmpeg or not ffprobe or set(paths) != {"text", "image", "audio", "video"}:
        raise ValueError("Four actual modalities and codec tools are required")
    started = time.perf_counter_ns()
    paths = {name: Path(path) for name, path in paths.items()}
    for name, path in paths.items():
        if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 4_000_000:
            raise ValueError(f"Invalid actual {name} file")
    caption = paths["text"].read_text(encoding="utf-8")
    if len(caption.encode("utf-8")) > 4096:
        raise ValueError("Text output bound exceeded")
    with Image.open(paths["image"]) as source:
        if source.format != "PNG" or source.mode != "L" or source.size != (56, 28):
            raise ValueError("Joint image profile mismatch")
        image = np.array(source, copy=True)
    with wave.open(str(paths["audio"]), "rb") as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate(), source.getnframes()) != (1, 2, SAMPLE_RATE, 2 * WORD_SAMPLES):
            raise ValueError("Waveform profile or sample clock mismatch")
        audio_bytes = source.readframes(source.getnframes())
    info = json.loads(_command([ffprobe, "-v", "error", "-protocol_whitelist", "file,pipe",
                                "-f", "mov", "-show_streams", "-show_frames",
                                "-show_entries", "stream=index,codec_type,codec_name,width,height,sample_rate,time_base,start_time,duration,nb_frames:frame=media_type,best_effort_timestamp_time,nb_samples",
                                "-of", "json", str(paths["video"])]))
    streams = {item["codec_type"]: item for item in info["streams"]}
    if set(streams) != {"audio", "video"}:
        raise ValueError("Video must carry actual image and audio streams")
    video_stream, audio_stream = streams["video"], streams["audio"]
    if (video_stream["codec_name"], video_stream["width"], video_stream["height"],
            audio_stream["codec_name"], int(audio_stream["sample_rate"])) != ("h264", 28, 28, "alac", SAMPLE_RATE):
        raise ValueError("Unexpected lossless codec profile")
    video_times = [float(frame["best_effort_timestamp_time"]) for frame in info["frames"] if frame["media_type"] == "video"]
    audio_frames = [frame for frame in info["frames"] if frame["media_type"] == "audio"]
    if len(video_times) != 20 or any(abs(timestamp - index / 5) > 1e-6 for index, timestamp in enumerate(video_times)):
        raise ValueError("Video frame clock does not match declared events")
    next_sample = 0
    for frame in audio_frames:
        if abs(float(frame["best_effort_timestamp_time"]) - next_sample / SAMPLE_RATE) > 1e-6:
            raise ValueError("Discontinuous mux audio sample clock")
        next_sample += int(frame["nb_samples"])
    if next_sample != 2 * WORD_SAMPLES or abs(float(audio_stream["duration"]) - 4) > 1e-6:
        raise ValueError("Muxed audio duration mismatch")
    video_bytes = _command([ffmpeg, "-v", "error", "-nostdin", "-protocol_whitelist", "file,pipe",
                            "-f", "mov", "-i", str(paths["video"]),
                            "-map", "0:v:0", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"])
    mux_audio_bytes = _command([ffmpeg, "-v", "error", "-nostdin", "-protocol_whitelist", "file,pipe",
                                "-f", "mov", "-i", str(paths["video"]),
                                "-map", "0:a:0", "-f", "s16le", "-acodec", "pcm_s16le", "pipe:1"])
    if len(video_bytes) != 20 * 28 * 28 * 3 or mux_audio_bytes != audio_bytes:
        raise ValueError("Actual decoded media byte census mismatch")
    return {"caption": caption, "image": image, "audio_bytes": audio_bytes,
            "mux_audio_bytes": mux_audio_bytes, "video_bytes": video_bytes,
            "clock": {"duration_ns": 4_000_000_000, "sample_rate": SAMPLE_RATE,
                      "audio_samples": next_sample, "video_fps": 5, "video_frames": 20,
                      "events": [{"slot": 0, "audio_sample": 0, "video_frame": 0, "time_ns": 0},
                                 {"slot": 1, "audio_sample": 16000, "video_frame": 10, "time_ns": 2_000_000_000}]},
            "verification_wall_ns": time.perf_counter_ns() - started}


def content_checks(decoded, minimum_frames):
    audio = np.frombuffer(decoded["audio_bytes"], dtype="<i2").reshape(2, WORD_SAMPLES).astype(np.float64) / 32768
    frames = np.frombuffer(decoded["video_bytes"], dtype=np.uint8).reshape(20, 28, 28, 3)
    rms = np.sqrt(np.mean(audio * audio, 1)).tolist()
    distinct = [len({frame.tobytes() for frame in block}) for block in (frames[:10], frames[10:])]
    return {"audio_rms": rms, "distinct_frames_per_event": distinct,
            "nonempty_audio": min(rms) > 1e-4, "moving_video": min(distinct) >= minimum_frames}


def observe_four_modal_bundle(paths, image_observer, speech_observer, expected_labels):
    from ...v6.observer import CAPTION
    started = time.perf_counter_ns()
    labels = torch.as_tensor(expected_labels, dtype=torch.long).reshape(-1)
    if labels.shape != (2,) or (labels < 0).any() or (labels > 9).any():
        raise ValueError("Offline expected semantics must contain two digit labels")
    decoded = read_media(paths)
    pixels = torch.from_numpy(decoded["image"].copy()).float() / 255
    panels = torch.stack((pixels[:, :28], pixels[:, 28:]))[:, None]
    rgb = np.frombuffer(decoded["video_bytes"], dtype=np.uint8).reshape(20, 28, 28, 3)
    if not np.array_equal(rgb[..., 0], rgb[..., 1]) or not np.array_equal(rgb[..., 0], rgb[..., 2]):
        raise ValueError("Carrier video profile requires actual grayscale frames")
    frames = torch.from_numpy(rgb[..., 0].copy()).float()[:, None] / 255
    with torch.inference_mode():
        image_digits = image_observer(panels).argmax(-1)
        video_digits = image_observer(frames).argmax(-1)
    audio_digits = torch.tensor(speech_observer.predict_pcm16(decoded["audio_bytes"]))
    external_audit = speech_observer.last_observation
    caption = CAPTION.fullmatch(decoded["caption"].strip())
    expected = labels.tolist()
    relation = "less" if expected[0] < expected[1] else "greater" if expected[0] > expected[1] else "equal"
    caption_digits = [int(caption[1]), int(caption[2])] if caption else None
    success = {"text": bool(caption and caption_digits == expected and caption[3] == relation),
               "image": torch.equal(image_digits, labels), "audio": torch.equal(audio_digits, labels),
               "video": torch.equal(video_digits, labels.repeat_interleave(10))}
    return {"schema": "hepta.closure.carrier-four-modal-observation.v1", "success": success,
            "joint_success": all(success.values()), "strict_completion": True,
            "expected_labels": expected, "caption_digits": caption_digits,
            "image_digits": image_digits.tolist(), "audio_digits": audio_digits.tolist(),
            "video_digits": video_digits.tolist(), "clock": decoded["clock"],
            "external_waveform_audit": external_audit, "audit_wall_ns": time.perf_counter_ns() - started,
            "scope": "Actual four-second PCM observed without targets by frozen Vosk and Whisper; actual container event alignment"}

