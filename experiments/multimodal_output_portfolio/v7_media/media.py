"""Linux media profile: real files, lossless readback and shared clock checks."""

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

from .corpus import SAMPLE_RATE, WORD_SAMPLES, spectrum_waveform
from .models import AcousticDecoder, TemporalPixelDecoder, validate_probabilities, weights_sha256


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
              "-framerate", "10", "-i", "pipe:0", "-protocol_whitelist", "file,pipe",
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
    return {"schema": "hepta.ndu.four-modal-media.v1", "bindings": bindings,
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
    if len(video_times) != 20 or any(abs(timestamp - index / 10) > 1e-6 for index, timestamp in enumerate(video_times)):
        raise ValueError("Video frame clock does not match declared events")
    next_sample = 0
    for frame in audio_frames:
        if abs(float(frame["best_effort_timestamp_time"]) - next_sample / SAMPLE_RATE) > 1e-6:
            raise ValueError("Discontinuous mux audio sample clock")
        next_sample += int(frame["nb_samples"])
    if next_sample != 2 * WORD_SAMPLES or abs(float(audio_stream["duration"]) - 2) > 1e-6:
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
            "clock": {"duration_ns": 2_000_000_000, "sample_rate": SAMPLE_RATE,
                      "audio_samples": next_sample, "video_fps": 10, "video_frames": 20,
                      "events": [{"slot": 0, "audio_sample": 0, "video_frame": 0, "time_ns": 0},
                                 {"slot": 1, "audio_sample": 8000, "video_frame": 10, "time_ns": 1_000_000_000}]},
            "verification_wall_ns": time.perf_counter_ns() - started}


class FourModalRenderer:
    """Frozen learned media heads consuming current predicted semantic slots."""

    def __init__(self, acoustic_path, acoustic_sha256, video_path, video_sha256,
                 *, audio_backend="spectral_vae", video_backend="temporal_pixels"):
        started = time.perf_counter_ns()
        self.models = {}
        self.pins = {}
        self._parameter_pins = {}
        self.audio_backend = audio_backend
        self.video_backend = video_backend
        if video_backend == "temporal_pixels":
            video_model = TemporalPixelDecoder()
        elif video_backend == "conditioned_motion_v1":
            from .motion import ConditionedMotionDecoder
            video_model = ConditionedMotionDecoder()
        else:
            raise ValueError("Unregistered temporal decoder backend")
        checkpoints = [("video", video_path, video_sha256, video_model)]
        if audio_backend == "spectral_vae":
            checkpoints.append(("audio", acoustic_path, acoustic_sha256, AcousticDecoder()))
        elif audio_backend == "piper_libritts_v1":
            from .piper_decoder import PiperSemanticDecoder
            require_digest(acoustic_sha256)
            self.models["audio"] = PiperSemanticDecoder(acoustic_path, acoustic_sha256)
            self.pins["audio"] = {**file_pin(acoustic_path), "backend": audio_backend,
                                  "dependencies": self.models["audio"].pins}
        else:
            raise ValueError("Unregistered acoustic decoder backend")
        for name, path, expected, model in checkpoints:
            require_digest(expected)
            path = Path(path)
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 32_000_000:
                raise ValueError("Invalid media checkpoint path")
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError("Media checkpoint differs from caller pin")
            record = torch.load(path, map_location="cpu", weights_only=True)
            model.load_state_dict(record["state_dict"])
            if weights_sha256(model) != record["weights_sha256"]:
                raise ValueError("Media parameter identity mismatch")
            self.models[name] = model.eval().requires_grad_(False)
            self.pins[name] = file_pin(path)
            self._parameter_pins[name] = record["weights_sha256"]
        self.ffmpeg, self.ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
        if not self.ffmpeg or not self.ffprobe:
            raise RuntimeError("Actual ffmpeg and ffprobe are required")
        self.pins["ffmpeg"] = file_pin(self.ffmpeg)
        self.pins["ffprobe"] = file_pin(self.ffprobe)
        self.load_wall_ns = time.perf_counter_ns() - started

    def verify_integrity(self):
        for name, expected in self._parameter_pins.items():
            model = self.models[name]
            if model.training or any(parameter.requires_grad for parameter in model.parameters()) or weights_sha256(model) != expected:
                raise RuntimeError("Frozen media model parameters changed")
        if self.audio_backend == "piper_libritts_v1":
            self.models["audio"].verify_integrity()
        for pin in self.pins.values():
            if file_pin(pin["path"])["sha256"] != pin["sha256"]:
                raise RuntimeError("Frozen media checkpoint or codec binary changed")
        return self.pins

    def render(self, probabilities, decoded_text, decoded_image, output_dir, bindings, seed=17):
        validate_probabilities(probabilities, paired=True)
        if len(probabilities) != 1:
            raise ValueError("One owner request produces one bounded joint bundle")
        started, cpu = time.perf_counter_ns(), time.process_time_ns()
        children_before = resource.getrusage(resource.RUSAGE_CHILDREN)
        self.verify_integrity()
        integrity_ns = time.perf_counter_ns() - started
        condition = probabilities.detach().cpu().float().contiguous()
        with torch.inference_mode():
            if self.audio_backend == "spectral_vae":
                spectra = self.models["audio"].decode(condition.reshape(2, 10))
                waveform = spectrum_waveform(spectra, seed)
            else:
                waveform = self.models["audio"].waveform(condition.reshape(2, 10), seed)
            if self.video_backend == "conditioned_motion_v1":
                frames = self.models["video"](condition, decoded_image[None])[0].sigmoid()
            else:
                frames = self.models["video"](condition)[0].sigmoid()
        decode_ns = time.perf_counter_ns() - started - integrity_ns
        bindings = {**bindings, "semantic_probability_sha256": hashlib.sha256(condition.numpy().tobytes()).hexdigest(),
                    "media_checkpoint_pins": self.pins, "media_seed": seed,
                    "audio_backend": self.audio_backend, "video_backend": self.video_backend}
        result = write_media(output_dir, decoded_text, decoded_image, waveform, frames,
                             bindings, self.ffmpeg, self.ffprobe)
        children_after = resource.getrusage(resource.RUSAGE_CHILDREN)
        result["measurements"] = {"neural_decode_wall_ns": decode_ns,
                                  "integrity_wall_ns": integrity_ns,
                                  "full_media_wall_ns": time.perf_counter_ns() - started,
                                  "python_cpu_ns": time.process_time_ns() - cpu,
                                  "codec_child_cpu_ns": round((children_after.ru_utime + children_after.ru_stime
                                                               - children_before.ru_utime - children_before.ru_stime) * 1e9),
                                  "checkpoint_load_wall_ns_once": self.load_wall_ns}
        result["semantic_probabilities"] = condition.tolist()
        if self.audio_backend == "piper_libritts_v1":
            result["audio_decoding"] = self.models["audio"].last_metadata
        result["semantic_entropy_nats"] = (-(condition * condition.clamp_min(1e-12).log()).sum(-1)).tolist()
        return result
