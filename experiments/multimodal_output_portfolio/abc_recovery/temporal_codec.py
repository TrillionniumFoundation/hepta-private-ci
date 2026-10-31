"""Append-only real AV commits, lossless Matroska output, and independent readback.

Virtual delivery time belongs to the commit ledger. Output media PTS keep the
source media clock; a successful file does not measure a live network or lip sync.
"""

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import numpy as np

from .temporal_sources import digest, elapsed, ledger, save, save_json, usage
from .temporal_transport import FRAME_TICKS, RATE


def command(argv, directory, name, retain_stdout=False):
    before = usage()
    row = {"argv": argv}
    try:
        result = subprocess.run(argv, capture_output=True, timeout=120, check=False)
        row.update(returncode=result.returncode, stdout_bytes=len(result.stdout), stdout_sha256=digest(result.stdout),
                   stderr_sha256=save(Path(directory) / (name + ".stderr"), result.stderr))
        if retain_stdout:
            save(Path(directory) / (name + ".stdout"), result.stdout)
        if result.returncode:
            raise RuntimeError(f"Media command failed ({name}, exit {result.returncode})")
        return result.stdout
    except BaseException as error:
        row["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        row["cost"] = elapsed(before)
        save_json(Path(directory) / (name + ".receipt.json"), row)


@dataclass(frozen=True)
class Reference:
    source_id: str
    width: int
    height: int
    frames: np.ndarray
    audio: np.ndarray
    video_pts: tuple
    audio_start_pts: float = 0.0
    audio_clock_max_error_seconds: float = 0.0

    @property
    def frame_bytes(self):
        return self.width * self.height * 3 // 2

    def audio_slice(self, index):
        return self.audio[index * FRAME_TICKS:min((index + 1) * FRAME_TICKS, len(self.audio))]


def decode(path, width, height, directory, name):
    ffmpeg = shutil.which("ffmpeg")
    common = [ffmpeg, "-nostdin", "-v", "error", "-threads", "1", "-protocol_whitelist", "file,pipe", "-i", str(path)]
    video = command(common + ["-map", "0:v:0", "-an", "-sn", "-dn", "-fps_mode", "passthrough",
                              "-pix_fmt", "yuv420p", "-f", "rawvideo", "pipe:1"], directory, name + "-video")
    audio = command(common + ["-map", "0:a:0", "-vn", "-sn", "-dn", "-acodec", "pcm_s16le",
                              "-f", "s16le", "pipe:1"], directory, name + "-audio")
    pixels = np.frombuffer(video, dtype=np.uint8).reshape(-1, width * height * 3 // 2)
    pcm = np.frombuffer(audio, dtype="<i2").reshape(-1, 2)
    return pixels, pcm


def audio_timeline(frames, time_base=None):
    pts = [float(row["pts"] * time_base) if time_base is not None else
           float(row.get("pts_time", row.get("best_effort_timestamp_time"))) for row in frames]
    if not pts:
        raise ValueError("Missing actual decoded audio packet clock")
    offset, maximum = 0, 0.0
    for row, timestamp in zip(frames, pts):
        maximum = max(maximum, abs(timestamp - pts[0] - offset / RATE))
        offset += row["nb_samples"]
    return pts[0], maximum, offset


def load_reference(source_root, source, output):
    before, output = usage(), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    sample = Path(source_root) / "originals" / f"s{source['speaker']}"
    original = sample / "original.mpg"
    if digest(original.read_bytes()) != source["video_sha256"]:
        raise ValueError("Registered original AV source bytes changed")
    inventory = json.loads((sample / "source-inventory.json").read_bytes())
    video = next(stream for stream in inventory["format_inventory"]["streams"] if stream["codec_type"] == "video")
    pts = tuple(map(float, inventory["format_inventory"]["actual_clocks"]["video"]["pts_seconds"]))
    frames, audio = decode(original, video["width"], video["height"], output, "source")
    audio_probe = json.loads(command([shutil.which("ffprobe"), "-v", "error", "-select_streams", "a:0",
        "-show_frames", "-show_streams", "-of", "json", str(original)], output, "source-audio-clock", retain_stdout=True))
    stream = audio_probe["streams"][0]
    source_tick = Fraction(stream["time_base"])
    origin, clock_error, counted_samples = audio_timeline(audio_probe["frames"], source_tick)
    # Differences of two rounded PTS may differ by one whole container tick.
    if (origin != 0.0 or clock_error > float(source_tick) + 1e-12 or counted_samples != len(audio)
            or int(stream["sample_rate"]) != RATE or stream["channels"] != 2):
        raise ValueError("Original audio clock must start at zero and be continuous at the registered stereo sample rate")
    if (len(frames) != 75 or len(audio) != 131328 or pts != tuple(index * .04 for index in range(75))):
        if len(frames) != 75 or len(audio) != 131328 or not np.allclose(pts, np.arange(75) * .04, atol=1e-9):
            raise ValueError("Decoded source census or actual media PTS changed")
    reference = Reference(source["source_id"], video["width"], video["height"], frames, audio, pts, origin, clock_error)
    save_json(output / "reference.json", {"source_id": source["source_id"], "original_sha256": source["video_sha256"],
              "video_pts": pts, "video_frame_sha256": [digest(frame.tobytes()) for frame in frames],
              "audio_packet_sha256": [digest(reference.audio_slice(i).tobytes()) for i in range(len(frames))],
              "audio_samples_per_channel": len(audio), "audio_start_pts": origin,
              "source_audio_time_base": str(source_tick),
              "source_audio_clock_tolerance_seconds": float(source_tick),
              "source_audio_clock_max_error_seconds": clock_error,
              "source_audio_clock_probe_sha256": digest((output / "source-audio-clock.stdout").read_bytes()),
              "source_setup_cost": elapsed(before)})
    return reference


class CommitSink:
    """Materialize each irreversible prefix before accepting its successor."""

    def __init__(self, reference, directory):
        self.reference, self.directory = reference, Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.temporary = Path(tempfile.mkdtemp(prefix="committed-raw-", dir=self.directory))
        self.video_path, self.audio_path = self.temporary / "video.yuv", self.temporary / "audio.pcm"
        self.video, self.audio = self.video_path.open("xb"), self.audio_path.open("xb")
        self.records, self.chain = [], "0" * 64
        black = np.full(reference.frame_bytes, 128, dtype=np.uint8)
        black[:reference.width * reference.height] = 16
        self.black = black.tobytes()

    def commit(self, index, delivered, commit_ticks):
        if index != len(self.records):
            raise ValueError("Committed prefix cannot be rewritten, reordered or skipped")
        source_video = self.reference.frames[index].tobytes()
        source_audio = self.reference.audio_slice(index).tobytes()
        video = source_video if delivered["video"] else self.black
        audio = source_audio if delivered["audio"] else bytes(len(source_audio))
        self.video.write(video)
        self.audio.write(audio)
        for stream in (self.video, self.audio):
            stream.flush()
            os.fsync(stream.fileno())
        row = {"index": index, "virtual_commit_ticks": commit_ticks, "delivered": dict(delivered),
               "source_video_sha256": digest(source_video), "source_audio_sha256": digest(source_audio),
               "written_video_sha256": digest(video), "written_audio_sha256": digest(audio),
               "video_bytes": len(video), "audio_bytes": len(audio), "previous_prefix_sha256": self.chain}
        self.chain = digest(self.chain.encode() + json.dumps(row, sort_keys=True).encode())
        row["prefix_sha256"] = self.chain
        ledger(self.directory / "commits.jsonl", row)
        self.records.append(row)

    def finish(self, relative_audio_delay_ms=0):
        if len(self.records) != len(self.reference.frames):
            raise ValueError("No terminal truncation: every registered source slot must be committed")
        self.video.close()
        self.audio.close()
        ref = self.reference
        video_delay, audio_delay = max(0, -relative_audio_delay_ms) / 1000, max(0, relative_audio_delay_ms) / 1000
        result = self.directory / "output.mkv"
        argv = [shutil.which("ffmpeg"), "-nostdin", "-v", "error", "-n", "-copyts",
                "-f", "rawvideo", "-pixel_format", "yuv420p", "-video_size", f"{ref.width}x{ref.height}",
                "-framerate", "25", "-itsoffset", str(video_delay), "-i", str(self.video_path),
                "-f", "s16le", "-ar", str(RATE), "-ac", "2", "-itsoffset", str(audio_delay), "-i", str(self.audio_path),
                "-map", "0:v:0", "-map", "1:a:0", "-c:v", "ffv1", "-level", "3", "-coder", "1",
                "-context", "1", "-g", "1", "-threads", "1", "-c:a", "pcm_s16le", "-fps_mode", "passthrough",
                "-avoid_negative_ts", "disabled", "-f", "matroska", str(result)]
        command(argv, self.directory, "mux")
        with result.open("rb") as stream:
            os.fsync(stream.fileno())
        return result

    def cleanup(self, verified=True):
        for stream in (self.video, self.audio):
            if not stream.closed:
                stream.close()
        if verified:
            shutil.rmtree(self.temporary)


def observe_output(path, reference, records, directory):
    """Read real bytes and clocks; source coverage comes from immutable delivery records."""
    before = usage()
    probe = json.loads(command([shutil.which("ffprobe"), "-v", "error", "-show_frames", "-show_streams",
                                "-of", "json", str(path)], directory, "readback-probe", retain_stdout=True))
    video, audio = decode(path, reference.width, reference.height, directory, "readback")
    video_frames = [row for row in probe["frames"] if row["media_type"] == "video"]
    audio_frames = [row for row in probe["frames"] if row["media_type"] == "audio"]
    if len(video) != len(records) or len(video_frames) != len(records) or len(audio) != len(reference.audio):
        raise ValueError("Actual decoded output lost source slots or audio samples")
    video_hashes = [digest(frame.tobytes()) for frame in video]
    audio_hashes = [digest(audio[i * FRAME_TICKS:min((i + 1) * FRAME_TICKS, len(audio))].tobytes()) for i in range(len(records))]
    fidelity = (video_hashes == [row["written_video_sha256"] for row in records]
                and audio_hashes == [row["written_audio_sha256"] for row in records])
    video_pts = np.array([float(row.get("pts_time", row.get("best_effort_timestamp_time"))) for row in video_frames])
    audio_pts = [float(row.get("pts_time", row.get("best_effort_timestamp_time"))) for row in audio_frames]
    audio_start, audio_clock_error, offset = audio_timeline(audio_frames)
    if offset != len(audio) or audio_clock_error > .001001:
        raise ValueError("Decoded audio packet clock is discontinuous")
    paired = np.array([row["delivered"]["video"] and row["delivered"]["audio"] for row in records])
    signed = audio_start - reference.audio_start_pts + np.array(reference.video_pts) - video_pts
    valid_error = float(np.abs(signed[paired]).mean()) if paired.any() else None
    video_q = sum(row["delivered"]["video"] for row in records) / len(records)
    audio_q = sum(row["audio_bytes"] for row in records if row["delivered"]["audio"]) / (len(audio) * 4)
    result = {"actual_file_sha256": digest(Path(path).read_bytes()), "actual_file_bytes": Path(path).stat().st_size,
              "video_frame_sha256": video_hashes, "audio_packet_sha256": audio_hashes,
              "video_frame_pts_seconds": video_pts.tolist(), "audio_frame_pts_seconds": audio_pts,
              "audio_samples_per_channel": len(audio), "video_frames": len(video),
              "content_fidelity_passed": fidelity, "source_delivery_video_fraction": video_q,
              "source_delivery_audio_fraction": audio_q, "joint_delivery_completion": video_q * audio_q,
              "valid_alignment_coverage": float(paired.mean()), "valid_alignment_clock_error_seconds": valid_error,
              "signed_relative_audio_clock_offset_seconds": float(signed.mean()),
              "missing_alignment_penalty": 1 - float(paired.mean()),
              "clock_penalty": 1 - float(paired.mean()) + float(paired.mean()) * min((valid_error or 0) / .040, 1),
              "audio_packet_clock_max_error_seconds": audio_clock_error,
              "clock_zero_for_matched_pts_is_structural": True, "independent_lip_sync_qualification": False,
              "readback_cost": elapsed(before)}
    save_json(Path(directory) / "readback.json", result)
    if not fidelity:
        raise ValueError("Actual decoded AV payload differs from committed source or placeholder bytes")
    return result
